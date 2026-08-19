from __future__ import annotations

import asyncio

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.mcp_adapter import EnterpriseKnowledgeMCP, MCPContextBroker
from app.agent_runtime.tool_contract import ToolContext
from app.agent_runtime.tool_gateway import ToolGateway
from app.domain.agent import AgentBudget, ToolError
from tests.v2_test_support import (
    RecordingNavigator,
    open_result,
    search_hit,
    search_result,
    user_context,
)


def stack(navigator: RecordingNavigator, *, now: list[float] | None = None):
    clock = now or [100.0]
    gateway = ToolGateway(
        V2ToolRegistry(navigator, clock_ms=lambda: clock[0]),
        clock_ms=lambda: clock[0],
    )
    broker = MCPContextBroker(gateway)
    adapter = EnterpriseKnowledgeMCP(gateway, broker)
    context = ToolContext(
        session_id="mcp-session",
        trace_id="mcp-trace",
        request_id="mcp-request",
        identity=user_context(),
        acl_scope=("employees",),
        issued_at_ms=10.0,
        expires_at_ms=1000.0,
    )
    return adapter, broker, context


def call(adapter: EnterpriseKnowledgeMCP, name: str, arguments: dict):
    result = asyncio.run(adapter.server.call_tool(name, arguments))
    return result.structured_content


def test_official_server_exposes_only_read_only_enterprise_tools() -> None:
    adapter, _, _ = stack(RecordingNavigator())

    tools = asyncio.run(adapter.server.list_tools())

    assert [tool.name for tool in tools] == ["search", "find", "open"]


def test_authorized_search_and_open_use_guarded_gateway() -> None:
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])],
        open_results=[open_result()],
    )
    adapter, broker, context = stack(navigator)
    handle = broker.issue(context)

    searched = call(
        adapter,
        "search",
        {
            "session_handle": handle,
            "query": "remote policy",
            "purpose": "collect evidence",
        },
    )
    opened = call(
        adapter,
        "open",
        {
            "session_handle": handle,
            "target_type": "document",
            "target_id": "doc-a",
        },
    )

    assert searched["status"] == "ok"
    assert searched["sequence"] == 1
    assert searched["payload"]["hits"][0]["hit"]["doc_id"] == "doc-a"
    assert opened["status"] == "ok"
    assert opened["sequence"] == 2
    assert [name for name, _ in navigator.calls] == ["search", "open"]


def test_invalid_or_revoked_session_never_reaches_backend() -> None:
    navigator = RecordingNavigator()
    adapter, broker, context = stack(navigator)
    handle = broker.issue(context)
    broker.revoke(handle)

    invalid = call(
        adapter,
        "search",
        {"session_handle": "x" * 40, "query": "q", "purpose": "p"},
    )
    revoked = call(
        adapter,
        "search",
        {"session_handle": handle, "query": "q", "purpose": "p"},
    )

    assert invalid["error"]["code"] == "stale_context"
    assert revoked["error"]["code"] == "stale_context"
    assert navigator.calls == []


def test_session_tool_scope_denies_search_and_open() -> None:
    navigator = RecordingNavigator()
    adapter, broker, context = stack(navigator)
    restricted = context.model_copy(update={"allowed_tools": ("find",)})
    handle = broker.issue(restricted)

    denied_search = call(
        adapter,
        "search",
        {"session_handle": handle, "query": "q", "purpose": "p"},
    )
    denied_open = call(
        adapter,
        "open",
        {
            "session_handle": handle,
            "target_type": "document",
            "target_id": "doc-a",
        },
    )

    assert denied_search["error"]["code"] == "unauthorized"
    assert denied_open["error"]["code"] == "unauthorized"
    assert navigator.calls == []


def test_malformed_arguments_are_structured_and_safe() -> None:
    navigator = RecordingNavigator()
    adapter, broker, context = stack(navigator)
    handle = broker.issue(context)

    result = call(
        adapter,
        "open",
        {
            "session_handle": handle,
            "target_type": "filesystem",
            "target_id": "../../secret",
        },
    )

    assert result["error"]["code"] == "invalid_args"
    assert "../../secret" not in str(result)
    assert navigator.calls == []


def test_budget_and_permission_errors_cross_protocol_as_structured_data() -> None:
    navigator = RecordingNavigator(
        search_results=[
            search_result([search_hit()]),
            ToolError(
                code="permission",
                retryable=False,
                safe_message="Document access is denied.",
            ),
        ]
    )
    adapter, broker, context = stack(navigator)
    limited = context.model_copy(
        update={"budget": AgentBudget(max_search_calls=1)}
    )
    first_handle = broker.issue(limited)
    args = {
        "session_handle": first_handle,
        "query": "policy",
        "purpose": "collect evidence",
    }
    assert call(adapter, "search", args)["status"] == "ok"
    assert call(adapter, "search", args)["error"]["code"] == "budget"

    second_context = context.model_copy(
        update={
            "session_id": "mcp-session-two",
            "request_id": "mcp-request-two",
        }
    )
    second_handle = broker.issue(second_context)
    denied = call(
        adapter,
        "search",
        {
            "session_handle": second_handle,
            "query": "secret policy",
            "purpose": "collect evidence",
        },
    )
    assert denied["error"]["code"] == "permission"


def test_session_expiry_is_enforced_by_gateway() -> None:
    now = [100.0]
    adapter, broker, context = stack(RecordingNavigator(), now=now)
    handle = broker.issue(context)
    now[0] = 1001.0

    result = call(
        adapter,
        "search",
        {"session_handle": handle, "query": "q", "purpose": "p"},
    )

    assert result["error"]["code"] == "stale_context"


def test_tool_timeout_discards_mcp_payload() -> None:
    now = [100.0]

    class SlowNavigator(RecordingNavigator):
        def search_ranked(self, request):
            now[0] = 1001.0
            return super().search_ranked(request)

    navigator = SlowNavigator(search_results=[search_result([search_hit()])])
    adapter, broker, context = stack(navigator, now=now)
    handle = broker.issue(context)

    result = call(
        adapter,
        "search",
        {"session_handle": handle, "query": "q", "purpose": "p"},
    )

    assert result["error"]["code"] == "timeout"
    assert "payload" not in result
