"""Shared, request-local obligations; relevance is never an entailment proof."""

from __future__ import annotations

from typing import Literal
import re
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.query_needs import NEED_LABELS, assess_need_coverage, requested_needs
from app.agent.question_parts import explicit_question_parts, part_is_addressed
from app.domain.evidence import Claim
from app.domain.evidence_packet import DeliveredEvidence
from app.domain.queries import QueryAnalysis


class NeedOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_ref: Literal["Q0", "R1", "R2"]
    quote: str = Field(min_length=1, max_length=600)
    start: int = Field(ge=0)
    end: int = Field(ge=1)


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
    answer_relation_status: Literal['supported','unknown','evidence_insufficient'] | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=1)
    origins: tuple[NeedOrigin, ...] = ()
    semantic_kind: Literal["answer", "materials", "process", "limit", "exception", "comparison", "other"] = "other"
    model_assessment: Literal["unknown", "candidate", "needs_read", "needs_user", "conflict", "supported_proposal"] = "unknown"


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
    model_added_needs: int = Field(default=0, ge=0, le=4)
    business_scope: str | None = None
    mode: Literal["legacy", "task"] = "legacy"

    @model_validator(mode="after")
    def validate_need_ids(self):
        if [need.need_id for need in self.needs] != [
            f"N{i}" for i in range(1, len(self.needs) + 1)
        ]:
            raise ValueError("task needs must have stable ordered unique IDs")
        return self


class NeedEvaluation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    need_id: str = Field(pattern=r'^N[1-8]$')
    claim_ids: list[str] = Field(max_length=20)
    status: Literal['supported','unknown','evidence_insufficient']
    subject_matches: bool
    attribute_matches: bool
    conditions_preserved: bool


def _identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def bind_need_evaluations(plan, question, claims, rows):
    """Bind one generation's provisional semantic links; never create source support."""
    evaluations=[NeedEvaluation.model_validate(row) for row in rows]
    need_ids={n.need_id for n in plan.needs}
    if len({r.need_id for r in evaluations})!=len(evaluations) or any(r.need_id not in need_ids for r in evaluations):
        raise ValueError('UNKNOWN_OR_DUPLICATE_ORIGINAL_NEED')
    originals={c.claim_id:_identity(c.model_dump(mode='json')) for c in claims}
    if any(cid not in originals for row in evaluations for cid in row.claim_ids):
        raise ValueError('UNKNOWN_COVERAGE_CLAIM')
    return {'version':'generation-need-relations-v1','question_sha256':_identity(question),
        'needs_sha256':_identity([(n.need_id,n.text,n.kind) for n in plan.needs]),
        'claim_bindings':originals,'evaluations':[row.model_dump() for row in evaluations],
        'authority':'MODEL_PROVISIONAL_WITH_HOST_IDENTITY_CHECKS_NOT_INDEPENDENT_TRUTH'}


def apply_need_evaluations(plan, question, claims, bound):
    current={c.claim_id:_identity(c.model_dump(mode='json')) for c in claims}
    valid=(bound.get('version')=='generation-need-relations-v1'
        and bound.get('question_sha256')==_identity(question)
        and bound.get('needs_sha256')==_identity([(n.need_id,n.text,n.kind) for n in plan.needs]))
    try:
        evaluations=[NeedEvaluation.model_validate(row) for row in bound.get('evaluations',[])]
        rows={r.need_id:r for r in evaluations}
        valid=valid and len(rows)==len(evaluations) and set(rows).issubset({n.need_id for n in plan.needs})
    except ValueError:
        rows={};valid=False
    needs=[]
    for need in plan.needs:
        row=rows.get(need.need_id)
        supported=bool(valid and row and row.status=='supported' and row.claim_ids
            and row.subject_matches and row.attribute_matches and row.conditions_preserved
            and all(cid in current and current[cid]==bound.get('claim_bindings',{}).get(cid) for cid in row.claim_ids))
        needs.append(need.model_copy(update={'answer_claim_ids':tuple(row.claim_ids) if supported else (),
            'answer_relation_status':'supported' if supported else 'unknown'}))
    return plan.model_copy(update={'needs':tuple(needs)})


def build_task_plan(analysis: QueryAnalysis) -> TaskPlan:
    if analysis.intent == "unsafe":
        return TaskPlan()
    # Default knowledge need is the whole original user obligation, never a
    # punctuation-derived subset or a domain-keyword expansion.
    return TaskPlan(needs=(RequestNeed(need_id="N1", text=analysis.original_question,
                                      kind="whole"),))


def need_matches(need: RequestNeed, question: str, texts: list[str]) -> bool:
    if need.clarification_needed:
        return False
    if need.kind == "whole":
        return part_is_addressed(question,texts)
    if need.kind == "domain":
        key=need.domain_key or ""
        if key.startswith("business_amount:"):
            scope=key.split(":",1)[1]
            return bool(scope) and any(scope+"业务" in t and re.search(r"\d+(?:\.\d+)?元",t) for t in texts)
        if key.startswith("device_"):
            patterns={"device_owner":r"(?:交|由).{1,20}(?:管理员|负责人).{0,8}(?:受理|申请)",
                      "device_materials":r"(?:代用机|维修).*(?:需要|需|工单)",
                      "device_supplier":r"供应商.*(?:需要|还需|除).*(?:记录|确认书|材料)"}
            return any(re.search(patterns[key],t) for t in texts)
        return need.domain_key not in assess_need_coverage(question, texts, texts).missing
    return part_is_addressed(need.text, texts, context=question)


def bind_business_scope(plan: TaskPlan, question: str, replies: list[dict]) -> TaskPlan:
    from app.agent.answer_applicability import business_scope
    scope=business_scope(question,replies)
    if scope is None:
        return plan
    return plan.model_copy(update={"business_scope":scope,"needs":tuple(
        n.model_copy(update={"domain_key":"business_amount:"+scope,"clarification_needed":False})
        if n.domain_key=="business_amount:" else n for n in plan.needs)})


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
                            if (view.citation_id in need.evidence_ids if plan.mode == "task"
                                else need_matches(need, question, [view.text]))
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
    if plan.mode == "task":
        visible = {view.citation_id for view in evidence}
        # The generator's mapping is semantic advice. Only citation-verified,
        # actually delivered claims reach this shared publication reducer.
        delivered = delivered.model_copy(update={"needs": tuple(n.model_copy(update={
            "evidence_ids": tuple(dict.fromkeys(cid for c in claims if n.need_id in c.need_refs
                                               for cid in c.cited_chunk_ids if cid in visible))})
            for n in delivered.needs)})
    return delivered.model_copy(
        update={
            "needs": tuple(
                need.model_copy(
                    update={
                        "answer_claim_ids": tuple(
                            claim.claim_id
                            for claim in claims
                            if (need.need_id in claim.need_refs if plan.mode == "task"
                                else need_matches(need, question, [claim.text]))
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
        "basis": ("model_association_and_actual_quote_binding_not_semantic_proof"
                  if plan.mode == "task" else "shared_needs_necessary_checks_not_semantic_proof"),
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
