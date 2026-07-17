from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.corpus.schemas import EvalCase
from app.domain.agent import AgentBudget
from app.domain.evidence import AnswerResponse
from app.evaluation.contracts import FailureSignal, LayerResult


_BUDGET_KEYS = {
    "search_calls",
    "find_calls",
    "open_calls",
    "steps",
    "context_chars",
}
_STEP_KEYS = {
    "sequence",
    "tool",
    "status",
    "latency_ms",
    "visible_count",
    "context_chars_added",
    "error_code",
    "budget",
}
_INTENTS_BY_TASK = {
    "comparison": {"comparison"},
    "completeness": {"completeness"},
    # no_answer is a post-retrieval label; the input can still require a
    # factual, procedural, or completeness-oriented evidence search.
    "no_answer": {"fact", "process", "completeness", "no_answer"},
    "fact_lookup": {"fact", "process"},
    "version_conflict": {"fact", "process"},
    "permission": {"fact", "process", "completeness"},
}
_STOP_REASON_BY_MODE = {
    "answered": "completed",
    "partial": "partial_evidence",
    "permission": "permission",
    "not_found": "not_found",
    "unsafe": "unsafe",
    "budget": "budget_exhausted",
    "system": "system_error",
}


@dataclass(frozen=True)
class AgentEvaluation:
    layer: LayerResult
    tool_sequence: list[str]
    tool_calls: int
    context_chars: int


def evaluate_agent_case(
    case: EvalCase,
    response: AnswerResponse,
    budget: AgentBudget,
    *,
    runtime_mode: Literal["deterministic", "live"] = "deterministic",
) -> AgentEvaluation:
    trace = response.trace if isinstance(response.trace, dict) else {}
    complete = trace_is_complete(trace)
    steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
    tool_sequence = [
        str(step.get("tool"))
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("tool"), str)
    ]
    actual_tools = [
        tool for tool in tool_sequence if tool in {"search", "find", "open"}
    ]
    search_calls = actual_tools.count("search")
    open_calls = actual_tools.count("open")
    intent = trace.get("intent") if isinstance(trace.get("intent"), str) else ""
    intent_correct = intent in _INTENTS_BY_TASK.get(case.task_type, set())
    tool_choice_correct, tool_failure = _tool_choice(case, search_calls, open_calls)
    decomposition_correct = not (
        case.task_type == "comparison"
        and (
            search_calls < 2
            or not isinstance(trace.get("required_aspect_count"), int)
            or trace["required_aspect_count"] < 2
        )
    )
    retry_rewrite_correct = _retry_rewrite_correct(
        case.task_type,
        search_calls=search_calls,
        open_calls=open_calls,
    )
    budget_values = trace.get("budget") if isinstance(trace.get("budget"), dict) else {}
    budget_compliant = _budget_compliant(
        budget_values,
        budget,
        actual_tool_calls=len(actual_tools),
        search_calls=search_calls,
        find_calls=actual_tools.count("find"),
        open_calls=open_calls,
    )
    expected_stop = _STOP_REASON_BY_MODE.get(response.mode)
    stop_reason_correct = trace.get("stop_reason") == expected_stop
    final_outcome_correct = response.mode == case.answer_mode
    exact_trajectory = tool_sequence == _expected_trajectory(case, response.mode)

    failures: list[FailureSignal] = []
    if not complete:
        failures.append(
            FailureSignal(
                stage="system_runtime",
                code="trace_incomplete",
                message="The aggregate Agent trace was missing or internally inconsistent.",
            )
        )
    if not intent_correct:
        failures.append(
            FailureSignal(
                stage="query_analysis",
                code="intent_mismatch",
                message="The analyzed intent was not valid for the evaluation task type.",
            )
        )
    if not tool_choice_correct and tool_failure is not None:
        failures.append(tool_failure)
    if not decomposition_correct:
        failures.append(
            FailureSignal(
                stage="decomposition_rewrite",
                code="comparison_decomposition_missing",
                message="Comparison did not execute independent bounded aspect searches.",
            )
        )
    if not budget_compliant:
        failures.append(
            FailureSignal(
                stage="system_runtime",
                code="agent_budget_violation",
                message="Agent counters exceeded or contradicted the configured budget.",
            )
        )
    if not stop_reason_correct:
        failures.append(
            FailureSignal(
                stage="evidence_assessment",
                code="stop_reason_mismatch",
                message="The stop reason was incompatible with the final answer mode.",
            )
        )
    if not final_outcome_correct:
        failures.append(
            FailureSignal(
                stage="evidence_assessment",
                code="final_outcome_mismatch",
                message="The final Agent outcome did not match the evaluation label.",
            )
        )

    metrics = {
        "intent_correct": intent_correct,
        "tool_choice_correct": tool_choice_correct,
        "decomposition_rewrite_correct": decomposition_correct,
        "retry_rewrite_decision_correct": retry_rewrite_correct,
        "budget_compliant": budget_compliant,
        "stop_reason_correct": stop_reason_correct,
        "trace_complete": complete,
        "final_outcome_correct": final_outcome_correct,
        "exact_trajectory_contract": exact_trajectory,
        "search_calls": search_calls,
        "find_calls": actual_tools.count("find"),
        "open_calls": open_calls,
        "tool_calls": len(actual_tools),
        "context_chars": _nonnegative_int(budget_values.get("context_chars")),
        "runtime_is_live": runtime_mode == "live",
    }
    return AgentEvaluation(
        layer=LayerResult(
            layer="agent",
            applicable=True,
            passed=not failures,
            metrics=metrics,
            failures=failures,
        ),
        tool_sequence=tool_sequence,
        tool_calls=len(actual_tools),
        context_chars=_nonnegative_int(budget_values.get("context_chars")),
    )


def trace_is_complete(trace: dict[str, Any]) -> bool:
    required = {
        "intent",
        "analysis_source",
        "required_aspect_count",
        "steps",
        "stop_reason",
        "budget",
    }
    if not required.issubset(trace):
        return False
    if not isinstance(trace["intent"], str) or not trace["intent"]:
        return False
    if not isinstance(trace["analysis_source"], str):
        return False
    if not isinstance(trace["required_aspect_count"], int):
        return False
    budget = trace["budget"]
    if not _valid_budget_dict(budget):
        return False
    steps = trace["steps"]
    if not isinstance(steps, list) or not steps:
        return False
    for expected_sequence, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or not _STEP_KEYS.issubset(step):
            return False
        if step["sequence"] != expected_sequence:
            return False
        if not isinstance(step["tool"], str) or not isinstance(step["status"], str):
            return False
        if not _valid_budget_dict(step["budget"]):
            return False
    if steps[-1]["tool"] not in {"answer", "stop", "refuse"}:
        return False
    if steps[-1]["status"] != "terminal":
        return False
    if any(step["tool"] in {"answer", "stop", "refuse"} for step in steps[:-1]):
        return False
    return True


def _valid_budget_dict(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and _BUDGET_KEYS.issubset(value)
        and all(isinstance(value[key], int) and value[key] >= 0 for key in _BUDGET_KEYS)
    )


def _budget_compliant(
    values: dict[str, Any],
    budget: AgentBudget,
    *,
    actual_tool_calls: int,
    search_calls: int,
    find_calls: int,
    open_calls: int,
) -> bool:
    if not _valid_budget_dict(values):
        return False
    return bool(
        values["search_calls"] == search_calls <= budget.max_search_calls
        and values["find_calls"] == find_calls <= budget.max_find_calls
        and values["open_calls"] == open_calls <= budget.max_open_calls
        and values["steps"] == actual_tool_calls <= budget.max_steps
        and values["context_chars"] <= budget.max_context_chars
    )


def _tool_choice(
    case: EvalCase,
    search_calls: int,
    open_calls: int,
) -> tuple[bool, FailureSignal | None]:
    if search_calls < 1:
        return False, FailureSignal(
            stage="decomposition_rewrite",
            code="required_search_missing",
            message="A safe knowledge task completed without a bounded search.",
        )
    if case.task_type == "completeness" and open_calls < 1:
        return False, FailureSignal(
            stage="decomposition_rewrite",
            code="completeness_open_missing",
            message="Completeness evaluation required an authorized document open.",
        )
    return True, None


def _retry_rewrite_correct(
    task_type: str,
    *,
    search_calls: int,
    open_calls: int,
) -> bool:
    if task_type == "comparison":
        return search_calls >= 2
    if task_type == "completeness":
        return search_calls >= 1 and open_calls >= 1
    return search_calls >= 1


def _expected_trajectory(case: EvalCase, actual_mode: str) -> list[str]:
    terminal = "answer" if actual_mode in {"answered", "partial"} else "stop"
    if actual_mode == "unsafe":
        return ["refuse"]
    if case.task_type == "comparison":
        return ["search", "search", terminal]
    if case.task_type == "completeness":
        return ["search", "open", terminal]
    return ["search", terminal]


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


__all__ = ["AgentEvaluation", "evaluate_agent_case", "trace_is_complete"]
