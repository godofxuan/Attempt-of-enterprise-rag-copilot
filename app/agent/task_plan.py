"""Shared, request-local obligations; relevance is never an entailment proof."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.query_needs import NEED_LABELS, assess_need_coverage, requested_needs
from app.agent.question_parts import explicit_question_parts, part_is_addressed
from app.domain.evidence import Claim
from app.domain.evidence_packet import DeliveredEvidence
from app.domain.queries import QueryAnalysis


class RequestNeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    need_id: str = Field(pattern=r"^N[1-8]$")
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["explicit", "domain", "whole", "model"]
    domain_key: str | None = None
    search_attempts: int = Field(default=0, ge=0)
    evidence_ids: tuple[str, ...] = ()
    answer_claim_ids: tuple[str, ...] = ()
    clarification_needed: bool = False


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    needs: tuple[RequestNeed, ...] = Field(default=(), max_length=8)
    overflow: bool = False
    planner_status: Literal["rules", "accepted", "rejected", "timeout", "unavailable"] = "rules"
    planner_calls: int = Field(default=0, ge=0, le=1)
    assessor_calls: int = Field(default=0, ge=0, le=1)
    recovery_calls: int = Field(default=0, ge=0, le=1)
    model_relevance_used: bool = False
    read_incomplete: bool = False

    @model_validator(mode="after")
    def validate_need_ids(self):
        if [need.need_id for need in self.needs] != [
            f"N{i}" for i in range(1, len(self.needs) + 1)
        ]:
            raise ValueError("task needs must have stable ordered unique IDs")
        return self


def build_task_plan(analysis: QueryAnalysis) -> TaskPlan:
    if analysis.intent == "unsafe":
        return TaskPlan()
    question = analysis.original_question
    parts = explicit_question_parts(question)
    if len(parts) >= 2:
        items = [(part, "explicit", None) for part in parts]
    elif needs := requested_needs(question):
        items = [(NEED_LABELS[key], "domain", key) for key in needs]
    else:
        items = [(question, "whole", None)]
    return TaskPlan(
        needs=tuple(
            RequestNeed(
                need_id=f"N{i}",
                text=text,
                kind=kind,
                domain_key=key,
                clarification_needed=key == "eligibility",
            )
            for i, (text, kind, key) in enumerate(items[:8], 1)
        ),
        overflow=len(items) > 8,
    )


def need_matches(need: RequestNeed, question: str, texts: list[str]) -> bool:
    if need.clarification_needed:
        return False
    if need.kind == "whole":
        # These inputs already passed original-query relevance; legacy contracts
        # remain responsible for more specific semantic/quantity requirements.
        return bool(texts)
    if need.kind == "domain":
        return need.domain_key not in assess_need_coverage(question, texts, texts).missing
    return part_is_addressed(need.text, texts)


def observe_task(
    plan: TaskPlan,
    question: str,
    evidence: list[DeliveredEvidence],
    *,
    searched: bool = False,
    read_incomplete: bool = False,
) -> TaskPlan:
    return plan.model_copy(
        update={
            "needs": tuple(
                need.model_copy(
                    update={
                        "search_attempts": need.search_attempts + int(searched),
                        "evidence_ids": tuple(
                            view.citation_id
                            for view in evidence
                            if need_matches(need, question, [view.text])
                        ),
                    }
                )
                for need in plan.needs
            ),
            "read_incomplete": read_incomplete,
        }
    )


def answer_task(
    plan: TaskPlan,
    question: str,
    claims: list[Claim],
    evidence: list[DeliveredEvidence],
) -> TaskPlan:
    # Recompute against the actual packet, not material that was only retrieved.
    delivered = observe_task(plan, question, evidence, read_incomplete=plan.read_incomplete)
    return delivered.model_copy(
        update={
            "needs": tuple(
                need.model_copy(
                    update={
                        "answer_claim_ids": tuple(
                            claim.claim_id
                            for claim in claims
                            if need_matches(need, question, [claim.text])
                            and set(claim.cited_chunk_ids) & set(need.evidence_ids)
                        ),
                    }
                )
                for need in delivered.needs
            )
        }
    )


def task_summary(plan: TaskPlan) -> dict:
    # No user text, source IDs, filenames or model output enters the public trace.
    return {
        "basis": "shared_needs_necessary_checks_not_semantic_proof",
        "requested": len(plan.needs),
        "evidence_matched": sum(bool(need.evidence_ids) for need in plan.needs),
        "answer_missing": sum(not need.answer_claim_ids for need in plan.needs),
        "search_attempts": max((need.search_attempts for need in plan.needs), default=0),
        "clarification_needed": sum(need.clarification_needed for need in plan.needs),
        "read_incomplete": plan.read_incomplete,
        "overflow": plan.overflow,
        "planner_status": plan.planner_status,
        "planner_calls": plan.planner_calls,
        "assessor_calls": plan.assessor_calls,
        "recovery_calls": plan.recovery_calls,
        "model_relevance_used": plan.model_relevance_used,
    }


def prompt_needs(plan: TaskPlan) -> list[dict[str, str]]:
    return [
        {
            "id": need.need_id,
            "question": need.text,
            "status": "clarification_needed"
            if need.clarification_needed
            else "evidence_located"
            if need.evidence_ids
            else "not_established",
        }
        for need in plan.needs
    ]
