from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent import AgentAction, BudgetState, ToolError, ToolErrorCode
from app.domain.queries import FindResult, OpenResult, SearchResult
from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    GuardedV2ToolExecution,
    SecurityCounters,
)
from app.retrieval.pipeline import RankedSearchPool
from app.security.retrieved_admission import (
    GuardedAdmissionOutcome,
    RetrievedContentAdmission,
)


class Navigator(Protocol):
    def search(self, request): ...

    def search_ranked(self, request): ...

    def find(self, request): ...

    def open(self, request): ...


ToolPayload = SearchResult | FindResult | OpenResult | ToolError
RawGuardInput = RankedSearchPool | FindResult | OpenResult | ToolError
ClockMs = Callable[[], float]


class V2ToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AgentAction
    result: ToolPayload
    budget_state: BudgetState
    status: Literal["ok", "error"]
    visible_count: int = Field(ge=0)
    context_chars_added: int = Field(ge=0)


class V2ToolRegistry:
    def __init__(
        self,
        navigator: Navigator,
        *,
        clock_ms: ClockMs | None = None,
        guard: object | None = None,
        admission: RetrievedContentAdmission | None = None,
    ) -> None:
        if guard is not None and admission is not None:
            raise ValueError("provide either Guard or admission, not both")
        self.navigator = navigator
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000)
        if admission is not None and not isinstance(
            admission,
            RetrievedContentAdmission,
        ):
            raise TypeError("admission must be RetrievedContentAdmission")
        self.admission = admission or RetrievedContentAdmission(guard=guard)

    def run(
        self,
        action: AgentAction,
        budget_state: BudgetState,
    ) -> GuardedV2ToolExecution:
        if not isinstance(action, AgentAction):
            raise TypeError("registry requires a typed AgentAction")
        if action.tool not in {"search", "find", "open"}:
            return _error_execution(
                action,
                budget_state,
                code="invalid_args",
                message="The requested tool is not available.",
            )
        started_at_ms = self.clock_ms()
        deadline_at_ms = _effective_deadline_ms(
            action,
            budget_state,
            started_at_ms=started_at_ms,
        )
        if started_at_ms >= deadline_at_ms:
            return _error_execution(
                action,
                budget_state,
                code="timeout",
                message="The tool call exceeded its deadline.",
                retryable=True,
            )

        budget_error = _budget_error(action, budget_state)
        if budget_error is not None:
            return _error_execution(
                action,
                budget_state,
                code="budget",
                message=budget_error,
            )

        consumed_state = _consume_call(action, budget_state)
        try:
            if action.tool == "search":
                raw_result = self.navigator.search_ranked(action.search_request)
            elif action.tool == "find":
                raw_result = self.navigator.find(action.find_request)
            else:
                raw_result = self.navigator.open(action.open_request)
        except Exception:
            if self.clock_ms() >= deadline_at_ms:
                return _error_execution(
                    action,
                    consumed_state,
                    code="timeout",
                    message="The tool call exceeded its deadline.",
                    retryable=True,
                )
            return _error_execution(
                action,
                consumed_state,
                code="system",
                message="The tool is temporarily unavailable.",
                retryable=True,
            )

        if self.clock_ms() >= deadline_at_ms:
            return _error_execution(
                action,
                consumed_state,
                code="timeout",
                message="The tool call exceeded its deadline.",
                retryable=True,
            )
        if not isinstance(
            raw_result,
            (RankedSearchPool, FindResult, OpenResult, ToolError),
        ):
            return _error_execution(
                action,
                consumed_state,
                code="system",
                message="The tool returned an invalid response.",
                retryable=True,
            )
        if isinstance(raw_result, ToolError):
            return _error_execution(
                action,
                consumed_state,
                code=raw_result.code,
                message=raw_result.safe_message,
                retryable=raw_result.retryable,
            )

        try:
            admission = _admit(self.admission, action, raw_result)
        except Exception:
            if self.clock_ms() >= deadline_at_ms:
                return _error_execution(
                    action,
                    consumed_state,
                    code="timeout",
                    message="The tool call exceeded its deadline.",
                    retryable=True,
                )
            return _error_execution(
                action,
                consumed_state,
                code="system",
                message="The retrieved-content safety boundary is unavailable.",
                retryable=True,
            )
        if not isinstance(admission, GuardedAdmissionOutcome):
            return _error_execution(
                action,
                consumed_state,
                code="system",
                message="The retrieved-content safety boundary returned an invalid response.",
                retryable=True,
            )
        if self.clock_ms() >= deadline_at_ms:
            return _error_execution(
                action,
                consumed_state,
                code="timeout",
                message="The tool call exceeded its deadline.",
                retryable=True,
                security_counters=_without_returned_evidence(
                    admission.security_counters
                ),
                quarantine_summaries=admission.quarantine_summaries,
            )

        context_chars = admission.context_chars
        if (
            consumed_state.context_chars + context_chars
            > consumed_state.budget.max_context_chars
        ):
            return _error_execution(
                action,
                consumed_state,
                code="budget",
                message="The context budget has been exhausted.",
                security_counters=_without_returned_evidence(
                    admission.security_counters
                ),
                quarantine_summaries=admission.quarantine_summaries,
            )
        final_state = _validated_budget_state(
            consumed_state,
            context_chars=consumed_state.context_chars + context_chars,
        )
        return GuardedV2ToolExecution(
            action=action,
            result=admission.result,
            budget_state=final_state,
            status="ok",
            visible_count=admission.security_counters.post_guard_evidence_count,
            context_chars_added=context_chars,
            quarantine_summaries=admission.quarantine_summaries,
            security_counters=admission.security_counters,
            security_stop_reason=admission.security_stop_reason,
        )


def _budget_error(action: AgentAction, state: BudgetState) -> str | None:
    budget = state.budget
    if state.steps >= budget.max_steps:
        return "The tool step budget has been exhausted."
    if state.context_chars >= budget.max_context_chars:
        return "The context budget has been exhausted."
    counters = {
        "search": (state.search_calls, budget.max_search_calls),
        "find": (state.find_calls, budget.max_find_calls),
        "open": (state.open_calls, budget.max_open_calls),
    }
    used, limit = counters[action.tool]
    if used >= limit:
        return f"The {action.tool} tool budget has been exhausted."
    return None


def _effective_deadline_ms(
    action: AgentAction,
    state: BudgetState,
    *,
    started_at_ms: float,
) -> float:
    requests = {
        "search": action.search_request,
        "find": action.find_request,
        "open": action.open_request,
    }
    request = requests[action.tool]
    if request is None:
        raise ValueError("tool action is missing its typed request")
    request_deadline = started_at_ms + request.timeout_ms
    if state.deadline_at_ms is None:
        return request_deadline
    return min(request_deadline, state.deadline_at_ms)


def _consume_call(action: AgentAction, state: BudgetState) -> BudgetState:
    updates = {"steps": state.steps + 1}
    counter_name = f"{action.tool}_calls"
    updates[counter_name] = getattr(state, counter_name) + 1
    return _validated_budget_state(state, **updates)


def _validated_budget_state(
    state: BudgetState,
    **updates: int,
) -> BudgetState:
    values = state.model_dump()
    values["budget"] = state.budget
    values.update(updates)
    return BudgetState(**values)


def _admit(
    admission: RetrievedContentAdmission,
    action: AgentAction,
    raw_result: RankedSearchPool | FindResult | OpenResult,
) -> GuardedAdmissionOutcome:
    if action.tool == "search" and isinstance(raw_result, RankedSearchPool):
        return admission.admit_search(raw_result, action.search_request)
    if action.tool == "find" and isinstance(raw_result, FindResult):
        return admission.admit_find(raw_result)
    if action.tool == "open" and isinstance(raw_result, OpenResult):
        return admission.admit_open(raw_result)
    raise TypeError("raw tool payload does not match the typed action")


def _zero_security_counters() -> SecurityCounters:
    return SecurityCounters(
        candidate_count=0,
        scanned_count=0,
        admitted_count=0,
        quarantined_count=0,
        scanned_chars=0,
        decoded_candidate_count=0,
        top_up_attempts=0,
        post_guard_evidence_count=0,
        guard_error_count=0,
        risk_categories=(),
        rule_ids=(),
        detector_version=DETECTOR_VERSION,
    )


def _without_returned_evidence(counters: SecurityCounters) -> SecurityCounters:
    values = counters.model_dump()
    values["post_guard_evidence_count"] = 0
    return SecurityCounters(**values)


def _error_execution(
    action: AgentAction,
    budget_state: BudgetState,
    *,
    code: ToolErrorCode,
    message: str,
    retryable: bool = False,
    security_counters: SecurityCounters | None = None,
    quarantine_summaries: tuple = (),
) -> GuardedV2ToolExecution:
    return GuardedV2ToolExecution(
        action=action,
        result=ToolError(
            code=code,
            retryable=retryable,
            safe_message=message,
        ),
        budget_state=budget_state,
        status="error",
        visible_count=0,
        context_chars_added=0,
        quarantine_summaries=quarantine_summaries,
        security_counters=security_counters or _zero_security_counters(),
        security_stop_reason=None,
    )


def build_tool_error_execution(
    action: AgentAction,
    budget_state: BudgetState,
    *,
    code: ToolErrorCode,
    message: str,
    retryable: bool = False,
) -> GuardedV2ToolExecution:
    """Build a zero-evidence failure for a rejected contract call."""
    return _error_execution(
        action,
        budget_state,
        code=code,
        message=message,
        retryable=retryable,
    )


__all__ = [
    "Navigator",
    "V2ToolExecution",
    "V2ToolRegistry",
    "build_tool_error_execution",
]
