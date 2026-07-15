from app.agent.planner import build_plan
from app.agent.schemas import RouteDecision


def tool_names(plan):
    return [step.tool for step in plan]


def test_planner_refuses_unsafe_route_without_retrieval():
    plan = build_plan(RouteDecision(route="unsafe_request", reason="unsafe keyword"))

    assert tool_names(plan) == ["guardrail.refuse"]
    assert "refuse" in plan[0].reason


def test_planner_runs_retrieval_answer_and_guardrail_for_policy_qa():
    plan = build_plan(RouteDecision(route="policy_qa", reason="default"))

    assert tool_names(plan) == [
        "retrieval.search",
        "rag.answer",
        "guardrail.check",
    ]


def test_planner_keeps_same_tool_loop_for_comparison_and_process():
    comparison_plan = build_plan(RouteDecision(route="comparison", reason="comparison keyword"))
    process_plan = build_plan(RouteDecision(route="process", reason="process keyword"))

    assert tool_names(comparison_plan) == tool_names(process_plan)
    assert tool_names(comparison_plan) == [
        "retrieval.search",
        "rag.answer",
        "guardrail.check",
    ]
