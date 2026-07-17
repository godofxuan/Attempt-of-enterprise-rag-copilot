from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.corpus.schemas import EvalCase
from app.domain.evidence import AnswerResponse
from app.evaluation.contracts import AblationRow
from app.evaluation.metrics import unique_ranked_doc_ids
from app.evaluation.retrieval import eval_user_context, evaluate_retrieval_case


_RETRIEVAL_VARIANTS = (
    "bm25",
    "dense",
    "hybrid_rrf",
    "hybrid_metadata_temporal",
    "hybrid_diversity_parent",
)


@dataclass(frozen=True)
class AblationEvaluation:
    rows: list[AblationRow]
    failure_case_ids: dict[str, list[str]]
    answer_by_case: dict[str, str]
    actual_mode_by_case: dict[str, str] = field(default_factory=dict)


def run_ablation(
    cases: Sequence[EvalCase],
    runtime,
    *,
    top_k: int = 5,
    candidate_k: int = 20,
) -> AblationEvaluation:
    rows: list[AblationRow] = []
    failure_case_ids: dict[str, list[str]] = {}
    for variant in _RETRIEVAL_VARIANTS:
        row, failures = _retrieval_variant(
            cases,
            runtime,
            variant=variant,
            top_k=top_k,
            candidate_k=candidate_k,
        )
        rows.append(row)
        failure_case_ids[variant] = failures
    rows.append(
        AblationRow(
            variant="hybrid_optional_reranker",
            family="retrieval",
            status="not_run",
            reason="no_admitted_reranker",
            case_count=0,
            metrics={},
            latency_ms_avg=None,
            model_calls=0,
            tool_calls=0,
            context_chars=0,
        )
    )
    failure_case_ids["hybrid_optional_reranker"] = []

    fixed_row, fixed_failures = _fixed_rag(
        cases,
        runtime,
        top_k=top_k,
        candidate_k=candidate_k,
    )
    rows.append(fixed_row)
    failure_case_ids["fixed_rag"] = fixed_failures
    agent_row, agent_failures, answers, actual_modes = _bounded_agent(
        cases,
        runtime,
        top_k=top_k,
    )
    rows.append(agent_row)
    failure_case_ids["bounded_agentic_retrieval"] = agent_failures
    return AblationEvaluation(
        rows=rows,
        failure_case_ids=failure_case_ids,
        answer_by_case=answers,
        actual_mode_by_case=actual_modes,
    )


def _retrieval_variant(
    cases: Sequence[EvalCase],
    runtime,
    *,
    variant: str,
    top_k: int,
    candidate_k: int,
) -> tuple[AblationRow, list[str]]:
    calls_before = runtime.counters.model_calls
    started = time.perf_counter()
    evaluations = []
    try:
        for case in cases:
            evaluations.append(
                (
                    case,
                    evaluate_retrieval_case(
                        case,
                        runtime.pipeline,
                        variant=variant,
                        top_k=top_k,
                        candidate_k=candidate_k,
                    ),
                )
            )
    except Exception as exc:
        return (
            AblationRow(
                variant=variant,
                family="retrieval",
                status="failed",
                reason=f"runtime_error:{type(exc).__name__}",
                case_count=0,
                metrics={},
                latency_ms_avg=None,
                model_calls=max(0, runtime.counters.model_calls - calls_before),
                tool_calls=len(evaluations),
                context_chars=sum(
                    item.observation.context_chars for _, item in evaluations
                ),
            ),
            [case.case_id for case in cases],
        )
    metrics = _retrieval_metrics([item for _, item in evaluations])
    elapsed_ms = (time.perf_counter() - started) * 1000
    failures = [case.case_id for case, item in evaluations if not item.layer.passed]
    return (
        AblationRow(
            variant=variant,
            family="retrieval",
            status="completed",
            case_count=len(cases),
            metrics=metrics,
            latency_ms_avg=elapsed_ms / len(cases) if cases else 0.0,
            model_calls=max(0, runtime.counters.model_calls - calls_before),
            tool_calls=len(cases),
            context_chars=sum(
                item.observation.context_chars for _, item in evaluations
            ),
        ),
        failures,
    )


def _fixed_rag(
    cases: Sequence[EvalCase],
    runtime,
    *,
    top_k: int,
    candidate_k: int,
) -> tuple[AblationRow, list[str]]:
    calls_before = runtime.counters.model_calls
    started = time.perf_counter()
    outcomes: list[bool] = []
    recalls: list[float] = []
    full_recalls: list[float] = []
    failures: list[str] = []
    context_chars = 0
    for case in cases:
        evaluated = evaluate_retrieval_case(
            case,
            runtime.pipeline,
            variant="production",
            top_k=top_k,
            candidate_k=candidate_k,
        )
        result = evaluated.observation.result
        predicted = (
            "answered"
            if result.hits
            else "permission"
            if result.stop_reason == "no_visible_evidence"
            else "not_found"
        )
        outcome_ok = predicted == case.answer_mode
        outcomes.append(outcome_ok)
        if case.gold_doc_ids:
            recalls.append(float(evaluated.layer.metrics["document_recall@5"] or 0.0))
            full_recalls.append(
                float(evaluated.layer.metrics["full_document_recall@5"] or 0.0)
            )
        if not outcome_ok or not evaluated.layer.passed:
            failures.append(case.case_id)
        context_chars += evaluated.observation.context_chars
    elapsed_ms = (time.perf_counter() - started) * 1000
    return (
        AblationRow(
            variant="fixed_rag",
            family="workflow",
            status="completed",
            case_count=len(cases),
            metrics={
                "outcome_accuracy": _mean_bool(outcomes),
                "document_recall@5": _mean(recalls),
                "full_document_recall@5": _mean(full_recalls),
            },
            latency_ms_avg=elapsed_ms / len(cases) if cases else 0.0,
            model_calls=max(0, runtime.counters.model_calls - calls_before),
            tool_calls=len(cases),
            context_chars=context_chars,
        ),
        sorted(set(failures)),
    )


def _bounded_agent(
    cases: Sequence[EvalCase],
    runtime,
    *,
    top_k: int,
) -> tuple[AblationRow, list[str], dict[str, str], dict[str, str]]:
    calls_before = runtime.counters.model_calls
    started = time.perf_counter()
    outcomes: list[bool] = []
    recalls: list[float] = []
    full_recalls: list[float] = []
    failures: list[str] = []
    answers: dict[str, str] = {}
    actual_modes: dict[str, str] = {}
    tool_calls = 0
    context_chars = 0
    for case in cases:
        response: AnswerResponse = runtime.runner.run(
            case.question,
            eval_user_context(case),
            top_k,
        )
        answers[case.case_id] = response.answer
        actual_modes[case.case_id] = response.mode
        outcome_ok = response.mode == case.answer_mode
        outcomes.append(outcome_ok)
        source_docs = unique_ranked_doc_ids(source.doc_id for source in response.sources)
        if case.gold_doc_ids:
            gold = set(case.gold_doc_ids)
            recalled = len(gold.intersection(source_docs)) / len(gold)
            recalls.append(recalled)
            full_recalls.append(float(recalled == 1.0))
        else:
            recalled = 1.0
        if not outcome_ok or recalled < 1.0:
            failures.append(case.case_id)
        case_tools, case_context = _trace_cost(response.trace)
        tool_calls += case_tools
        context_chars += case_context
    elapsed_ms = (time.perf_counter() - started) * 1000
    return (
        AblationRow(
            variant="bounded_agentic_retrieval",
            family="workflow",
            status="completed",
            case_count=len(cases),
            metrics={
                "outcome_accuracy": _mean_bool(outcomes),
                "document_recall@5": _mean(recalls),
                "full_document_recall@5": _mean(full_recalls),
            },
            latency_ms_avg=elapsed_ms / len(cases) if cases else 0.0,
            model_calls=max(0, runtime.counters.model_calls - calls_before),
            tool_calls=tool_calls,
            context_chars=context_chars,
        ),
        sorted(set(failures)),
        answers,
        actual_modes,
    )


def _retrieval_metrics(evaluations: Sequence[Any]) -> dict[str, float | int]:
    metric_names = (
        "hit@5",
        "document_recall@5",
        "full_document_recall@5",
        "precision@5",
        "mrr",
        "ndcg@5",
        "authority_accuracy",
    )
    result: dict[str, float | int] = {}
    for name in metric_names:
        values = [
            float(item.layer.metrics[name])
            for item in evaluations
            if item.layer.metrics.get(name) is not None
        ]
        result[name] = _mean(values)
    result["case_pass_rate"] = _mean_bool(
        [item.layer.passed for item in evaluations]
    )
    result["acl_leakage_count"] = sum(
        int(item.layer.metrics["acl_leakage_count"]) for item in evaluations
    )
    return result


def _trace_cost(trace: Any) -> tuple[int, int]:
    if not isinstance(trace, dict) or not isinstance(trace.get("budget"), dict):
        return 0, 0
    budget = trace["budget"]
    tool_calls = sum(
        value if isinstance(value, int) and value >= 0 else 0
        for key, value in budget.items()
        if key in {"search_calls", "find_calls", "open_calls"}
    )
    context = budget.get("context_chars")
    return tool_calls, context if isinstance(context, int) and context >= 0 else 0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_bool(values: Sequence[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


__all__ = ["AblationEvaluation", "run_ablation"]
