from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.queries import SearchHit


MAX_PAGES_PER_HIT = 100
PageRetrievalFailureCode = Literal[
    "no_retrieval_hits",
    "unscorable_page_locator",
    "gold_pages_missing",
]


class PageRetrievalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PageReference(PageRetrievalModel):
    doc_id: str = Field(min_length=1, max_length=500)
    page_number: int = Field(ge=1, le=1_000_000)


class RankedPageReference(PageReference):
    first_hit_rank: int = Field(ge=1)
    chunk_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("chunk_ids")
    @classmethod
    def validate_unique_chunk_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ranked page chunk IDs must be unique")
        return values


class PageCutoffMetrics(PageRetrievalModel):
    cutoff: int = Field(ge=1, le=100)
    returned_hit_count: int = Field(ge=0)
    scorable_hit_count: int = Field(ge=0)
    unique_retrieved_page_count: int = Field(ge=0)
    matched_gold_page_count: int = Field(ge=0)
    gold_page_count: int = Field(ge=1)
    page_hit: bool
    page_recall: float = Field(ge=0.0, le=1.0)
    page_precision: float = Field(ge=0.0, le=1.0)
    page_locator_coverage: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_fractions(self) -> "PageCutoffMetrics":
        if self.scorable_hit_count > self.returned_hit_count:
            raise ValueError("scorable hit count exceeds returned hit count")
        if self.matched_gold_page_count > self.gold_page_count:
            raise ValueError("matched page count exceeds gold page count")
        if self.matched_gold_page_count > self.unique_retrieved_page_count:
            raise ValueError("matched page count exceeds retrieved page count")
        expected_recall = self.matched_gold_page_count / self.gold_page_count
        expected_precision = (
            self.matched_gold_page_count / self.unique_retrieved_page_count
            if self.unique_retrieved_page_count
            else 0.0
        )
        expected_coverage = (
            self.scorable_hit_count / self.returned_hit_count
            if self.returned_hit_count
            else 0.0
        )
        if abs(self.page_recall - expected_recall) > 1e-12:
            raise ValueError("page recall does not match page counts")
        if abs(self.page_precision - expected_precision) > 1e-12:
            raise ValueError("page precision does not match page counts")
        if abs(self.page_locator_coverage - expected_coverage) > 1e-12:
            raise ValueError("page locator coverage does not match hit counts")
        if self.page_hit != (self.matched_gold_page_count > 0):
            raise ValueError("page hit does not match matched page count")
        return self


class PageRetrievalCaseScore(PageRetrievalModel):
    case_id: str = Field(min_length=1, max_length=500)
    gold_pages: list[PageReference] = Field(min_length=1, max_length=100)
    ranked_pages: list[RankedPageReference] = Field(default_factory=list)
    cutoffs: list[PageCutoffMetrics] = Field(min_length=1, max_length=10)
    passed_at_max_cutoff: bool
    failure_codes: list[PageRetrievalFailureCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score(self) -> "PageRetrievalCaseScore":
        gold_keys = [
            (item.doc_id, item.page_number) for item in self.gold_pages
        ]
        if len(gold_keys) != len(set(gold_keys)):
            raise ValueError("gold page references must be unique")
        ranked_keys = [
            (item.doc_id, item.page_number) for item in self.ranked_pages
        ]
        if len(ranked_keys) != len(set(ranked_keys)):
            raise ValueError("ranked page references must be unique")
        cutoff_values = [item.cutoff for item in self.cutoffs]
        if cutoff_values != sorted(set(cutoff_values)):
            raise ValueError("page cutoffs must be sorted and unique")
        if len(self.failure_codes) != len(set(self.failure_codes)):
            raise ValueError("page retrieval failure codes must be unique")
        expected_pass = (
            self.cutoffs[-1].page_recall == 1.0
            and self.cutoffs[-1].page_locator_coverage == 1.0
        )
        if self.passed_at_max_cutoff != expected_pass:
            raise ValueError("page retrieval pass does not match max cutoff")
        if self.passed_at_max_cutoff and self.failure_codes:
            raise ValueError("passed page retrieval cannot contain failures")
        if not self.passed_at_max_cutoff and not self.failure_codes:
            raise ValueError("failed page retrieval requires failure codes")
        return self


def score_page_retrieval(
    *,
    case_id: str,
    hits: Sequence[SearchHit],
    gold_pages: Sequence[PageReference],
    cutoffs: Sequence[int] = (1, 3, 5),
) -> PageRetrievalCaseScore:
    cutoff_values = _validate_cutoffs(cutoffs)
    normalized_gold = sorted(
        [PageReference.model_validate(item) for item in gold_pages],
        key=lambda item: (item.doc_id, item.page_number),
    )
    gold_keys = {(item.doc_id, item.page_number) for item in normalized_gold}
    if not normalized_gold or len(normalized_gold) != len(gold_keys):
        raise ValueError("gold page references must be non-empty and unique")

    hit_list = list(hits)
    ranked_pages = _ranked_pages(hit_list[: cutoff_values[-1]])
    cutoff_metrics = [
        _score_cutoff(hit_list, gold_keys, cutoff) for cutoff in cutoff_values
    ]
    max_metrics = cutoff_metrics[-1]
    failures: list[PageRetrievalFailureCode] = []
    if max_metrics.returned_hit_count == 0:
        failures.append("no_retrieval_hits")
    if max_metrics.page_locator_coverage < 1.0:
        failures.append("unscorable_page_locator")
    if max_metrics.page_recall < 1.0:
        failures.append("gold_pages_missing")
    passed = (
        max_metrics.page_recall == 1.0
        and max_metrics.page_locator_coverage == 1.0
    )
    return PageRetrievalCaseScore(
        case_id=case_id,
        gold_pages=normalized_gold,
        ranked_pages=ranked_pages,
        cutoffs=cutoff_metrics,
        passed_at_max_cutoff=passed,
        failure_codes=failures,
    )


def _validate_cutoffs(cutoffs: Sequence[int]) -> list[int]:
    values = list(cutoffs)
    if (
        not values
        or any(isinstance(value, bool) or not isinstance(value, int) for value in values)
        or any(value < 1 or value > 100 for value in values)
        or values != sorted(set(values))
    ):
        raise ValueError("page cutoffs must be sorted unique integers from 1 to 100")
    return values


def _page_keys(hit: SearchHit) -> list[tuple[str, int]]:
    locator = hit.locator
    if locator is None or locator.kind != "page":
        return []
    end = locator.end if locator.end is not None else locator.start
    page_count = end - locator.start + 1
    if page_count < 1 or page_count > MAX_PAGES_PER_HIT:
        return []
    return [
        (hit.doc_id, page_number)
        for page_number in range(locator.start, end + 1)
    ]


def _ranked_pages(hits: Sequence[SearchHit]) -> list[RankedPageReference]:
    pages: dict[tuple[str, int], dict[str, object]] = {}
    for rank, hit in enumerate(hits, start=1):
        for doc_id, page_number in _page_keys(hit):
            item = pages.setdefault(
                (doc_id, page_number),
                {"first_hit_rank": rank, "chunk_ids": []},
            )
            chunk_ids = item["chunk_ids"]
            assert isinstance(chunk_ids, list)
            if hit.chunk_id not in chunk_ids:
                chunk_ids.append(hit.chunk_id)
    return [
        RankedPageReference(
            doc_id=doc_id,
            page_number=page_number,
            first_hit_rank=int(item["first_hit_rank"]),
            chunk_ids=list(item["chunk_ids"]),
        )
        for (doc_id, page_number), item in pages.items()
    ]


def _score_cutoff(
    hits: Sequence[SearchHit],
    gold_keys: set[tuple[str, int]],
    cutoff: int,
) -> PageCutoffMetrics:
    selected = list(hits[:cutoff])
    page_keys: set[tuple[str, int]] = set()
    scorable_hits = 0
    for hit in selected:
        keys = _page_keys(hit)
        if keys:
            scorable_hits += 1
            page_keys.update(keys)
    matched = page_keys & gold_keys
    return PageCutoffMetrics(
        cutoff=cutoff,
        returned_hit_count=len(selected),
        scorable_hit_count=scorable_hits,
        unique_retrieved_page_count=len(page_keys),
        matched_gold_page_count=len(matched),
        gold_page_count=len(gold_keys),
        page_hit=bool(matched),
        page_recall=len(matched) / len(gold_keys),
        page_precision=(len(matched) / len(page_keys) if page_keys else 0.0),
        page_locator_coverage=(scorable_hits / len(selected) if selected else 0.0),
    )


__all__ = [
    "MAX_PAGES_PER_HIT",
    "PageCutoffMetrics",
    "PageReference",
    "PageRetrievalCaseScore",
    "RankedPageReference",
    "score_page_retrieval",
]
