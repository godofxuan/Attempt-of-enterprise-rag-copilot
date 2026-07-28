from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Protocol

from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.corpus.schemas import EvalCase
from app.domain.queries import (
    QueryAnalysis,
    QueryFilters,
    SearchRequest,
    SearchResult,
    UserContext,
)
from app.evaluation.contracts import FailureSignal, LayerResult
from app.evaluation.metrics import document_metrics, unique_ranked_doc_ids
from app.security.access import AccessPolicy


RetrievalVariant = Literal[
    "production",
    "bm25",
    "dense",
    "hybrid_rrf",
    "hybrid_metadata_temporal",
    "hybrid_diversity_parent",
]


class SearchBackend(Protocol):
    def search(self, request: SearchRequest) -> SearchResult: ...


@dataclass(frozen=True)
class RetrievalObservation:
    request: SearchRequest
    result: SearchResult
    analysis: QueryAnalysis
    ranked_doc_ids: list[str]
    latency_ms: float
    context_chars: int


@dataclass(frozen=True)
class RetrievalEvaluation:
    observation: RetrievalObservation
    layer: LayerResult


def evaluate_retrieval_case(
    case: EvalCase,
    pipeline: SearchBackend,
    *,
    variant: RetrievalVariant = "production",
    top_k: int = 5,
    candidate_k: int = 20,
    analyzer: RuleFirstQueryAnalyzer | None = None,
    access_policy: AccessPolicy | None = None,
    include_parent: bool | None = None,
    max_chunks_per_doc: int | None = None,
) -> RetrievalEvaluation:
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")
    if candidate_k < top_k or candidate_k > 200:
        raise ValueError("candidate_k must be between top_k and 200")
    if max_chunks_per_doc is not None and not 1 <= max_chunks_per_doc <= 10:
        raise ValueError("max_chunks_per_doc must be between 1 and 10")
    user = eval_user_context(case)
    analysis = (analyzer or RuleFirstQueryAnalyzer()).analyze(case.question, user)
    request = _search_request(
        case,
        user,
        analysis,
        variant=variant,
        top_k=top_k,
        candidate_k=candidate_k,
        include_parent_override=include_parent,
        max_chunks_per_doc_override=max_chunks_per_doc,
    )
    started = time.perf_counter()
    result = pipeline.search(request)
    latency_ms = (time.perf_counter() - started) * 1000
    ranked_doc_ids = unique_ranked_doc_ids(hit.doc_id for hit in result.hits)
    context_chars = sum(len(hit.context_text) for hit in result.hits)
    observation = RetrievalObservation(
        request=request,
        result=result,
        analysis=analysis,
        ranked_doc_ids=ranked_doc_ids,
        latency_ms=latency_ms,
        context_chars=context_chars,
    )
    return RetrievalEvaluation(
        observation=observation,
        layer=_score_retrieval(
            case,
            observation,
            user=user,
            access_policy=access_policy or AccessPolicy(),
        ),
    )


def _search_request(
    case: EvalCase,
    user: UserContext,
    analysis: QueryAnalysis,
    *,
    variant: RetrievalVariant,
    top_k: int,
    candidate_k: int,
    include_parent_override: bool | None,
    max_chunks_per_doc_override: int | None,
) -> SearchRequest:
    if variant in {"production", "hybrid_diversity_parent"}:
        mode = "hybrid"
        filters = analysis.filters
        include_parent_default = True
        max_chunks_per_doc_default = 2
    elif variant == "hybrid_metadata_temporal":
        mode = "hybrid"
        filters = analysis.filters
        include_parent_default = False
        max_chunks_per_doc_default = min(10, top_k)
    else:
        mode = {
            "bm25": "bm25",
            "dense": "dense",
            "hybrid_rrf": "hybrid",
        }[variant]
        filters = QueryFilters(
            temporal_scope="all",
            authoritative_only=False,
        )
        include_parent_default = False
        max_chunks_per_doc_default = min(10, top_k)
    if include_parent_override is not None:
        active_include_parent = include_parent_override
    else:
        active_include_parent = include_parent_default
    if max_chunks_per_doc_override is not None:
        active_max_chunks_per_doc = max_chunks_per_doc_override
    else:
        active_max_chunks_per_doc = max_chunks_per_doc_default
    return SearchRequest(
        request_id=f"eval-{case.case_id}",
        query=case.question,
        purpose=f"evaluate {variant} retrieval",
        user=user,
        filters=filters,
        top_k=top_k,
        candidate_k=candidate_k,
        mode=mode,
        include_parent=active_include_parent,
        max_chunks_per_doc=active_max_chunks_per_doc,
    )


def _score_retrieval(
    case: EvalCase,
    observation: RetrievalObservation,
    *,
    user: UserContext,
    access_policy: AccessPolicy,
) -> LayerResult:
    metrics = document_metrics(
        observation.ranked_doc_ids,
        case.gold_doc_ids,
        cutoffs=(1, 3, 5),
    )
    forbidden = set(case.forbidden_doc_ids)
    leakage_count = sum(
        hit.doc_id in forbidden or not access_policy.evaluate(user, hit).allowed
        for hit in observation.result.hits
    )
    expected_authority = set(case.expected_authority_doc_ids)
    authority_accuracy = (
        None
        if not expected_authority
        else float(expected_authority.issubset(observation.ranked_doc_ids[:5]))
    )
    metrics.update(
        {
            "gold_document_count": len(case.gold_doc_ids),
            "visible_document_count": len(observation.ranked_doc_ids),
            "acl_leakage_count": leakage_count,
            "authority_accuracy": authority_accuracy,
            "latency_ms": observation.latency_ms,
            "context_chars": observation.context_chars,
        }
    )

    failures: list[FailureSignal] = []
    if observation.result.stop_reason == "timeout":
        failures.append(
            FailureSignal(
                stage="system_runtime",
                code="retrieval_timeout",
                message="Retrieval exceeded its configured timeout.",
            )
        )
    if leakage_count:
        failures.append(
            FailureSignal(
                stage="acl",
                code="unauthorized_document_exposure",
                message=(
                    "One or more unauthorized documents were exposed in public hits."
                ),
            )
        )
    if case.gold_doc_ids:
        recall = float(metrics["document_recall@5"] or 0.0)
        if recall == 0.0:
            failures.append(
                FailureSignal(
                    stage="retrieval",
                    code="gold_documents_missing",
                    message="No gold document was visible in the evaluated cutoff.",
                )
            )
        elif recall < 1.0:
            failures.append(
                FailureSignal(
                    stage="ranking",
                    code="incomplete_gold_coverage",
                    message="Only part of the required gold document set was in top-k.",
                )
            )
    if authority_accuracy == 0.0:
        failures.append(
            FailureSignal(
                stage="conflict_resolution",
                code="authority_document_missing",
                message="The expected authoritative document set was not fully recalled.",
            )
        )
    return LayerResult(
        layer="retrieval",
        applicable=True,
        passed=not failures,
        metrics=metrics,
        failures=failures,
    )


def eval_user_context(case: EvalCase) -> UserContext:
    context = case.user_context
    return UserContext(
        user_id=context.user_id,
        tenant_id=context.tenant,
        region=context.region,
        groups=context.groups,
    )


__all__ = [
    "RetrievalEvaluation",
    "RetrievalObservation",
    "RetrievalVariant",
    "eval_user_context",
    "evaluate_retrieval_case",
]
