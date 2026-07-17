from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentAction, AgentBudget, BudgetState, ToolError
from app.domain.queries import FindRequest, OpenRequest, SearchRequest
from tests.v2_test_support import (
    RecordingNavigator,
    find_result,
    open_result,
    search_hit,
    search_result,
    user_context,
)


USER = user_context()


def search_action(sequence: int = 1) -> AgentAction:
    return AgentAction(
        sequence=sequence,
        tool="search",
        purpose="collect answer evidence",
        aspect="answer",
        search_request=SearchRequest(
            user=USER,
            query="remote policy",
            purpose="collect answer evidence",
            mode="bm25",
        ),
    )


def find_action(sequence: int = 1) -> AgentAction:
    return AgentAction(
        sequence=sequence,
        tool="find",
        purpose="narrow inside document",
        aspect="answer",
        find_request=FindRequest(
            user=USER,
            doc_id="doc-a",
            pattern="approval",
        ),
    )


def open_action(sequence: int = 1, max_chars: int = 100) -> AgentAction:
    return AgentAction(
        sequence=sequence,
        tool="open",
        purpose="open complete document",
        aspect="complete_policy_coverage",
        open_request=OpenRequest(
            user=USER,
            target_type="document",
            target_id="doc-a",
            max_chars=max_chars,
        ),
    )


def test_search_find_and_open_consume_separate_counters() -> None:
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])],
        find_results=[find_result()],
        open_results=[open_result()],
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 10.0)
    state = BudgetState(
        budget=AgentBudget(
            max_search_calls=2,
            max_find_calls=2,
            max_open_calls=2,
            max_steps=6,
            max_context_chars=1000,
        ),
        deadline_at_ms=1000.0,
    )

    search_execution = registry.run(search_action(1), state)
    find_execution = registry.run(find_action(2), search_execution.budget_state)
    open_execution = registry.run(open_action(3), find_execution.budget_state)

    final = open_execution.budget_state
    assert (final.search_calls, final.find_calls, final.open_calls) == (1, 1, 1)
    assert final.steps == 3
    assert final.context_chars > 0
    assert [name for name, _ in navigator.calls] == ["search", "find", "open"]


def test_over_budget_returns_error_without_executing_tool() -> None:
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 10.0)
    budget = AgentBudget(max_search_calls=1)
    state = BudgetState(
        budget=budget,
        search_calls=1,
        steps=1,
        deadline_at_ms=1000.0,
    )

    execution = registry.run(search_action(2), state)

    assert isinstance(execution.result, ToolError)
    assert execution.result.code == "budget"
    assert execution.budget_state == state
    assert navigator.calls == []


def test_deadline_returns_timeout_without_executing_tool() -> None:
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 100.0)
    state = BudgetState(deadline_at_ms=99.0)

    execution = registry.run(search_action(), state)

    assert isinstance(execution.result, ToolError)
    assert execution.result.code == "timeout"
    assert execution.budget_state == state
    assert navigator.calls == []


def test_context_cap_discards_oversized_result_but_counts_executed_call() -> None:
    secret_content = "visible but oversized " * 10
    navigator = RecordingNavigator(
        open_results=[open_result(content=secret_content)]
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 10.0)
    state = BudgetState(
        budget=AgentBudget(max_context_chars=100),
        context_chars=90,
        deadline_at_ms=1000.0,
    )

    execution = registry.run(open_action(max_chars=100), state)

    assert isinstance(execution.result, ToolError)
    assert execution.result.code == "budget"
    assert execution.budget_state.open_calls == 1
    assert execution.budget_state.steps == 1
    assert execution.budget_state.context_chars == 90
    assert secret_content not in execution.model_dump_json()


def test_terminal_action_is_not_in_tool_allowlist_and_consumes_nothing() -> None:
    navigator = RecordingNavigator()
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 10.0)
    state = BudgetState(deadline_at_ms=1000.0)
    action = AgentAction(
        sequence=1,
        tool="refuse",
        purpose="unsafe short circuit",
    )

    execution = registry.run(action, state)

    assert isinstance(execution.result, ToolError)
    assert execution.result.code == "invalid_args"
    assert execution.budget_state == state
    assert navigator.calls == []


def test_arbitrary_tool_name_cannot_enter_registry() -> None:
    with pytest.raises(ValidationError):
        AgentAction(
            sequence=1,
            tool="shell",
            purpose="run an arbitrary command",
        )
