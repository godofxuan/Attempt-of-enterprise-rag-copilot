"""Serving-only reranking admission; historical replay implementation stays frozen."""

import math
import time
from collections import Counter

from app.domain.queries import SearchRequest
from app.domain.retrieved_security import (
    AdmittedEvidenceChunk,
    GuardDecision,
    GuardedSearchResult,
    QuarantineSummary,
    ScannedContentUnit,
)
from app.retrieval.pipeline import RankedSearchPool
from app.security.retrieved_admission import (
    GuardedAdmissionOutcome,
    RetrievedContentAdmission,
    _CounterBuilder,
    _search_context_chars,
    _search_metadata,
    _security_stop,
    _summary,
)


class RerankingContentAdmission(RetrievedContentAdmission):
    def __init__(self, *, search_scorer, guard=None):
        super().__init__(guard=guard)
        self.search_scorer = search_scorer

    def admit_search(
        self,
        pool: RankedSearchPool,
        request: SearchRequest,
    ) -> GuardedAdmissionOutcome:
        candidates = pool.candidates[: request.candidate_k]
        builder = _CounterBuilder(candidate_count=len(candidates))
        summaries: list[QuarantineSummary] = []
        provenance: list[ScannedContentUnit] = []
        matched_decisions: dict[str, GuardDecision] = {}
        matched_summaries: set[str] = set()
        blocked = self._scan_split_windows(
            candidates,
            builder=builder,
            summaries=summaries,
            provenance=provenance,
            matched_decisions=matched_decisions,
            matched_summaries=matched_summaries,
        )

        selected: list[AdmittedEvidenceChunk] = []
        per_doc: Counter[str] = Counter()
        for candidate in candidates:
            hit = candidate.hit
            if hit.chunk_id in blocked:
                continue
            if self.search_scorer is None and per_doc[hit.doc_id] >= request.max_chunks_per_doc:
                continue
            if candidate.rank > request.top_k:
                builder.top_up_attempts = 1

            matched_decision = self._matched_decision(
                candidate,
                builder=builder,
                summaries=summaries,
                provenance=provenance,
                cache=matched_decisions,
                summarized=matched_summaries,
            )
            metadata_decision = self._scan_recorded(
                _search_metadata(candidate),
                provenance=provenance,
                operation="search",
                surface="metadata",
                internal_item_key=hit.chunk_id,
            )
            builder.record(metadata_decision)
            if metadata_decision.disposition == "QUARANTINE":
                summaries.append(_summary(candidate.hit.chunk_id, "metadata", metadata_decision))

            context_decision: GuardDecision | None = None
            admitted_hit = hit
            if hit.context_from_parent and hit.context_text == hit.matched_text:
                admitted_hit = hit.model_copy(update={"context_from_parent": False})
            elif hit.context_from_parent:
                context_decision = self._scan_recorded(
                    hit.context_text,
                    provenance=provenance,
                    operation="search",
                    surface="parent",
                    internal_item_key=hit.chunk_id,
                )
                builder.record(context_decision)
                if context_decision.disposition == "QUARANTINE":
                    summaries.append(_summary(hit.chunk_id, "parent", context_decision))
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
            if self.search_scorer is None and len(selected) == request.top_k:
                break

        ranking_counts: dict[str, int] = {}
        if self.search_scorer is not None:
            # Only fully admitted text crosses into the scoring model. Preserve
            # the original admission objects; sorting cannot mint new evidence.
            started = time.monotonic()
            from app.retrieval.scorer_errors import RerankerFailure, failure_reason

            try:
                scores = (
                    list(
                        self.search_scorer(
                            request.query, tuple(item.hit.matched_text for item in selected)
                        )
                    )
                    if selected
                    else []
                )
            except Exception as exc:
                raise RerankerFailure(failure_reason(exc)) from None
            if len(scores) != len(selected) or any(
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not math.isfinite(score)
                for score in scores
            ):
                raise RerankerFailure("invalid_scores")
            ranking_counts = {
                "reranker_scored": len(selected),
                "reranker_calls": int(bool(selected)),
                "reranker_elapsed_ms": int((time.monotonic() - started) * 1000),
            }
            ranked = sorted(zip(scores, selected, strict=True), key=lambda pair: -pair[0])
            selected = []
            per_doc.clear()
            for _, admitted in ranked:
                if per_doc[admitted.hit.doc_id] >= request.max_chunks_per_doc:
                    continue
                selected.append(admitted)
                per_doc[admitted.hit.doc_id] += 1
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
            stage_counts={**pool.stage_counts, **ranking_counts, "returned": len(selected)},
            stop_reason=pool.stop_reason,
        )
        counters = builder.build()
        return GuardedAdmissionOutcome(
            result=result,
            quarantine_summaries=tuple(summaries),
            scan_provenance=tuple(provenance),
            security_counters=counters,
            security_stop_reason=_security_stop(counters),
            context_chars=sum(_search_context_chars(item) for item in selected),
        )
