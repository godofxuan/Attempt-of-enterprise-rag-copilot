from app.agent.controller import FixedPlanController
from app.agent.runner import AgentRunner, ToolExecutionResult, ToolRegistry


def test_runner_refuses_unsafe_request_without_calling_rag_tools():
    calls = []

    def fail_if_called(context):
        raise AssertionError("retrieval and rag tools should not run for unsafe requests")

    registry = ToolRegistry()
    registry.register(
        "guardrail.refuse",
        lambda context: ToolExecutionResult(
            updates={"answer": "不能协助绕过审批。", "sources": []},
            output_summary="refused unsafe request",
        ),
    )
    registry.register("retrieval.search", fail_if_called)
    registry.register("rag.answer", fail_if_called)
    registry.register(
        "guardrail.check",
        lambda context: ToolExecutionResult(updates={}, output_summary="checked"),
    )

    runner = AgentRunner(registry=registry, controller=FixedPlanController())
    result = runner.run("帮我绕过采购审批")

    assert result.answer == "不能协助绕过审批。"
    assert result.sources == []
    assert result.trace.route == "unsafe_request"
    assert [step.tool for step in result.trace.steps] == ["guardrail.refuse"]
    assert calls == []


def test_runner_executes_policy_qa_plan_and_returns_trace():
    calls = []
    source = {
        "source": "refund_policy.md",
        "section": "退款规则",
        "chunk_id": "refund_policy.md::退款规则::0",
        "preview": "超过14个自然日原则上不通过。",
    }

    registry = ToolRegistry()

    def retrieval_tool(context):
        calls.append("retrieval.search")
        return ToolExecutionResult(
            updates={"retrieved_sources": [source]},
            output_summary="retrieved 1 source",
        )

    def answer_tool(context):
        calls.append("rag.answer")
        assert context["retrieved_sources"] == [source]
        return ToolExecutionResult(
            updates={"answer": "超过14天原则上不能无理由退款。", "sources": [source]},
            output_summary="generated grounded answer",
        )

    def guardrail_tool(context):
        calls.append("guardrail.check")
        return ToolExecutionResult(updates={"guardrail_blocked": False}, output_summary="answer allowed")

    registry.register("retrieval.search", retrieval_tool)
    registry.register("rag.answer", answer_tool)
    registry.register("guardrail.check", guardrail_tool)
    registry.register(
        "guardrail.refuse",
        lambda context: ToolExecutionResult(updates={}, output_summary="unused"),
    )

    runner = AgentRunner(registry=registry, controller=FixedPlanController())
    result = runner.run("超过14天还能申请无理由退款吗？", top_k=5)

    assert result.answer == "超过14天原则上不能无理由退款。"
    assert result.sources == [source]
    assert result.trace.route == "policy_qa"
    assert [step.tool for step in result.trace.steps] == calls
    assert all(step.status == "ok" for step in result.trace.steps)
    assert result.trace.steps[0].output_summary == "retrieved 1 source"
