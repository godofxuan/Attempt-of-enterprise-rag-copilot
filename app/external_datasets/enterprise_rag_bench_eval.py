from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.external_datasets.enterprise_rag_bench import EnterpriseRAGBenchQuestion


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnterpriseRAGBenchRetrievalCase(_StrictModel):
    question_id: str = Field(min_length=1)
    question_type: str = Field(min_length=1)
    gold_document_count: int = Field(ge=1)
    ranked_source_ids: list[str] = Field(max_length=5)
    hit_at_1: float = Field(ge=0, le=1)
    recall_at_1: float = Field(ge=0, le=1)
    recall_at_3: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    reciprocal_rank_at_5: float = Field(ge=0, le=1)
    ndcg_at_5: float = Field(ge=0, le=1)
    complete_at_5: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float = Field(ge=0)


class EnterpriseRAGBenchRetrievalSummary(_StrictModel):
    schema_version: str = "enterprise_rag_bench_retrieval_summary_v1"
    group: str = Field(min_length=1)
    case_count: int = Field(ge=1)
    multi_document_case_count: int = Field(ge=0)
    hit_at_1: float = Field(ge=0, le=1)
    macro_document_recall_at_1: float = Field(ge=0, le=1)
    macro_document_recall_at_3: float = Field(ge=0, le=1)
    macro_document_recall_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    ndcg_at_5: float = Field(ge=0, le=1)
    multi_document_completeness_at_5: float | None = Field(
        default=None, ge=0, le=1
    )
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)


def score_enterprise_rag_bench_ranking(
    question: EnterpriseRAGBenchQuestion,
    *,
    ranked_source_ids: Sequence[str],
    latency_ms: float,
) -> EnterpriseRAGBenchRetrievalCase:
    gold = set(question.unique_expected_doc_ids)
    if not gold:
        raise ValueError("retrieval scoring requires document gold")
    top = list(dict.fromkeys(ranked_source_ids))[:5]
    recalls = {
        cutoff: len(gold.intersection(top[:cutoff])) / len(gold)
        for cutoff in (1, 3, 5)
    }
    first = next(
        (rank for rank, item in enumerate(top, start=1) if item in gold), None
    )
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(top, start=1)
        if item in gold
    )
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(5, len(gold)) + 1)
    )
    return EnterpriseRAGBenchRetrievalCase(
        question_id=question.question_id,
        question_type=question.question_type,
        gold_document_count=len(gold),
        ranked_source_ids=top,
        hit_at_1=float(bool(top and top[0] in gold)),
        recall_at_1=recalls[1],
        recall_at_3=recalls[3],
        recall_at_5=recalls[5],
        reciprocal_rank_at_5=0.0 if first is None else 1.0 / first,
        ndcg_at_5=dcg / ideal,
        complete_at_5=float(gold <= set(top)) if len(gold) > 1 else None,
        latency_ms=latency_ms,
    )


def summarize_enterprise_rag_bench_retrieval(
    scores: Sequence[EnterpriseRAGBenchRetrievalCase],
    *,
    group: str,
) -> EnterpriseRAGBenchRetrievalSummary:
    if not scores:
        raise ValueError("cannot summarize an empty retrieval cohort")
    multi = [item.complete_at_5 for item in scores if item.complete_at_5 is not None]
    latency = sorted(item.latency_ms for item in scores)
    return EnterpriseRAGBenchRetrievalSummary(
        group=group,
        case_count=len(scores),
        multi_document_case_count=len(multi),
        hit_at_1=_mean(item.hit_at_1 for item in scores),
        macro_document_recall_at_1=_mean(item.recall_at_1 for item in scores),
        macro_document_recall_at_3=_mean(item.recall_at_3 for item in scores),
        macro_document_recall_at_5=_mean(item.recall_at_5 for item in scores),
        mrr_at_5=_mean(item.reciprocal_rank_at_5 for item in scores),
        ndcg_at_5=_mean(item.ndcg_at_5 for item in scores),
        multi_document_completeness_at_5=(
            _mean(value for value in multi if value is not None) if multi else None
        ),
        latency_ms_mean=_mean(latency),
        latency_ms_p50=_nearest_rank(latency, 0.50),
        latency_ms_p95=_nearest_rank(latency, 0.95),
    )


def summarize_by_question_type(
    scores: Sequence[EnterpriseRAGBenchRetrievalCase],
) -> list[EnterpriseRAGBenchRetrievalSummary]:
    grouped: dict[str, list[EnterpriseRAGBenchRetrievalCase]] = defaultdict(list)
    for score in scores:
        grouped[score.question_type].append(score)
    return [
        summarize_enterprise_rag_bench_retrieval(grouped[name], group=name)
        for name in sorted(grouped)
    ]


def _mean(values) -> float:
    rows = list(values)
    if not rows:
        raise ValueError("mean requires at least one value")
    return sum(rows) / len(rows)


def _nearest_rank(values: Sequence[float], fraction: float) -> float:
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


__all__ = [
    "EnterpriseRAGBenchRetrievalCase",
    "EnterpriseRAGBenchRetrievalSummary",
    "score_enterprise_rag_bench_ranking",
    "summarize_by_question_type",
    "summarize_enterprise_rag_bench_retrieval",
]
