from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MultiDocArmCase(_StrictModel):
    question_id: str = Field(min_length=1)
    arm: str = Field(min_length=1)
    gold_source_count: int = Field(ge=2)
    retrieved_source_ids: list[str]
    accepted_source_ids: list[str]
    cited_source_ids: list[str]
    retrieval_recall: float = Field(ge=0, le=1)
    retrieval_complete: float = Field(ge=0, le=1)
    required_evidence_complete: float = Field(ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    citation_complete: float = Field(ge=0, le=1)
    search_calls: int = Field(ge=0)
    open_calls: int = Field(ge=0)
    find_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_errors: int = Field(ge=0)
    budget_exhausted: bool
    latency_ms: float = Field(ge=0)


class MultiDocArmSummary(_StrictModel):
    arm: str = Field(min_length=1)
    case_count: int = Field(ge=1)
    retrieval_recall: float = Field(ge=0, le=1)
    retrieval_completeness: float = Field(ge=0, le=1)
    required_evidence_completeness: float = Field(ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float = Field(ge=0, le=1)
    citation_completeness: float = Field(ge=0, le=1)
    search_calls_mean: float = Field(ge=0)
    open_calls_mean: float = Field(ge=0)
    find_calls_mean: float = Field(ge=0)
    tool_calls_mean: float = Field(ge=0)
    tool_error_count: int = Field(ge=0)
    budget_exhaustion_rate: float = Field(ge=0, le=1)
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    generation_model_calls: int = Field(ge=0)
    generation_tokens: int = Field(ge=0)


def score_arm_case(
    *,
    question_id: str,
    arm: str,
    gold_source_ids: Sequence[str],
    retrieved_source_ids: Sequence[str],
    accepted_source_ids: Sequence[str],
    cited_source_ids: Sequence[str],
    trace: dict,
    latency_ms: float,
) -> MultiDocArmCase:
    gold = set(gold_source_ids)
    if len(gold) < 2:
        raise ValueError("fast-track cases require at least two gold sources")
    retrieved = list(dict.fromkeys(retrieved_source_ids))
    accepted = list(dict.fromkeys(accepted_source_ids))
    cited = list(dict.fromkeys(cited_source_ids))
    budget = trace.get("budget", {})
    tool_steps = [
        step
        for step in trace.get("steps", [])
        if step.get("tool") in {"search", "open", "find"}
    ]
    tool_errors = sum(
        bool(step.get("error_code")) or step.get("status") == "error"
        for step in tool_steps
    )
    cited_gold = gold.intersection(cited)
    return MultiDocArmCase(
        question_id=question_id,
        arm=arm,
        gold_source_count=len(gold),
        retrieved_source_ids=retrieved,
        accepted_source_ids=accepted,
        cited_source_ids=cited,
        retrieval_recall=len(gold.intersection(retrieved)) / len(gold),
        retrieval_complete=float(gold <= set(retrieved)),
        required_evidence_complete=float(gold <= set(accepted)),
        citation_precision=(len(cited_gold) / len(cited) if cited else None),
        citation_recall=len(cited_gold) / len(gold),
        citation_complete=float(gold <= set(cited)),
        search_calls=int(budget.get("search_calls", 0)),
        open_calls=int(budget.get("open_calls", 0)),
        find_calls=int(budget.get("find_calls", 0)),
        tool_calls=len(tool_steps),
        tool_errors=tool_errors,
        budget_exhausted=trace.get("stop_reason") == "budget_exhausted",
        latency_ms=latency_ms,
    )


def summarize_arm(cases: Sequence[MultiDocArmCase], *, arm: str) -> MultiDocArmSummary:
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
    return MultiDocArmSummary(
        arm=arm,
        case_count=len(cases),
        retrieval_recall=_mean(item.retrieval_recall for item in cases),
        retrieval_completeness=_mean(
            item.retrieval_complete for item in cases
        ),
        required_evidence_completeness=_mean(
            item.required_evidence_complete for item in cases
        ),
        citation_precision=(
            _mean(value for value in precisions if value is not None)
            if precisions
            else None
        ),
        citation_recall=_mean(item.citation_recall for item in cases),
        citation_completeness=_mean(
            item.citation_complete for item in cases
        ),
        search_calls_mean=_mean(item.search_calls for item in cases),
        open_calls_mean=_mean(item.open_calls for item in cases),
        find_calls_mean=_mean(item.find_calls for item in cases),
        tool_calls_mean=_mean(item.tool_calls for item in cases),
        tool_error_count=sum(item.tool_errors for item in cases),
        budget_exhaustion_rate=_mean(
            float(item.budget_exhausted) for item in cases
        ),
        latency_ms_mean=_mean(item.latency_ms for item in cases),
        latency_ms_p50=_nearest_rank(latencies, 0.50),
        latency_ms_p95=_nearest_rank(latencies, 0.95),
        generation_model_calls=0,
        generation_tokens=0,
    )


def _mean(values) -> float:
    rows = list(values)
    return sum(rows) / len(rows)


def _nearest_rank(values: Sequence[float], fraction: float) -> float:
    return values[max(0, math.ceil(fraction * len(values)) - 1)]


__all__ = [
    "MultiDocArmCase",
    "MultiDocArmSummary",
    "score_arm_case",
    "summarize_arm",
]
