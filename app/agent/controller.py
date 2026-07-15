from collections.abc import Callable
from typing import Any, Protocol

from app.agent.evidence import EvidenceAssessment, is_usable_rewrite
from app.agent.planner import build_plan
from app.agent.schemas import PlanStep, RouteDecision


PlannerFn = Callable[[RouteDecision], list[PlanStep]]


class AgentController(Protocol):
    def initialize(
        self,
        decision: RouteDecision,
        *,
        question: str,
        top_k: int | None,
    ) -> dict[str, Any]: ...

    def next_step(
        self,
        decision: RouteDecision,
        context: dict[str, Any],
    ) -> PlanStep | None: ...


def _base_context(
    decision: RouteDecision,
    *,
    question: str,
    top_k: int | None,
) -> dict[str, Any]:
    return {
        "question": question,
        "search_query": question,
        "top_k": top_k,
        "route": decision.route,
        "phase": "start",
        "retrieval_attempts": 0,
        "latest_retrieved_chunks": [],
        "latest_retrieved_sources": [],
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "evidence_history": [],
    }


class FixedPlanController:
    def __init__(self, planner: PlannerFn = build_plan) -> None:
        self.planner = planner

    def initialize(
        self,
        decision: RouteDecision,
        *,
        question: str,
        top_k: int | None,
    ) -> dict[str, Any]:
        context = _base_context(decision, question=question, top_k=top_k)
        context["fixed_plan"] = self.planner(decision)
        context["fixed_plan_index"] = 0
        return context

    def next_step(
        self,
        decision: RouteDecision,
        context: dict[str, Any],
    ) -> PlanStep | None:
        plan = context["fixed_plan"]
        index = context["fixed_plan_index"]
        if index >= len(plan):
            return None
        context["fixed_plan_index"] = index + 1
        return plan[index]


class AdaptiveController:
    def __init__(self, max_retrieval_attempts: int = 2) -> None:
        if not 1 <= max_retrieval_attempts <= 2:
            raise ValueError("max_retrieval_attempts must be between 1 and 2")
        self.max_retrieval_attempts = max_retrieval_attempts

    def initialize(
        self,
        decision: RouteDecision,
        *,
        question: str,
        top_k: int | None,
    ) -> dict[str, Any]:
        context = _base_context(decision, question=question, top_k=top_k)
        context["max_retrieval_attempts"] = self.max_retrieval_attempts
        return context

    def next_step(
        self,
        decision: RouteDecision,
        context: dict[str, Any],
    ) -> PlanStep | None:
        phase = context["phase"]

        if phase == "start":
            if decision.route == "unsafe_request":
                return PlanStep(
                    tool="guardrail.refuse",
                    reason="refuse unsafe request before retrieval or generation",
                )
            return PlanStep(
                tool="retrieval.search",
                reason=f"retrieve initial evidence for {decision.route}",
            )

        if phase == "retrieved":
            latest_chunks = context.get(
                "latest_retrieved_chunks",
                context.get("retrieved_chunks", []),
            )
            if not latest_chunks:
                return PlanStep(
                    tool="rag.no_answer",
                    reason="stop because retrieval returned no evidence",
                )
            return PlanStep(
                tool="evidence.assess",
                reason="check whether retrieved chunks support the original question",
            )

        if phase == "assessed":
            assessment = context.get("evidence_assessment")
            if not isinstance(assessment, EvidenceAssessment):
                raise RuntimeError("assessed phase requires EvidenceAssessment")

            if assessment.verdict == "sufficient":
                return PlanStep(
                    tool="rag.answer",
                    reason="generate only after evidence is sufficient",
                )

            attempts = int(context.get("retrieval_attempts", 0))
            can_retry = attempts < self.max_retrieval_attempts
            if assessment.verdict == "insufficient" and can_retry and is_usable_rewrite(
                assessment.rewritten_query,
                context["question"],
                context["search_query"],
            ):
                return PlanStep(
                    tool="query.rewrite",
                    reason="apply one intent-preserving retrieval rewrite",
                )

            return PlanStep(
                tool="rag.no_answer",
                reason="stop because evidence is insufficient or assessment failed",
            )

        if phase == "rewritten":
            return PlanStep(
                tool="retrieval.search",
                reason="retry retrieval once with the rewritten query",
            )

        if phase in {"answered", "no_answer"}:
            return PlanStep(
                tool="guardrail.check",
                reason="check the final response before returning it",
            )

        if phase in {"guarded", "refused"}:
            return None

        raise RuntimeError(f"Unsupported agent phase: {phase!r}")


__all__ = [
    "AdaptiveController",
    "AgentController",
    "FixedPlanController",
]
