import pytest

from app.agent.controller import AdaptiveController, FixedPlanController
from app.agent.evidence import EvidenceAssessment
from app.agent.schemas import AgentTrace, RouteDecision


def route(name: str = "policy_qa") -> RouteDecision:
    return RouteDecision(route=name, reason="test route")


def initialized_context(
    controller: AdaptiveController,
    decision: RouteDecision | None = None,
) -> tuple[RouteDecision, dict]:
    decision = decision or route()
    context = controller.initialize(
        decision,
        question="What is the refund deadline?",
        top_k=5,
    )
    return decision, context


@pytest.mark.parametrize("attempts", [0, 3])
def test_adaptive_controller_rejects_attempt_budget_outside_hard_limit(attempts):
    with pytest.raises(ValueError, match="between 1 and 2"):
        AdaptiveController(max_retrieval_attempts=attempts)


def test_adaptive_controller_initializes_immutable_and_mutable_queries():
    controller = AdaptiveController(max_retrieval_attempts=2)
    decision, context = initialized_context(controller)

    assert context["question"] == "What is the refund deadline?"
    assert context["search_query"] == context["question"]
    assert context["retrieval_attempts"] == 0
    assert context["max_retrieval_attempts"] == 2
    assert context["phase"] == "start"
    assert context["latest_retrieved_chunks"] == []
    assert context["evidence_history"] == []
    assert controller.next_step(decision, context).tool == "retrieval.search"


def test_adaptive_controller_refuses_unsafe_route_before_retrieval():
    controller = AdaptiveController()
    decision, context = initialized_context(controller, route("unsafe_request"))

    assert controller.next_step(decision, context).tool == "guardrail.refuse"

    context["phase"] = "refused"
    assert controller.next_step(decision, context) is None


def test_adaptive_controller_short_circuits_empty_retrieval_to_no_answer():
    controller = AdaptiveController()
    decision, context = initialized_context(controller)
    context.update(
        phase="retrieved",
        latest_retrieved_chunks=[],
        retrieved_chunks=[{"text": "evidence retained from an earlier attempt"}],
        retrieval_attempts=2,
    )

    assert controller.next_step(decision, context).tool == "rag.no_answer"


def test_adaptive_controller_assesses_non_empty_retrieval():
    controller = AdaptiveController()
    decision, context = initialized_context(controller)
    context.update(
        phase="retrieved",
        latest_retrieved_chunks=[{"text": "policy evidence"}],
        retrieved_chunks=[{"text": "policy evidence"}],
        retrieval_attempts=1,
    )

    assert controller.next_step(decision, context).tool == "evidence.assess"


def test_adaptive_controller_answers_sufficient_evidence():
    controller = AdaptiveController()
    decision, context = initialized_context(controller)
    context.update(
        phase="assessed",
        retrieval_attempts=1,
        evidence_assessment=EvidenceAssessment(
            verdict="sufficient",
            reason="direct support",
        ),
    )

    assert controller.next_step(decision, context).tool == "rag.answer"


def test_adaptive_controller_rewrites_once_when_evidence_is_insufficient():
    controller = AdaptiveController(max_retrieval_attempts=2)
    decision, context = initialized_context(controller)
    context.update(
        phase="assessed",
        retrieval_attempts=1,
        evidence_assessment=EvidenceAssessment(
            verdict="insufficient",
            reason="missing deadline",
            rewritten_query="employee refund policy deadline",
        ),
    )

    assert controller.next_step(decision, context).tool == "query.rewrite"

    context.update(phase="rewritten", search_query="employee refund policy deadline")
    assert controller.next_step(decision, context).tool == "retrieval.search"


@pytest.mark.parametrize(
    "assessment",
    [
        EvidenceAssessment(
            verdict="insufficient",
            reason="still missing",
            rewritten_query="another query",
        ),
        EvidenceAssessment(
            verdict="error",
            reason="evidence assessment failed: RuntimeError",
        ),
    ],
)
def test_adaptive_controller_stops_after_second_attempt_or_assessment_error(
    assessment,
):
    controller = AdaptiveController(max_retrieval_attempts=2)
    decision, context = initialized_context(controller)
    context.update(
        phase="assessed",
        retrieval_attempts=2,
        evidence_assessment=assessment,
    )

    assert controller.next_step(decision, context).tool == "rag.no_answer"


def test_adaptive_controller_rejects_blank_or_unchanged_rewrite():
    controller = AdaptiveController(max_retrieval_attempts=2)
    decision, context = initialized_context(controller)
    context.update(
        phase="assessed",
        retrieval_attempts=1,
        evidence_assessment=EvidenceAssessment(
            verdict="insufficient",
            reason="missing evidence",
            rewritten_query="What is the refund deadline?",
        ),
    )

    assert controller.next_step(decision, context).tool == "rag.no_answer"


@pytest.mark.parametrize("phase", ["answered", "no_answer"])
def test_adaptive_controller_guardrail_checks_completed_answer(phase):
    controller = AdaptiveController()
    decision, context = initialized_context(controller)
    context["phase"] = phase

    assert controller.next_step(decision, context).tool == "guardrail.check"

    context["phase"] = "guarded"
    assert controller.next_step(decision, context) is None


def test_adaptive_controller_rejects_impossible_phase():
    controller = AdaptiveController()
    decision, context = initialized_context(controller)
    context["phase"] = "unknown"

    with pytest.raises(RuntimeError, match="Unsupported agent phase"):
        controller.next_step(decision, context)


def test_fixed_plan_controller_preserves_historical_sequence():
    controller = FixedPlanController()
    decision = route()
    context = controller.initialize(
        decision,
        question="What is the refund deadline?",
        top_k=5,
    )

    tools = []
    while (step := controller.next_step(decision, context)) is not None:
        tools.append(step.tool)

    assert tools == ["retrieval.search", "rag.answer", "guardrail.check"]


def test_agent_trace_new_fields_have_backward_compatible_defaults():
    trace = AgentTrace(
        route="policy_qa",
        route_reason="default",
        plan=[],
        steps=[],
    )

    assert trace.retrieval_attempts == 0
    assert trace.evidence_history == []
    assert trace.final_outcome is None
