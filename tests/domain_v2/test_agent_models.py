import pytest
from pydantic import ValidationError

from app.domain.agent import (
    AgentAction,
    AgentBudget,
    BudgetState,
    ToolError,
)
from app.domain.queries import OpenRequest, SearchRequest, UserContext


def user() -> UserContext:
    return UserContext(
        user_id="user-employee",
        tenant_id="starbridge-cn",
        region="cn",
        groups=["all_employees"],
    )


def search_request() -> SearchRequest:
    return SearchRequest(
        query="remote work",
        purpose="remote policy",
        user=user(),
    )


def test_budget_rejects_nonpositive_limits() -> None:
    with pytest.raises(ValidationError):
        AgentBudget(max_search_calls=0)


def test_budget_state_cannot_exceed_any_hard_limit() -> None:
    budget = AgentBudget(max_search_calls=1, max_steps=2, max_context_chars=100)
    with pytest.raises(ValidationError, match="search"):
        BudgetState(budget=budget, search_calls=2)
    with pytest.raises(ValidationError, match="steps"):
        BudgetState(budget=budget, steps=3)
    with pytest.raises(ValidationError, match="context"):
        BudgetState(budget=budget, context_chars=101)


def test_search_action_requires_only_a_search_request() -> None:
    action = AgentAction(
        sequence=1,
        tool="search",
        purpose="find remote policy",
        aspect="remote policy",
        search_request=search_request(),
    )
    assert action.search_request.query == "remote work"

    with pytest.raises(ValidationError, match="search_request"):
        AgentAction(
            sequence=1,
            tool="search",
            purpose="find remote policy",
            aspect="remote policy",
        )


def test_action_rejects_request_for_another_tool() -> None:
    with pytest.raises(ValidationError, match="request"):
        AgentAction(
            sequence=1,
            tool="search",
            purpose="wrong request type",
            aspect="remote policy",
            open_request=OpenRequest(
                user=user(),
                target_type="document",
                target_id="doc-a",
            ),
        )


def test_terminal_action_cannot_carry_tool_requests() -> None:
    with pytest.raises(ValidationError, match="terminal"):
        AgentAction(
            sequence=2,
            tool="answer",
            purpose="finish",
            search_request=search_request(),
        )


def test_tool_error_is_structured_and_forbids_debug_details() -> None:
    error = ToolError(
        code="permission",
        retryable=False,
        safe_message="The requested resource is unavailable.",
    )
    assert error.code == "permission"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ToolError(
            code="system",
            retryable=False,
            safe_message="Request failed.",
            internal_path="D:/secret/index",
        )
