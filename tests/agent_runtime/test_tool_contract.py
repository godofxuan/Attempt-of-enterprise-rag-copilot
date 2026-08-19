from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.tool_contract import ToolContext, ToolRequest
from app.agent_runtime.tool_gateway import ToolGateway
from app.domain.agent import AgentBudget, ToolError as DomainToolError
from app.domain.queries import OpenRequest, SearchRequest, UserContext
from tests.v2_test_support import RecordingNavigator, search_hit, search_result


USER = UserContext(
    user_id="employee-one",
    tenant_id="tenant-one",
    region="cn",
    groups=["employees"],
)


def context(**updates) -> ToolContext:
    values = {
        "session_id": "session-one",
        "trace_id": "trace-one",
        "request_id": "request-one",
        "identity": USER,
        "acl_scope": ("employees",),
        "issued_at_ms": 10.0,
        "expires_at_ms": 1000.0,
    }
    values.update(updates)
    return ToolContext(**values)


def search_request(*, user: UserContext = USER, sequence: int = 1) -> ToolRequest:
    return ToolRequest(
        context_request_id="request-one",
        tool="search",
        sequence=sequence,
        purpose="collect evidence",
        aspect="policy",
        arguments=SearchRequest(
            request_id="request-one",
            user=user,
            query="remote policy",
            purpose="collect evidence",
            mode="bm25",
        ),
    )


def gateway(navigator: RecordingNavigator, *, now: list[float] | None = None) -> ToolGateway:
    clock = now or [100.0]
    return ToolGateway(
        V2ToolRegistry(navigator, clock_ms=lambda: clock[0]),
        clock_ms=lambda: clock[0],
    )


def test_authorized_request_uses_existing_guarded_registry() -> None:
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    tool_gateway = gateway(navigator)
    trusted = context()
    tool_gateway.start_session(trusted)

    result = tool_gateway.execute(search_request(), trusted)

    assert result.status == "ok"
    assert result.payload.hits[0].hit.doc_id == "doc-a"
    assert result.budget_state.search_calls == 1
    assert [name for name, _ in navigator.calls] == ["search"]


def test_tool_not_in_session_allowlist_fails_before_backend() -> None:
    navigator = RecordingNavigator()
    tool_gateway = gateway(navigator)
    trusted = context(allowed_tools=("find", "open"))
    tool_gateway.start_session(trusted)

    result = tool_gateway.execute(search_request(), trusted)

    assert result.error.code == "unauthorized"
    assert navigator.calls == []


def test_forged_identity_and_cross_tenant_fail_before_backend() -> None:
    navigator = RecordingNavigator()
    tool_gateway = gateway(navigator)
    trusted = context()
    tool_gateway.start_session(trusted)
    attacker = UserContext(
        user_id="attacker",
        tenant_id="tenant-two",
        region="cn",
        groups=["employees"],
    )

    result = tool_gateway.execute(search_request(user=attacker), trusted)

    assert result.error.code == "identity_mismatch"
    assert navigator.calls == []


def test_supplied_context_cannot_replace_server_session_identity() -> None:
    navigator = RecordingNavigator()
    tool_gateway = gateway(navigator)
    trusted = context()
    tool_gateway.start_session(trusted)
    forged = context(trace_id="trace-forged")

    result = tool_gateway.execute(search_request(), forged)

    assert result.error.code == "identity_mismatch"
    assert navigator.calls == []


def test_expired_and_closed_sessions_are_stale() -> None:
    now = [100.0]
    tool_gateway = gateway(RecordingNavigator(), now=now)
    trusted = context()
    tool_gateway.start_session(trusted)
    now[0] = 1001.0
    expired = tool_gateway.execute(search_request(), trusted)
    tool_gateway.close_session(trusted.session_id)
    closed = tool_gateway.execute(search_request(), trusted)

    assert expired.error.code == "stale_context"
    assert closed.error.code == "stale_context"


def test_budget_is_stateful_across_contract_calls() -> None:
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    tool_gateway = gateway(navigator)
    trusted = context(budget=AgentBudget(max_search_calls=1))
    tool_gateway.start_session(trusted)

    first = tool_gateway.execute(search_request(sequence=1), trusted)
    second = tool_gateway.execute(search_request(sequence=2), trusted)

    assert first.status == "ok"
    assert second.error.code == "budget"
    assert len(navigator.calls) == 1


def test_backend_permission_denial_remains_structured() -> None:
    navigator = RecordingNavigator(
        search_results=[
            DomainToolError(
                code="permission",
                retryable=False,
                safe_message="Document access is denied.",
            )
        ]
    )
    tool_gateway = gateway(navigator)
    trusted = context()
    tool_gateway.start_session(trusted)

    result = tool_gateway.execute(search_request(), trusted)

    assert result.error.code == "permission"
    assert "Document access" in result.error.safe_message


def test_timeout_is_bounded_by_session_expiry() -> None:
    now = [999.0]

    class SlowNavigator(RecordingNavigator):
        def search_ranked(self, request):
            now[0] = 1001.0
            return super().search_ranked(request)

    navigator = SlowNavigator(search_results=[search_result([search_hit()])])
    tool_gateway = gateway(navigator, now=now)
    trusted = context(issued_at_ms=900.0)
    tool_gateway.start_session(trusted)

    result = tool_gateway.execute(search_request(), trusted)

    assert result.error.code == "timeout"
    assert result.payload is None


def test_malformed_or_mismatched_arguments_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolRequest(
            context_request_id="request-one",
            tool="search",
            sequence=1,
            purpose="bad shape",
            arguments=OpenRequest(
                request_id="request-one",
                user=USER,
                target_type="document",
                target_id="doc-a",
            ),
        )

    with pytest.raises(ValidationError):
        ToolRequest.model_validate(
            {
                "context_request_id": "request-one",
                "tool": "shell",
                "sequence": 1,
                "purpose": "escape",
                "arguments": {},
            }
        )


def test_acl_scope_may_equal_or_narrow_authenticated_groups() -> None:
    multi_group_user = USER.model_copy(
        update={"groups": ["employees", "finance"]}
    )

    same = context(
        identity=multi_group_user,
        acl_scope=("employees", "finance"),
    )
    narrower = context(identity=multi_group_user, acl_scope=("employees",))

    assert set(same.acl_scope) == set(multi_group_user.groups)
    assert narrower.acl_scope == ("employees",)


@pytest.mark.parametrize(
    "acl_scope",
    [
        ("employees", "finance_admin"),
        ("contractors",),
    ],
)
def test_acl_scope_rejects_expansion_or_unrelated_group(acl_scope) -> None:
    with pytest.raises(ValidationError, match="ACL scope"):
        context(acl_scope=acl_scope)
