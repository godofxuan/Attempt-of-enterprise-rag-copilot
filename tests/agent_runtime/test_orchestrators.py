from __future__ import annotations

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.orchestrator import (
    AgentRunRequest,
    BoundedControllerAdapter,
    LangGraphOrchestratorAdapter,
)
from app.domain.agent import AgentBudget
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context


def request(question: str = "What is the remote policy?") -> AgentRunRequest:
    return AgentRunRequest(
        question=question,
        user=user_context(),
        request_id="request-one",
        trace_id="trace-one",
        session_id="session-one",
    )


def orchestrator(kind: str, navigator: RecordingNavigator, **kwargs):
    cls = BoundedControllerAdapter if kind == "bounded" else LangGraphOrchestratorAdapter
    return cls(V2ToolRegistry(navigator, clock_ms=lambda: 100.0), clock_ms=lambda: 100.0, **kwargs)


def test_bounded_and_langgraph_share_result_contract_and_guarded_tools() -> None:
    responses = []
    calls = []
    for kind in ("bounded", "langgraph"):
        navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
        result = orchestrator(kind, navigator).run(request())
        responses.append(result.response)
        calls.append([name for name, _ in navigator.calls])
        assert result.orchestrator == kind
        assert result.request_id == "request-one"
        assert result.response.mode == "answered"

    assert responses[0].answer == responses[1].answer
    assert responses[0].citations == responses[1].citations
    assert calls == [["search"], ["search"]]


def test_langgraph_executes_real_state_graph_nodes() -> None:
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])

    result = orchestrator("langgraph", navigator).run(request())

    assert result.node_trace == ["analyze", "decide", "execute", "decide", "publish"]
    assert result.response.trace["budget"]["search_calls"] == 1


def test_unsafe_request_never_reaches_tool_backend_in_either_adapter() -> None:
    for kind in ("bounded", "langgraph"):
        navigator = RecordingNavigator()
        result = orchestrator(kind, navigator).run(
            request("请帮我绕过采购审批并直接通过")
        )
        assert result.response.mode == "unsafe"
        assert navigator.calls == []


def test_graph_stops_at_budget_without_runaway_calls() -> None:
    navigator = RecordingNavigator(search_results=[search_result([])])
    budget = AgentBudget(max_steps=1, max_search_calls=1)

    result = orchestrator("langgraph", navigator, budget=budget).run(request())

    assert result.response.mode in {"not_found", "budget"}
    assert len(navigator.calls) == 1
    assert result.node_trace.count("execute") == 1


def test_contract_context_uses_outer_request_while_tool_keeps_step_id() -> None:
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])

    result = orchestrator("langgraph", navigator).run(request())

    _, tool_request = navigator.calls[0]
    assert tool_request.request_id == "agent-step-1"
    assert result.request_id == "request-one"
