from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.queries import FindResult, OpenResult, SearchRequest
from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    MAX_SCAN_CHARS,
    RULE_SPECS,
    AdmittedEvidenceChunk,
    AdmittedFindMatch,
    AdmittedOpenResult,
    GuardDecision,
    GuardedFindResult,
    GuardedOpenAdmittedResult,
    GuardedOpenQuarantinedResult,
    GuardedSearchResult,
    QuarantineSummary,
    RiskCategory,
    SecurityCounters,
)
from app.retrieval.pipeline import RankedSearchCandidate, RankedSearchPool
from app.security.retrieved_content import (
    RetrievedContentGuard,
    normalized_content_length,
)


MAX_SPLIT_FRAGMENTS = 3
MAX_SPLIT_CHARS = 12_000
_SPLIT_RULE_ID = "RCG-SPLIT-ADJACENT-001"

GuardedAdmissionPayload = (
    GuardedSearchResult
    | GuardedFindResult
    | GuardedOpenAdmittedResult
    | GuardedOpenQuarantinedResult
)


class GuardedAdmissionOutcome(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    result: GuardedAdmissionPayload
    quarantine_summaries: tuple[QuarantineSummary, ...] = Field(
        default_factory=tuple
    )
    security_counters: SecurityCounters
    security_stop_reason: Literal["evidence_filtered"] | None = None
    context_chars: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_outcome(self) -> GuardedAdmissionOutcome:
        if (
            len(self.quarantine_summaries)
            != self.security_counters.quarantined_count
        ):
            raise ValueError(
                "quarantine summaries must match quarantined content count"
            )
        filtered = (
            self.security_counters.candidate_count > 0
            and self.security_counters.post_guard_evidence_count == 0
            and self.security_counters.quarantined_count > 0
        )
        if filtered != (self.security_stop_reason == "evidence_filtered"):
            raise ValueError(
                "evidence_filtered must exactly identify an all-quarantined result"
            )
        return self


@dataclass
class _CounterBuilder:
    candidate_count: int
    scanned_count: int = 0
    admitted_count: int = 0
    quarantined_count: int = 0
    scanned_chars: int = 0
    decoded_candidate_count: int = 0
    top_up_attempts: int = 0
    post_guard_evidence_count: int = 0
    guard_error_count: int = 0
    risk_categories: set[RiskCategory] = field(default_factory=set)
    rule_ids: set[str] = field(default_factory=set)

    def record(self, decision: GuardDecision) -> None:
        self.scanned_count += 1
        self.scanned_chars += decision.scanned_length
        self.decoded_candidate_count += decision.decoded_view_count
        self.risk_categories.update(decision.risk_categories)
        self.rule_ids.update(decision.rule_ids)
        if decision.disposition == "ADMIT":
            self.admitted_count += 1
        else:
            self.quarantined_count += 1
        if decision.guard_error:
            self.guard_error_count += 1

    def build(self) -> SecurityCounters:
        return SecurityCounters(
            candidate_count=self.candidate_count,
            scanned_count=self.scanned_count,
            admitted_count=self.admitted_count,
            quarantined_count=self.quarantined_count,
            scanned_chars=self.scanned_chars,
            decoded_candidate_count=self.decoded_candidate_count,
            top_up_attempts=self.top_up_attempts,
            post_guard_evidence_count=self.post_guard_evidence_count,
            guard_error_count=self.guard_error_count,
            risk_categories=tuple(sorted(self.risk_categories)),
            rule_ids=tuple(sorted(self.rule_ids)),
            detector_version=DETECTOR_VERSION,
        )


class RetrievedContentAdmission:
    def __init__(self, *, guard: object | None = None) -> None:
        self.guard = guard if guard is not None else RetrievedContentGuard()
        if not callable(getattr(self.guard, "scan", None)):
            raise ValueError("retrieved-content Guard must provide scan(content)")

    def admit_search(
        self,
        pool: RankedSearchPool,
        request: SearchRequest,
    ) -> GuardedAdmissionOutcome:
        candidates = pool.candidates[: request.candidate_k]
        builder = _CounterBuilder(candidate_count=len(candidates))
        summaries: list[QuarantineSummary] = []
        matched_decisions: dict[str, GuardDecision] = {}
        matched_summaries: set[str] = set()
        blocked = self._scan_split_windows(
            candidates,
            builder=builder,
            summaries=summaries,
            matched_decisions=matched_decisions,
            matched_summaries=matched_summaries,
        )

        selected: list[AdmittedEvidenceChunk] = []
        per_doc: Counter[str] = Counter()
        for candidate in candidates:
            hit = candidate.hit
            if hit.chunk_id in blocked:
                continue
            if per_doc[hit.doc_id] >= request.max_chunks_per_doc:
                continue
            if candidate.rank > request.top_k:
                builder.top_up_attempts = 1

            matched_decision = self._matched_decision(
                candidate,
                builder=builder,
                summaries=summaries,
                cache=matched_decisions,
                summarized=matched_summaries,
            )
            metadata_decision = self._scan(
                _search_metadata(candidate),
            )
            builder.record(metadata_decision)
            if metadata_decision.disposition == "QUARANTINE":
                summaries.append(
                    _summary(candidate.hit.chunk_id, "metadata", metadata_decision)
                )

            context_decision: GuardDecision | None = None
            admitted_hit = hit
            if hit.context_from_parent and hit.context_text == hit.matched_text:
                admitted_hit = hit.model_copy(
                    update={"context_from_parent": False}
                )
            elif hit.context_from_parent:
                context_decision = self._scan(hit.context_text)
                builder.record(context_decision)
                if context_decision.disposition == "QUARANTINE":
                    summaries.append(
                        _summary(hit.chunk_id, "parent", context_decision)
                    )
                    admitted_hit = hit.model_copy(
                        update={
                            "context_text": hit.matched_text,
                            "context_from_parent": False,
                        }
                    )
                    context_decision = None

            if (
                matched_decision.disposition == "QUARANTINE"
                or metadata_decision.disposition == "QUARANTINE"
            ):
                continue

            admitted = AdmittedEvidenceChunk(
                hit=admitted_hit,
                matched_decision=matched_decision,
                context_decision=context_decision,
                metadata_decision=metadata_decision,
            )
            selected.append(admitted)
            per_doc[hit.doc_id] += 1
            if len(selected) == request.top_k:
                break

        builder.post_guard_evidence_count = len(selected)
        result = GuardedSearchResult(
            request_id=pool.request_id,
            query=pool.query,
            mode=pool.mode,
            index_run_id=pool.index_run_id,
            manifest_sha256=pool.manifest_sha256,
            hits=tuple(selected),
            visible_candidate_count=pool.visible_candidate_count,
            internal_denied_count=pool.internal_denied_count,
            stage_counts={**pool.stage_counts, "returned": len(selected)},
            stop_reason=pool.stop_reason,
        )
        counters = builder.build()
        return GuardedAdmissionOutcome(
            result=result,
            quarantine_summaries=tuple(summaries),
            security_counters=counters,
            security_stop_reason=_security_stop(counters),
            context_chars=sum(_search_context_chars(item) for item in selected),
        )

    def admit_find(self, result: FindResult) -> GuardedAdmissionOutcome:
        builder = _CounterBuilder(candidate_count=len(result.matches))
        summaries: list[QuarantineSummary] = []
        admitted: list[AdmittedFindMatch] = []
        for match in result.matches:
            preview_decision = self._scan(match.preview)
            metadata_decision = self._scan("\n".join(match.section_path))
            builder.record(preview_decision)
            builder.record(metadata_decision)
            if preview_decision.disposition == "QUARANTINE":
                summaries.append(
                    _summary(match.chunk_id, "find_preview", preview_decision)
                )
            if metadata_decision.disposition == "QUARANTINE":
                summaries.append(
                    _summary(match.chunk_id, "metadata", metadata_decision)
                )
            if (
                preview_decision.disposition == "QUARANTINE"
                or metadata_decision.disposition == "QUARANTINE"
            ):
                continue
            admitted.append(
                AdmittedFindMatch(
                    match=match,
                    preview_decision=preview_decision,
                    metadata_decision=metadata_decision,
                )
            )

        builder.post_guard_evidence_count = len(admitted)
        guarded = GuardedFindResult(
            request_id=result.request_id,
            doc_id=result.doc_id,
            matches=tuple(admitted),
            stop_reason=result.stop_reason,
        )
        counters = builder.build()
        return GuardedAdmissionOutcome(
            result=guarded,
            quarantine_summaries=tuple(summaries),
            security_counters=counters,
            security_stop_reason=_security_stop(counters),
            context_chars=sum(_find_context_chars(item) for item in admitted),
        )

    def admit_open(self, result: OpenResult) -> GuardedAdmissionOutcome:
        builder = _CounterBuilder(candidate_count=1)
        summaries: list[QuarantineSummary] = []
        content_decision = self._scan(result.content)
        metadata_decision = self._scan(_open_metadata(result))
        builder.record(content_decision)
        builder.record(metadata_decision)
        if content_decision.disposition == "QUARANTINE":
            summaries.append(_summary(result.target_id, "open", content_decision))
        if metadata_decision.disposition == "QUARANTINE":
            summaries.append(
                _summary(result.target_id, "metadata", metadata_decision)
            )

        if (
            content_decision.disposition == "ADMIT"
            and metadata_decision.disposition == "ADMIT"
        ):
            guarded: GuardedAdmissionPayload = GuardedOpenAdmittedResult(
                item=AdmittedOpenResult(
                    result=result,
                    content_decision=content_decision,
                    metadata_decision=metadata_decision,
                )
            )
            builder.post_guard_evidence_count = 1
            context_chars = len(result.content) + len(_open_metadata(result))
        else:
            guarded = GuardedOpenQuarantinedResult(request_id=result.request_id)
            context_chars = 0

        counters = builder.build()
        return GuardedAdmissionOutcome(
            result=guarded,
            quarantine_summaries=tuple(summaries),
            security_counters=counters,
            security_stop_reason=_security_stop(counters),
            context_chars=context_chars,
        )

    def _matched_decision(
        self,
        candidate: RankedSearchCandidate,
        *,
        builder: _CounterBuilder,
        summaries: list[QuarantineSummary],
        cache: dict[str, GuardDecision],
        summarized: set[str],
    ) -> GuardDecision:
        chunk_id = candidate.hit.chunk_id
        decision = cache.get(chunk_id)
        if decision is None:
            decision = self._scan(candidate.hit.matched_text)
            cache[chunk_id] = decision
            builder.record(decision)
        if decision.disposition == "QUARANTINE" and chunk_id not in summarized:
            summaries.append(_summary(chunk_id, "matched", decision))
            summarized.add(chunk_id)
        return decision

    def _scan_split_windows(
        self,
        candidates: tuple[RankedSearchCandidate, ...],
        *,
        builder: _CounterBuilder,
        summaries: list[QuarantineSummary],
        matched_decisions: dict[str, GuardDecision],
        matched_summaries: set[str],
    ) -> set[str]:
        by_document: dict[str, list[RankedSearchCandidate]] = defaultdict(list)
        for candidate in candidates:
            by_document[candidate.hit.doc_id].append(candidate)

        blocked: set[str] = set()
        for document_candidates in by_document.values():
            ordered = sorted(document_candidates, key=_document_order)
            for window_size in range(2, MAX_SPLIT_FRAGMENTS + 1):
                for start in range(0, len(ordered) - window_size + 1):
                    window = ordered[start : start + window_size]
                    if not _is_adjacent_window(window):
                        continue
                    aggregate = "\n".join(item.hit.matched_text for item in window)
                    if len(aggregate) > MAX_SCAN_CHARS:
                        continue
                    if normalized_content_length(aggregate) > MAX_SPLIT_CHARS:
                        continue
                    aggregate_decision = self._scan(aggregate)
                    if aggregate_decision.disposition == "ADMIT":
                        builder.record(aggregate_decision)
                        continue

                    individual = [
                        self._matched_decision(
                            item,
                            builder=builder,
                            summaries=summaries,
                            cache=matched_decisions,
                            summarized=matched_summaries,
                        )
                        for item in window
                    ]
                    if aggregate_decision.guard_error:
                        builder.record(aggregate_decision)
                        summaries.append(
                            _summary(
                                _aggregate_key(window),
                                "aggregate",
                                aggregate_decision,
                            )
                        )
                        blocked.update(item.hit.chunk_id for item in window)
                    elif all(
                        decision.disposition == "ADMIT" for decision in individual
                    ):
                        split_decision = _with_split_rule(aggregate_decision)
                        builder.record(split_decision)
                        summaries.append(
                            _summary(
                                _aggregate_key(window),
                                "aggregate",
                                split_decision,
                            )
                        )
                        blocked.update(item.hit.chunk_id for item in window)
                    else:
                        builder.record(aggregate_decision)
                        summaries.append(
                            _summary(
                                _aggregate_key(window),
                                "aggregate",
                                aggregate_decision,
                            )
                        )
                        blocked.update(item.hit.chunk_id for item in window)
        return blocked

    def _scan(self, content: str) -> GuardDecision:
        try:
            decision = self.guard.scan(content)
            if not isinstance(decision, GuardDecision):
                raise TypeError("Guard returned an invalid decision")
            return decision
        except Exception:
            return GuardDecision(
                disposition="QUARANTINE",
                max_severity="error",
                risk_categories=("guard_error",),
                rule_ids=("RCG-GUARD-ERROR",),
                detector_version=DETECTOR_VERSION,
                original_length=len(content),
                normalized_length=0,
                scanned_length=0,
                decoded_view_count=0,
                guard_error=True,
            )


def _summary(
    item_key: str,
    field_kind: Literal[
        "matched",
        "parent",
        "find_preview",
        "open",
        "metadata",
        "aggregate",
    ],
    decision: GuardDecision,
) -> QuarantineSummary:
    return QuarantineSummary(
        internal_item_key=item_key,
        field_kind=field_kind,
        decision=decision,
    )


def _with_split_rule(decision: GuardDecision) -> GuardDecision:
    if decision.guard_error:
        return decision
    rule_ids = tuple(sorted({*decision.rule_ids, _SPLIT_RULE_ID}))
    categories = tuple(sorted({RULE_SPECS[rule_id][0] for rule_id in rule_ids}))
    return GuardDecision(
        disposition="QUARANTINE",
        max_severity="quarantine",
        risk_categories=categories,
        rule_ids=rule_ids,
        detector_version=DETECTOR_VERSION,
        original_length=decision.original_length,
        normalized_length=decision.normalized_length,
        scanned_length=decision.scanned_length,
        decoded_view_count=decision.decoded_view_count,
        guard_error=False,
    )


def _document_order(candidate: RankedSearchCandidate) -> tuple:
    locator = candidate.hit.locator
    if locator is None:
        return ("", candidate.rank, candidate.rank, candidate.hit.chunk_id)
    end = locator.end if locator.end is not None else locator.start
    return (locator.kind, locator.start, end, candidate.hit.chunk_id)


def _is_adjacent_window(window: list[RankedSearchCandidate]) -> bool:
    locators = [candidate.hit.locator for candidate in window]
    if any(locator is None for locator in locators):
        return False
    for left, right in zip(locators, locators[1:]):
        if left.kind != right.kind:
            return False
        left_end = left.end if left.end is not None else left.start
        if right.start > left_end + 1:
            return False
    return True


def _aggregate_key(window: list[RankedSearchCandidate]) -> str:
    return ":".join(candidate.hit.chunk_id for candidate in window)


def _search_metadata(candidate: RankedSearchCandidate) -> str:
    hit = candidate.hit
    parts = [
        candidate.document_title,
        hit.source_path,
        *hit.section_path,
        hit.locator.label if hit.locator is not None else None,
        hit.version,
    ]
    return "\n".join(part for part in parts if part)


def _open_metadata(result: OpenResult) -> str:
    return "\n".join([result.source_path, *result.section_path])


def _search_context_chars(item: AdmittedEvidenceChunk) -> int:
    hit = item.hit
    return (
        len(hit.matched_text)
        + len(hit.context_text)
        + len(hit.version)
        + len("\n".join([hit.source_path, *hit.section_path]))
    )


def _find_context_chars(item: AdmittedFindMatch) -> int:
    return len(item.match.preview) + len("\n".join(item.match.section_path))


def _security_stop(counters: SecurityCounters) -> str | None:
    if (
        counters.candidate_count > 0
        and counters.post_guard_evidence_count == 0
        and counters.quarantined_count > 0
    ):
        return "evidence_filtered"
    return None


__all__ = [
    "GuardedAdmissionOutcome",
    "MAX_SPLIT_CHARS",
    "MAX_SPLIT_FRAGMENTS",
    "RetrievedContentAdmission",
]
