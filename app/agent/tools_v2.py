from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent import AgentAction, BudgetState, ToolError
from app.domain.queries import FindResult, OpenResult, SearchResult


class Navigator(Protocol):
    def search(self, request): ...

    def find(self, request): ...

    def open(self, request): ...


ToolPayload = SearchResult | FindResult | OpenResult | ToolError
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
    ) -> None:
        self.navigator = navigator
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000)

    def run(
        self,
        action: AgentAction,
        budget_state: BudgetState,
    ) -> V2ToolExecution:
        if not isinstance(action, AgentAction):
            raise TypeError("registry requires a typed AgentAction")
        if action.tool not in {"search", "find", "open"}:
            return _error_execution(
                action,
                budget_state,
                code="invalid_args",
                message="The requested tool is not available.",
            )
        if (
            budget_state.deadline_at_ms is not None
            and self.clock_ms() >= budget_state.deadline_at_ms
        ):
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
                result = self.navigator.search(action.search_request)
            elif action.tool == "find":
                result = self.navigator.find(action.find_request)
            else:
                result = self.navigator.open(action.open_request)
        except Exception:
            return _error_execution(
                action,
                consumed_state,
                code="system",
                message="The tool is temporarily unavailable.",
                retryable=True,
            )

        if not isinstance(result, (SearchResult, FindResult, OpenResult, ToolError)):
            return _error_execution(
                action,
                consumed_state,
                code="system",
                message="The tool returned an invalid response.",
                retryable=True,
            )
        if isinstance(result, ToolError):
            return V2ToolExecution(
                action=action,
                result=result,
                budget_state=consumed_state,
                status="error",
                visible_count=0,
                context_chars_added=0,
            )

        context_chars = _context_chars(result)
        visible_count = _visible_count(result)
        if (
            consumed_state.context_chars + context_chars
            > consumed_state.budget.max_context_chars
        ):
            return _error_execution(
                action,
                consumed_state,
                code="budget",
                message="The context budget has been exhausted.",
            )
        final_state = consumed_state.model_copy(
            update={
                "context_chars": consumed_state.context_chars + context_chars,
            }
        )
        return V2ToolExecution(
            action=action,
            result=result,
            budget_state=final_state,
            status="ok",
            visible_count=visible_count,
            context_chars_added=context_chars,
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


def _consume_call(action: AgentAction, state: BudgetState) -> BudgetState:
    updates = {"steps": state.steps + 1}
    counter_name = f"{action.tool}_calls"
    updates[counter_name] = getattr(state, counter_name) + 1
    return state.model_copy(update=updates)


def _context_chars(result: SearchResult | FindResult | OpenResult) -> int:
    if isinstance(result, SearchResult):
        return sum(len(hit.context_text) for hit in result.hits)
    if isinstance(result, FindResult):
        return sum(len(match.preview) for match in result.matches)
    return len(result.content)


def _visible_count(result: SearchResult | FindResult | OpenResult) -> int:
    if isinstance(result, SearchResult):
        return len(result.hits)
    if isinstance(result, FindResult):
        return len(result.matches)
    return 1


def _error_execution(
    action: AgentAction,
    budget_state: BudgetState,
    *,
    code: Literal["invalid_args", "timeout", "budget", "system"],
    message: str,
    retryable: bool = False,
) -> V2ToolExecution:
    return V2ToolExecution(
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
    )


__all__ = ["Navigator", "V2ToolExecution", "V2ToolRegistry"]
