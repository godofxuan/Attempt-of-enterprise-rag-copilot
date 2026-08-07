from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.external_datasets.financebench import FinanceBenchPreparedCase
from app.external_datasets.financebench_page_eval import (
    FinanceBenchPageCaseResult,
)


FinanceBenchPrimaryFailure = Literal[
    "document_miss_top5",
    "document_ranking_miss",
    "page_ranking_miss",
    "partial_multi_page_recall",
    "unscorable_locator",
]
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


class FinanceBenchFailureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinanceBenchPageExtractionSignal(FinanceBenchFailureModel):
    doc_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    indexed_chunk_count: int = Field(ge=0)
    evidence_token_count: int = Field(ge=0)
    best_chunk_token_recall: float = Field(ge=0.0, le=1.0)
    aggregate_page_token_recall: float = Field(ge=0.0, le=1.0)
    missing_from_index: bool
    low_extraction_recall: bool
    chunk_boundary_risk: bool


class FinanceBenchFailureCaseAnalysis(FinanceBenchFailureModel):
    case_id: str = Field(min_length=1)
    primary_failure: FinanceBenchPrimaryFailure
    gold_document_best_rank: int | None = Field(default=None, ge=1)
    gold_page_count: int = Field(ge=1)
    multi_page_evidence: bool
    numeric_or_table_question: bool
    table_extraction_risk: bool
    embedding_failure_candidate: bool
    header_footer_review_required: bool = True
    extraction_signals: list[FinanceBenchPageExtractionSignal]


class FinanceBenchFailureSummary(FinanceBenchFailureModel):
    case_count: int = Field(ge=1)
    failed_case_count: int = Field(ge=1)
    primary_failure_counts: dict[str, int]
    multi_page_failure_count: int = Field(ge=0)
    numeric_or_table_failure_count: int = Field(ge=0)
    missing_gold_page_chunk_case_count: int = Field(ge=0)
    low_extraction_recall_case_count: int = Field(ge=0)
    chunk_boundary_risk_case_count: int = Field(ge=0)
    table_extraction_risk_case_count: int = Field(ge=0)
    embedding_failure_candidate_count: int = Field(ge=0)
    header_footer_human_review_case_count: int = Field(ge=0)
    parser_ablation_recommended: bool
    parser_ablation_reason: str = Field(min_length=1)


def analyze_financebench_page_failures(
    *,
    details: Sequence[FinanceBenchPageCaseResult],
    evidence_cases: Sequence[FinanceBenchPreparedCase],
    chunks: Sequence[Any],
    parser_risk_threshold: float = 0.20,
) -> tuple[FinanceBenchFailureSummary, list[FinanceBenchFailureCaseAnalysis]]:
    rows = list(details)
    if not rows:
        raise ValueError("FinanceBench failure analysis requires cases")
    if not 0.0 <= parser_risk_threshold <= 1.0:
        raise ValueError("parser risk threshold must be between zero and one")
    evidence_by_id = {item.case_id: item for item in evidence_cases}
    if len(evidence_by_id) != len(evidence_cases):
        raise ValueError("FinanceBench evidence case IDs must be unique")
    if set(evidence_by_id) != {item.case_id for item in rows}:
        raise ValueError("FinanceBench details and evidence cases are misaligned")

    chunks_by_page: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for chunk in chunks:
        locator = chunk.locator
        if locator.kind != "page":
            continue
        end = locator.end if locator.end is not None else locator.start
        if end < locator.start or end - locator.start + 1 > 100:
            continue
        for page_number in range(locator.start, end + 1):
            chunks_by_page[(chunk.doc_id, page_number)].append(chunk)

    analyses: list[FinanceBenchFailureCaseAnalysis] = []
    for row in rows:
        if row.passed:
            continue
        evidence_case = evidence_by_id[row.case_id]
        gold_doc_ids = set(evidence_case.gold_doc_ids)
        gold_rank = next(
            (
                rank
                for rank, doc_id in enumerate(row.ranked_doc_ids, start=1)
                if doc_id in gold_doc_ids
            ),
            None,
        )
        primary = _primary_failure(row, gold_rank)
        page_signals = _page_extraction_signals(
            evidence_case,
            chunks_by_page,
        )
        numeric_or_table = _is_numeric_or_table_question(evidence_case)
        low_extraction = any(item.low_extraction_recall for item in page_signals)
        analyses.append(
            FinanceBenchFailureCaseAnalysis(
                case_id=row.case_id,
                primary_failure=primary,
                gold_document_best_rank=gold_rank,
                gold_page_count=len(row.page_score.gold_pages),
                multi_page_evidence=len(row.page_score.gold_pages) > 1,
                numeric_or_table_question=numeric_or_table,
                table_extraction_risk=numeric_or_table and low_extraction,
                embedding_failure_candidate=(
                    primary == "document_miss_top5"
                    and not any(item.missing_from_index for item in page_signals)
                    and not low_extraction
                ),
                extraction_signals=page_signals,
            )
        )
    if not analyses:
        raise ValueError("FinanceBench failure analysis found no failed cases")

    primary_counts = Counter(item.primary_failure for item in analyses)
    parser_risk_cases = sum(
        any(
            signal.missing_from_index
            or signal.low_extraction_recall
            or signal.chunk_boundary_risk
            for signal in item.extraction_signals
        )
        for item in analyses
    )
    parser_risk_rate = parser_risk_cases / len(analyses)
    parser_recommended = parser_risk_rate >= parser_risk_threshold
    reason = (
        f"{parser_risk_cases}/{len(analyses)} failed cases have a deterministic "
        f"parser-risk signal; threshold={parser_risk_threshold:.2f}."
    )
    return (
        FinanceBenchFailureSummary(
            case_count=len(rows),
            failed_case_count=len(analyses),
            primary_failure_counts=dict(sorted(primary_counts.items())),
            multi_page_failure_count=sum(
                item.multi_page_evidence for item in analyses
            ),
            numeric_or_table_failure_count=sum(
                item.numeric_or_table_question for item in analyses
            ),
            missing_gold_page_chunk_case_count=sum(
                any(signal.missing_from_index for signal in item.extraction_signals)
                for item in analyses
            ),
            low_extraction_recall_case_count=sum(
                any(
                    signal.low_extraction_recall
                    for signal in item.extraction_signals
                )
                for item in analyses
            ),
            chunk_boundary_risk_case_count=sum(
                any(
                    signal.chunk_boundary_risk
                    for signal in item.extraction_signals
                )
                for item in analyses
            ),
            table_extraction_risk_case_count=sum(
                item.table_extraction_risk for item in analyses
            ),
            embedding_failure_candidate_count=sum(
                item.embedding_failure_candidate for item in analyses
            ),
            header_footer_human_review_case_count=len(analyses),
            parser_ablation_recommended=parser_recommended,
            parser_ablation_reason=reason,
        ),
        analyses,
    )


def _primary_failure(
    row: FinanceBenchPageCaseResult,
    gold_document_best_rank: int | None,
) -> FinanceBenchPrimaryFailure:
    max_cutoff = row.page_score.cutoffs[-1]
    if (
        max_cutoff.returned_hit_count == 0
        or max_cutoff.page_locator_coverage < 1.0
    ):
        return "unscorable_locator"
    if 0.0 < max_cutoff.page_recall < 1.0:
        return "partial_multi_page_recall"
    if gold_document_best_rank is None:
        return "document_miss_top5"
    if gold_document_best_rank > 1:
        return "document_ranking_miss"
    return "page_ranking_miss"


def _page_extraction_signals(
    evidence_case: FinanceBenchPreparedCase,
    chunks_by_page: dict[tuple[str, int], list[Any]],
) -> list[FinanceBenchPageExtractionSignal]:
    evidence_by_page: dict[tuple[str, int], list[str]] = defaultdict(list)
    for item in evidence_case.evidence:
        evidence_by_page[(item.doc_id, item.page_number)].append(
            item.evidence_text
        )
    signals: list[FinanceBenchPageExtractionSignal] = []
    for (doc_id, page_number), snippets in sorted(evidence_by_page.items()):
        page_chunks = chunks_by_page.get((doc_id, page_number), [])
        evidence_tokens = _tokens(" ".join(snippets))
        chunk_tokens = [_tokens(item.text) for item in page_chunks]
        best_recall = max(
            (_token_recall(evidence_tokens, tokens) for tokens in chunk_tokens),
            default=0.0,
        )
        aggregate_tokens = set().union(*chunk_tokens) if chunk_tokens else set()
        aggregate_recall = _token_recall(evidence_tokens, aggregate_tokens)
        missing = not page_chunks
        low_recall = bool(evidence_tokens) and aggregate_recall < 0.50
        boundary_risk = (
            aggregate_recall >= 0.80
            and best_recall < 0.60
            and aggregate_recall - best_recall >= 0.20
        )
        signals.append(
            FinanceBenchPageExtractionSignal(
                doc_id=doc_id,
                page_number=page_number,
                indexed_chunk_count=len(page_chunks),
                evidence_token_count=len(evidence_tokens),
                best_chunk_token_recall=best_recall,
                aggregate_page_token_recall=aggregate_recall,
                missing_from_index=missing,
                low_extraction_recall=low_recall,
                chunk_boundary_risk=boundary_risk,
            )
        )
    return signals


def _is_numeric_or_table_question(case: FinanceBenchPreparedCase) -> bool:
    text = " ".join(
        [
            case.answer,
            case.question_type,
            case.question_reasoning or "",
        ]
    ).lower()
    return bool(re.search(r"\d", case.answer)) or any(
        marker in text
        for marker in ("metric", "calculation", "percentage", "numeric", "table")
    )


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(text.lower()))


def _token_recall(gold: set[str], observed: set[str]) -> float:
    return len(gold & observed) / len(gold) if gold else 0.0


__all__ = [
    "FinanceBenchFailureCaseAnalysis",
    "FinanceBenchFailureSummary",
    "FinanceBenchPageExtractionSignal",
    "analyze_financebench_page_failures",
]
