from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.controller_v2 import ControllerState
from app.agent.runner_v2 import ExtractiveResponseBuilder
from app.domain.evidence import AnswerResponse


CandidateArm = Literal[
    "current",
    "decompose_only",
    "select_only",
    "combined",
]
CandidateDecision = Literal[
    "DEVELOPMENT_CANDIDATE_HOLD_FOR_FIXED_VALIDATION",
    "DEVELOPMENT_CANDIDATE_REJECTED",
]

_CLAUSE_SEPARATOR = re.compile(
    r"\s+(?:and|or|versus|vs\.?)\s+|[,;]",
    flags=re.IGNORECASE,
)
_TOKEN = re.compile(r"[A-Za-z0-9]+")


def decompose_query(question: str) -> list[str]:
    """Return the frozen original-plus-two-clause development policy."""
    original = " ".join(question.split())
    if not original:
        raise ValueError("question must not be empty")
    clauses = []
    for raw_clause in _CLAUSE_SEPARATOR.split(original):
        clause = raw_clause.strip(" .?!:\t\r\n")
        if len(_TOKEN.findall(clause)) < 3:
            continue
        if clause.casefold() == original.casefold():
            continue
        if clause.casefold() not in {item.casefold() for item in clauses}:
            clauses.append(clause)
    if len(clauses) < 2:
        return [original]
    return [original, *clauses[:2]]


def fuse_query_rankings(
    rankings: Sequence[Sequence[str]],
    *,
    rrf_k: int = 60,
) -> list[str]:
    """Fuse any number of rankings using deterministic reciprocal rank fusion."""
    if not rankings:
        raise ValueError("at least one ranking is required")
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    scores: dict[str, float] = {}
    rank_vectors: dict[str, list[int]] = {}
    missing_rank = 10**9
    for source_index, ranking in enumerate(rankings):
        seen: set[str] = set()
        for rank, document_id in enumerate(ranking, start=1):
            if document_id in seen:
                continue
            seen.add(document_id)
            scores[document_id] = scores.get(document_id, 0.0) + 1.0 / (
                rrf_k + rank
            )
            vector = rank_vectors.setdefault(
                document_id,
                [missing_rank] * len(rankings),
            )
            vector[source_index] = rank
    return sorted(
        scores,
        key=lambda item: (
            -scores[item],
            min(rank_vectors[item]),
            tuple(rank_vectors[item]),
            item,
        ),
    )


def select_preferred_admitted_document_ids(
    query_rankings: Sequence[Sequence[str]],
    admitted_document_ids: Sequence[str],
    *,
    max_selected: int = 3,
) -> list[str]:
    """Select one highest-ranked admitted document for each query variant."""
    if max_selected < 1:
        raise ValueError("max_selected must be positive")
    admitted = set(admitted_document_ids)
    selected: list[str] = []
    for ranking in query_rankings:
        best = next((item for item in ranking if item in admitted), None)
        if best is not None and best not in selected:
            selected.append(best)
        if len(selected) >= max_selected:
            break
    if not selected and admitted_document_ids:
        selected.append(admitted_document_ids[0])
    return selected


class SelectiveExtractiveResponseBuilder:
    """Evaluation-only response builder constrained to admitted Agent evidence."""

    def __init__(
        self,
        *,
        query_rankings: Sequence[Sequence[str]] | None = None,
        max_selected_documents: int = 3,
    ) -> None:
        self.query_rankings = (
            [list(ranking) for ranking in query_rankings]
            if query_rankings is not None
            else None
        )
        self.max_selected_documents = max_selected_documents
        self.delegate = ExtractiveResponseBuilder(
            max_evidence_per_aspect=(
                1 if query_rankings is None else max_selected_documents
            )
        )
        self.admitted_document_ids: list[str] = []
        self.selected_document_ids: list[str] = []

    def build(self, **kwargs) -> AnswerResponse:
        state: ControllerState = kwargs["state"]
        supported = state.ledger.supported_aspects if state.ledger else []
        admitted = _document_ids_for_aspects(state, supported)
        self.admitted_document_ids = admitted
        if self.query_rankings is None:
            self.selected_document_ids = _first_document_per_aspect(
                state,
                supported,
            )
            return self.delegate.build(**kwargs)

        selected = select_preferred_admitted_document_ids(
            self.query_rankings,
            admitted,
            max_selected=self.max_selected_documents,
        )
        selected_set = set(selected)
        selected_by_aspect = {}
        for aspect, evidence_items in state.evidence_by_aspect.items():
            by_document = {item.hit.doc_id: item for item in evidence_items}
            selected_by_aspect[aspect] = [
                by_document[document_id]
                for document_id in selected
                if document_id in by_document
            ]
        self.selected_document_ids = selected
        candidate_state = state.model_copy(
            update={
                "evidence_by_aspect": {
                    aspect: items
                    for aspect, items in selected_by_aspect.items()
                    if items or aspect not in supported
                }
            }
        )
        kwargs = {**kwargs, "state": candidate_state}
        response = self.delegate.build(**kwargs)
        final_ids = list(dict.fromkeys(source.doc_id for source in response.sources))
        if not set(final_ids).issubset(selected_set):
            raise RuntimeError("response builder escaped the selected evidence set")
        self.selected_document_ids = final_ids
        return response


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MultiDocCandidateCase(_StrictModel):
    question_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    arm: CandidateArm
    gold_document_count: int = Field(ge=2)
    retrieved_document_ids: list[str]
    admitted_document_ids: list[str]
    cited_document_ids: list[str]
    retrieval_recall: float = Field(ge=0, le=1)
    retrieval_complete: float = Field(ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    citation_complete: float = Field(ge=0, le=1)
    response_mode: str = Field(min_length=1)
    selected_source_count: int = Field(ge=0, le=3)
    query_variant_count: int = Field(ge=1, le=3)
    embedding_calls: int = Field(ge=1, le=3)
    search_calls: int = Field(ge=0)
    find_calls: int = Field(ge=0)
    open_calls: int = Field(ge=0)
    tool_errors: int = Field(ge=0)
    budget_exhausted: bool
    guard_quarantined_count: int = Field(ge=0)
    security_filtered: bool
    retrieval_compute_ms: float = Field(ge=0)
    mechanism_ms: float = Field(ge=0)
    latency_ms: float = Field(ge=0)


class MultiDocCandidateSummary(_StrictModel):
    arm: CandidateArm
    case_count: int = Field(ge=1)
    retrieval_recall: float = Field(ge=0, le=1)
    retrieval_completeness: float = Field(ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    citation_completeness: float = Field(ge=0, le=1)
    answered_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    source_free_count: int = Field(ge=0)
    selected_sources_mean: float = Field(ge=0, le=3)
    query_variants_mean: float = Field(ge=1, le=3)
    embedding_calls_mean: float = Field(ge=1, le=3)
    search_calls_mean: float = Field(ge=0)
    find_calls_mean: float = Field(ge=0)
    open_calls_mean: float = Field(ge=0)
    tool_error_count: int = Field(ge=0)
    budget_exhaustion_count: int = Field(ge=0)
    guard_quarantined_count: int = Field(ge=0)
    security_filtered_count: int = Field(ge=0)
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    generation_model_calls: Literal[0] = 0
    generation_tokens: Literal[0] = 0


class MultiDocCandidateGate(_StrictModel):
    baseline_arm: Literal["current"] = "current"
    candidate_arm: Literal["combined"] = "combined"
    citation_completeness_delta_pp: float
    citation_recall_delta_pp: float
    citation_precision_delta_pp: float | None
    p95_latency_ratio: float = Field(ge=0)
    paired_fix_count: int = Field(ge=0)
    paired_regression_count: int = Field(ge=0)
    checks: dict[str, bool]
    decision: CandidateDecision


class MultiDocCandidateFailureAnalysis(_StrictModel):
    case_count: int = Field(ge=1)
    decomposed_case_count: int = Field(ge=0)
    top5_order_changed_case_count: int = Field(ge=0)
    retrieval_recall_improved_case_count: int = Field(ge=0)
    retrieval_recall_regressed_case_count: int = Field(ge=0)
    acquisition_incomplete_case_count: int = Field(ge=0)
    all_gold_admitted_case_count: int = Field(ge=0)
    admission_loss_after_complete_retrieval_count: int = Field(ge=0)
    selection_incomplete_after_complete_admission_count: int = Field(ge=0)
    citation_recall_improved_case_count: int = Field(ge=0)
    citation_recall_regressed_case_count: int = Field(ge=0)
    multi_source_citation_case_count: int = Field(ge=0)
    cited_gold_document_count: int = Field(ge=0)
    cited_noise_document_count: int = Field(ge=0)
    guard_quarantine_case_count: int = Field(ge=0)


def score_candidate_case(
    *,
    question_id_sha256: str,
    arm: CandidateArm,
    gold_document_ids: Sequence[str],
    retrieved_document_ids: Sequence[str],
    admitted_document_ids: Sequence[str],
    cited_document_ids: Sequence[str],
    response_mode: str,
    trace: dict,
    query_variant_count: int,
    embedding_calls: int,
    retrieval_compute_ms: float,
    mechanism_ms: float,
) -> MultiDocCandidateCase:
    gold = set(gold_document_ids)
    if len(gold) < 2:
        raise ValueError("candidate cases require at least two gold documents")
    retrieved = list(dict.fromkeys(retrieved_document_ids))
    admitted = list(dict.fromkeys(admitted_document_ids))
    cited = list(dict.fromkeys(cited_document_ids))
    budget = trace.get("budget", {})
    tool_steps = [
        step
        for step in trace.get("steps", [])
        if step.get("tool") in {"search", "find", "open"}
    ]
    security_rows = [
        step.get("retrieved_content_security", {}) for step in tool_steps
    ]
    cited_gold = gold.intersection(cited)
    return MultiDocCandidateCase(
        question_id_sha256=question_id_sha256,
        arm=arm,
        gold_document_count=len(gold),
        retrieved_document_ids=retrieved,
        admitted_document_ids=admitted,
        cited_document_ids=cited,
        retrieval_recall=len(gold.intersection(retrieved)) / len(gold),
        retrieval_complete=float(gold <= set(retrieved)),
        citation_precision=(len(cited_gold) / len(cited) if cited else None),
        citation_recall=len(cited_gold) / len(gold),
        citation_complete=float(gold <= set(cited)),
        response_mode=response_mode,
        selected_source_count=len(cited),
        query_variant_count=query_variant_count,
        embedding_calls=embedding_calls,
        search_calls=int(budget.get("search_calls", 0)),
        find_calls=int(budget.get("find_calls", 0)),
        open_calls=int(budget.get("open_calls", 0)),
        tool_errors=sum(
            bool(step.get("error_code")) or step.get("status") == "error"
            for step in tool_steps
        ),
        budget_exhausted=trace.get("stop_reason") == "budget_exhausted",
        guard_quarantined_count=sum(
            int(row.get("quarantined_count", 0)) for row in security_rows
        ),
        security_filtered=(
            response_mode == "security_filtered"
            or any(row.get("stop_reason") == "evidence_filtered" for row in security_rows)
        ),
        retrieval_compute_ms=retrieval_compute_ms,
        mechanism_ms=mechanism_ms,
        latency_ms=retrieval_compute_ms + mechanism_ms,
    )


def summarize_candidate_arm(
    cases: Sequence[MultiDocCandidateCase],
    *,
    arm: CandidateArm,
) -> MultiDocCandidateSummary:
    if not cases:
        raise ValueError("cannot summarize an empty arm")
    if any(item.arm != arm for item in cases):
        raise ValueError("arm summary received mixed arm labels")
    precisions = [
        item.citation_precision
        for item in cases
        if item.citation_precision is not None
    ]
    latencies = sorted(item.latency_ms for item in cases)
    return MultiDocCandidateSummary(
        arm=arm,
        case_count=len(cases),
        retrieval_recall=_mean(item.retrieval_recall for item in cases),
        retrieval_completeness=_mean(
            item.retrieval_complete for item in cases
        ),
        citation_precision=_mean(precisions) if precisions else None,
        citation_recall=_mean(item.citation_recall for item in cases),
        citation_completeness=_mean(
            item.citation_complete for item in cases
        ),
        answered_count=sum(item.response_mode == "answered" for item in cases),
        partial_count=sum(item.response_mode == "partial" for item in cases),
        source_free_count=sum(not item.cited_document_ids for item in cases),
        selected_sources_mean=_mean(
            item.selected_source_count for item in cases
        ),
        query_variants_mean=_mean(
            item.query_variant_count for item in cases
        ),
        embedding_calls_mean=_mean(item.embedding_calls for item in cases),
        search_calls_mean=_mean(item.search_calls for item in cases),
        find_calls_mean=_mean(item.find_calls for item in cases),
        open_calls_mean=_mean(item.open_calls for item in cases),
        tool_error_count=sum(item.tool_errors for item in cases),
        budget_exhaustion_count=sum(item.budget_exhausted for item in cases),
        guard_quarantined_count=sum(
            item.guard_quarantined_count for item in cases
        ),
        security_filtered_count=sum(item.security_filtered for item in cases),
        latency_ms_mean=_mean(item.latency_ms for item in cases),
        latency_ms_p50=_nearest_rank(latencies, 0.50),
        latency_ms_p95=_nearest_rank(latencies, 0.95),
    )


def evaluate_combined_gate(
    baseline_cases: Sequence[MultiDocCandidateCase],
    candidate_cases: Sequence[MultiDocCandidateCase],
    *,
    guard_enabled: bool,
    acl_enabled: bool,
    production_paths_unchanged: bool,
) -> MultiDocCandidateGate:
    baseline = summarize_candidate_arm(baseline_cases, arm="current")
    candidate = summarize_candidate_arm(candidate_cases, arm="combined")
    baseline_by_id = {item.question_id_sha256: item for item in baseline_cases}
    candidate_by_id = {item.question_id_sha256: item for item in candidate_cases}
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("paired arms must contain identical case IDs")
    fixes = sum(
        baseline_by_id[case_id].citation_complete == 0
        and candidate_by_id[case_id].citation_complete == 1
        for case_id in baseline_by_id
    )
    regressions = sum(
        baseline_by_id[case_id].citation_complete == 1
        and candidate_by_id[case_id].citation_complete == 0
        for case_id in baseline_by_id
    )
    precision_delta = (
        None
        if baseline.citation_precision is None
        or candidate.citation_precision is None
        else 100 * (candidate.citation_precision - baseline.citation_precision)
    )
    latency_ratio = (
        candidate.latency_ms_p95 / baseline.latency_ms_p95
        if baseline.latency_ms_p95 > 0
        else 0.0
    )
    completeness_delta = 100 * (
        candidate.citation_completeness - baseline.citation_completeness
    )
    recall_delta = 100 * (
        candidate.citation_recall - baseline.citation_recall
    )
    checks = {
        "citation_completeness_gain_at_least_15pp": completeness_delta >= 15,
        "citation_recall_gain_at_least_15pp": recall_delta >= 15,
        "citation_precision_drop_no_more_than_10pp": (
            precision_delta is not None and precision_delta >= -10
        ),
        "at_least_3_paired_fixes": fixes >= 3,
        "zero_paired_regressions": regressions == 0,
        "p95_latency_no_more_than_2x": latency_ratio <= 2.0,
        "mean_selected_sources_no_more_than_3": (
            candidate.selected_sources_mean <= 3
        ),
        "tool_error_count_zero": candidate.tool_error_count == 0,
        "budget_exhaustion_count_zero": candidate.budget_exhaustion_count == 0,
        "retrieved_content_guard_enabled": guard_enabled,
        "acl_boundary_enabled": acl_enabled,
        "production_paths_unchanged": production_paths_unchanged,
    }
    return MultiDocCandidateGate(
        citation_completeness_delta_pp=completeness_delta,
        citation_recall_delta_pp=recall_delta,
        citation_precision_delta_pp=precision_delta,
        p95_latency_ratio=latency_ratio,
        paired_fix_count=fixes,
        paired_regression_count=regressions,
        checks=checks,
        decision=(
            "DEVELOPMENT_CANDIDATE_HOLD_FOR_FIXED_VALIDATION"
            if all(checks.values())
            else "DEVELOPMENT_CANDIDATE_REJECTED"
        ),
    )


def derive_failure_analysis(
    baseline_cases: Sequence[MultiDocCandidateCase],
    candidate_cases: Sequence[MultiDocCandidateCase],
    *,
    gold_documents_by_question_id_sha256: dict[str, Sequence[str]],
) -> MultiDocCandidateFailureAnalysis:
    baseline_by_id = {item.question_id_sha256: item for item in baseline_cases}
    candidate_by_id = {item.question_id_sha256: item for item in candidate_cases}
    case_ids = set(baseline_by_id)
    if case_ids != set(candidate_by_id) or case_ids != set(
        gold_documents_by_question_id_sha256
    ):
        raise ValueError("failure analysis requires identical paired and gold IDs")

    acquisition_incomplete = 0
    all_gold_admitted = 0
    admission_loss = 0
    selection_loss = 0
    cited_gold = 0
    cited_noise = 0
    for case_id in case_ids:
        item = candidate_by_id[case_id]
        gold = set(gold_documents_by_question_id_sha256[case_id])
        retrieved = set(item.retrieved_document_ids)
        admitted = set(item.admitted_document_ids)
        cited = set(item.cited_document_ids)
        if len(gold) < 2:
            raise ValueError("failure analysis gold must be multi-document")
        if not gold.issubset(retrieved):
            acquisition_incomplete += 1
        if gold.issubset(admitted):
            all_gold_admitted += 1
            if not gold.issubset(cited):
                selection_loss += 1
        elif gold.issubset(retrieved):
            admission_loss += 1
        cited_gold += len(gold.intersection(cited))
        cited_noise += len(cited - gold)

    return MultiDocCandidateFailureAnalysis(
        case_count=len(case_ids),
        decomposed_case_count=sum(
            item.query_variant_count > 1 for item in candidate_cases
        ),
        top5_order_changed_case_count=sum(
            baseline_by_id[case_id].retrieved_document_ids
            != candidate_by_id[case_id].retrieved_document_ids
            for case_id in case_ids
        ),
        retrieval_recall_improved_case_count=sum(
            candidate_by_id[case_id].retrieval_recall
            > baseline_by_id[case_id].retrieval_recall
            for case_id in case_ids
        ),
        retrieval_recall_regressed_case_count=sum(
            candidate_by_id[case_id].retrieval_recall
            < baseline_by_id[case_id].retrieval_recall
            for case_id in case_ids
        ),
        acquisition_incomplete_case_count=acquisition_incomplete,
        all_gold_admitted_case_count=all_gold_admitted,
        admission_loss_after_complete_retrieval_count=admission_loss,
        selection_incomplete_after_complete_admission_count=selection_loss,
        citation_recall_improved_case_count=sum(
            candidate_by_id[case_id].citation_recall
            > baseline_by_id[case_id].citation_recall
            for case_id in case_ids
        ),
        citation_recall_regressed_case_count=sum(
            candidate_by_id[case_id].citation_recall
            < baseline_by_id[case_id].citation_recall
            for case_id in case_ids
        ),
        multi_source_citation_case_count=sum(
            item.selected_source_count > 1 for item in candidate_cases
        ),
        cited_gold_document_count=cited_gold,
        cited_noise_document_count=cited_noise,
        guard_quarantine_case_count=sum(
            item.guard_quarantined_count > 0 for item in candidate_cases
        ),
    )


def _document_ids_for_aspects(
    state: ControllerState,
    aspects: Sequence[str],
) -> list[str]:
    return list(
        dict.fromkeys(
            item.hit.doc_id
            for aspect in aspects
            for item in state.evidence_by_aspect.get(aspect, [])
        )
    )


def _first_document_per_aspect(
    state: ControllerState,
    aspects: Sequence[str],
) -> list[str]:
    return list(
        dict.fromkeys(
            items[0].hit.doc_id
            for aspect in aspects
            if (items := state.evidence_by_aspect.get(aspect, []))
        )
    )


def _mean(values) -> float:
    rows = list(values)
    return sum(rows) / len(rows)


def _nearest_rank(values: Sequence[float], fraction: float) -> float:
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


__all__ = [
    "CandidateArm",
    "MultiDocCandidateCase",
    "MultiDocCandidateFailureAnalysis",
    "MultiDocCandidateGate",
    "MultiDocCandidateSummary",
    "SelectiveExtractiveResponseBuilder",
    "decompose_query",
    "derive_failure_analysis",
    "evaluate_combined_gate",
    "fuse_query_rankings",
    "score_candidate_case",
    "select_preferred_admitted_document_ids",
    "summarize_candidate_arm",
]
