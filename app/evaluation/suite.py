from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import MutableMapping, Sequence
from typing import Any, Literal

from app.corpus.schemas import EvalCase
from app.domain.evidence import AnswerResponse
from app.evaluation.agent import AgentEvaluation, evaluate_agent_case
from app.evaluation.answer import evaluate_answer_case
from app.evaluation.attribution import attribute_failures
from app.evaluation.contracts import (
    EvaluationCaseResult,
    EvaluationRunResult,
    FailureSignal,
    LayerResult,
)
from app.evaluation.metrics import rate_metric, unique_ranked_doc_ids
from app.evaluation.retrieval import eval_user_context, evaluate_retrieval_case
from app.evaluation.security import (
    evaluate_case_security,
    evaluate_injection_probes,
)


EvaluationSuite = Literal["retrieval", "answer", "agent", "security", "all"]


def evaluate_suite(
    cases: Sequence[EvalCase],
    runtime,
    *,
    run_id: str,
    suite: EvaluationSuite,
    split: Literal["dev", "test", "regression"],
    top_k: int = 5,
    candidate_k: int = 20,
    bootstrap_iterations: int = 0,
    bootstrap_seed: int = 20260716,
    response_sink: MutableMapping[str, str] | None = None,
) -> EvaluationRunResult:
    if suite not in {"retrieval", "answer", "agent", "security", "all"}:
        raise ValueError(f"unknown evaluation suite: {suite}")
    details = [
        _evaluate_case(
            case,
            runtime,
            suite=suite,
            top_k=top_k,
            candidate_k=candidate_k,
            response_sink=response_sink,
        )
        for case in cases
    ]
    probe_results: list[dict[str, Any]] = []
    probe_metrics: dict[str, Any] | None = None
    if suite in {"security", "all"} and cases:
        probe_user = eval_user_context(cases[0])
        probes = evaluate_injection_probes(
            lambda prompt: runtime.runner.run(prompt, probe_user, top_k),
            runtime.budget,
        )
        probe_results = probes.results
        probe_metrics = {
            **probes.layer.metrics,
            "passed": probes.layer.passed,
            "failure_count": len(probes.layer.failures),
        }

    summary = _summarize(
        details,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    if probe_metrics is not None:
        summary["security_probes"] = probe_metrics
    summary["failed_case_count"] = sum(not detail.passed for detail in details)
    summary["primary_failure_counts"] = _primary_failure_counts(details)
    return EvaluationRunResult(
        run_id=run_id,
        suite=suite,
        split=split,
        mode=runtime.mode,
        case_count=len(details),
        summary=summary,
        metrics_by_category=_category_rows(details, cases),
        details=details,
        security_probes=probe_results,
        config={
            "top_k": top_k,
            "candidate_k": candidate_k,
            "bootstrap_iterations": bootstrap_iterations,
            "bootstrap_seed": bootstrap_seed,
            "runtime_variant": runtime.variant,
        },
    )


def _evaluate_case(
    case: EvalCase,
    runtime,
    *,
    suite: EvaluationSuite,
    top_k: int,
    candidate_k: int,
    response_sink: MutableMapping[str, str] | None,
) -> EvaluationCaseResult:
    started = time.perf_counter()
    model_calls_before = runtime.counters.model_calls
    layers: list[LayerResult] = []
    retrieval_evaluation = None
    visible_doc_ids: list[str] = []
    if suite in {"retrieval", "security", "all"}:
        try:
            retrieval_evaluation = evaluate_retrieval_case(
                case,
                runtime.pipeline,
                top_k=top_k,
                candidate_k=candidate_k,
            )
            visible_doc_ids = retrieval_evaluation.observation.ranked_doc_ids
            if suite in {"retrieval", "all"}:
                layers.append(retrieval_evaluation.layer)
        except Exception:
            if suite in {"retrieval", "all"}:
                layers.append(_runtime_failure_layer("retrieval"))

    response: AnswerResponse | None = None
    agent_evaluation: AgentEvaluation | None = None
    if suite in {"answer", "agent", "security", "all"}:
        try:
            response = runtime.runner.run(
                case.question,
                eval_user_context(case),
                top_k,
            )
        except Exception:
            response = _system_response()
        if response_sink is not None:
            response_sink[case.case_id] = response.answer

        if suite in {"answer", "all"}:
            layers.append(
                evaluate_answer_case(
                    case,
                    response,
                    runtime.snapshot.all_chunks_by_id,
                ).layer
            )
        if suite in {"agent", "all"}:
            agent_evaluation = evaluate_agent_case(
                case,
                response,
                runtime.budget,
                runtime_mode=runtime.mode,
            )
            layers.append(agent_evaluation.layer)
        if suite in {"security", "all"}:
            security = evaluate_case_security(
                case,
                response,
                visible_doc_ids=visible_doc_ids,
                budget=runtime.budget,
            )
            layers.append(security.layer)

    if not layers:
        raise ValueError("evaluation suite produced no layer results")
    signals = [failure for layer in layers for failure in layer.failures]
    primary, secondary = attribute_failures(signals)
    source_doc_ids = (
        [source.doc_id for source in response.sources] if response is not None else []
    )
    public_visible = [
        doc_id
        for doc_id in unique_ranked_doc_ids([*visible_doc_ids, *source_doc_ids])
        if doc_id not in set(case.forbidden_doc_ids)
    ]
    tool_calls, context_chars = _execution_cost(response, agent_evaluation)
    return EvaluationCaseResult(
        case_id=case.case_id,
        task_type=case.task_type,
        expected_mode=case.answer_mode,
        actual_mode=response.mode if response is not None else "not_evaluated",
        passed=all(layer.passed for layer in layers if layer.applicable),
        visible_doc_ids=public_visible,
        layers=layers,
        primary_failure=primary,
        secondary_failures=secondary,
        latency_ms=(time.perf_counter() - started) * 1000,
        model_calls=max(0, runtime.counters.model_calls - model_calls_before),
        tool_calls=tool_calls,
        context_chars=context_chars,
    )


def _runtime_failure_layer(layer: str) -> LayerResult:
    return LayerResult(
        layer=layer,
        applicable=True,
        passed=False,
        metrics={},
        failures=[
            FailureSignal(
                stage="system_runtime",
                code=f"{layer}_runtime_exception",
                message=f"The {layer} evaluator encountered a runtime exception.",
            )
        ],
    )


def _system_response() -> AnswerResponse:
    budget = {
        "search_calls": 0,
        "find_calls": 0,
        "open_calls": 0,
        "steps": 0,
        "context_chars": 0,
    }
    return AnswerResponse(
        mode="system",
        answer="The evaluation runtime failed before producing an answer.",
        stop_reason="system_error",
        trace={
            "intent": "unknown",
            "analysis_source": "rules",
            "required_aspect_count": 0,
            "steps": [
                {
                    "sequence": 1,
                    "tool": "stop",
                    "status": "terminal",
                    "latency_ms": 0.0,
                    "visible_count": 0,
                    "context_chars_added": 0,
                    "error_code": "system_error",
                    "budget": budget,
                }
            ],
            "stop_reason": "system_error",
            "budget": budget,
        },
    )


def _execution_cost(
    response: AnswerResponse | None,
    agent_evaluation: AgentEvaluation | None,
) -> tuple[int, int]:
    if agent_evaluation is not None:
        return agent_evaluation.tool_calls, agent_evaluation.context_chars
    if response is None or not isinstance(response.trace, dict):
        return 0, 0
    budget = response.trace.get("budget")
    if not isinstance(budget, dict):
        return 0, 0
    tool_calls = sum(
        value if isinstance(value, int) and value >= 0 else 0
        for key, value in budget.items()
        if key in {"search_calls", "find_calls", "open_calls"}
    )
    context = budget.get("context_chars")
    return tool_calls, context if isinstance(context, int) and context >= 0 else 0


def _summarize(
    details: Sequence[EvaluationCaseResult],
    *,
    bootstrap_iterations: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    overall = rate_metric(
        [detail.passed for detail in details],
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )
    by_layer: dict[str, list[LayerResult]] = defaultdict(list)
    for detail in details:
        for layer in detail.layers:
            if layer.applicable:
                by_layer[layer.layer].append(layer)
    layer_summary: dict[str, Any] = {}
    for layer_name, layers in sorted(by_layer.items()):
        metrics: dict[str, list[int | float | bool]] = defaultdict(list)
        for layer in layers:
            for name, value in layer.metrics.items():
                if value is not None and isinstance(value, (int, float, bool)):
                    metrics[name].append(value)
        metric_summary: dict[str, Any] = {}
        for name, values in sorted(metrics.items()):
            if all(isinstance(value, bool) for value in values):
                metric_summary[name] = rate_metric(values).model_dump(mode="json")
            else:
                numeric = [float(value) for value in values]
                metric_summary[name] = {
                    "n": len(numeric),
                    "mean": sum(numeric) / len(numeric),
                    "sum": sum(numeric),
                }
        layer_summary[layer_name] = {
            "pass_rate": rate_metric(
                [layer.passed for layer in layers],
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=bootstrap_seed,
            ).model_dump(mode="json"),
            "metrics": metric_summary,
        }
    return {
        "overall_case_pass": overall.model_dump(mode="json"),
        "layers": layer_summary,
    }


def _category_rows(
    details: Sequence[EvaluationCaseResult],
    cases: Sequence[EvalCase],
) -> list[dict[str, Any]]:
    by_case = {detail.case_id: detail for detail in details}
    groups: dict[tuple[str, str], list[EvaluationCaseResult]] = defaultdict(list)
    for case in cases:
        detail = by_case[case.case_id]
        groups[("task_type", case.task_type)].append(detail)
        for tag in case.tags:
            groups[("tag", tag)].append(detail)
    rows: list[dict[str, Any]] = []
    for (category_type, category), group in sorted(groups.items()):
        layer_names = sorted({layer.layer for detail in group for layer in detail.layers})
        row: dict[str, Any] = {
            "category_type": category_type,
            "category": category,
            "count": len(group),
            "case_pass_rate": sum(detail.passed for detail in group) / len(group),
        }
        for layer_name in layer_names:
            layer_values = [
                layer.passed
                for detail in group
                for layer in detail.layers
                if layer.layer == layer_name and layer.applicable
            ]
            row[f"{layer_name}_pass_rate"] = (
                sum(layer_values) / len(layer_values) if layer_values else None
            )
        rows.append(row)
    return rows


def _primary_failure_counts(
    details: Sequence[EvaluationCaseResult],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for detail in details:
        if detail.primary_failure is not None:
            counts[detail.primary_failure] += 1
    return dict(sorted(counts.items()))


__all__ = ["EvaluationSuite", "evaluate_suite"]
