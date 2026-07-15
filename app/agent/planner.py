from app.agent.schemas import PlanStep, RouteDecision


def build_plan(decision: RouteDecision) -> list[PlanStep]:
    if decision.route == "unsafe_request":
        return [
            PlanStep(
                tool="guardrail.refuse",
                reason="refuse unsafe request before retrieval or generation",
            )
        ]

    return [
        PlanStep(
            tool="retrieval.search",
            reason=f"retrieve policy evidence for {decision.route}",
        ),
        PlanStep(
            tool="rag.answer",
            reason="generate grounded answer using the current RAG pipeline",
        ),
        PlanStep(
            tool="guardrail.check",
            reason="check the generated answer before returning it",
        ),
    ]
