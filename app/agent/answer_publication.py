"""One publication decision for generated answers; policies supply diagnostics.

This is a finite contract, not semantic entailment. Only admitted and actually
delivered evidence may bind the statements selected for publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from app.agent.answer_applicability import assess_answer_applicability
from app.agent.answer_contract import (
    answer_sufficiency,
    bounded_answer_slots,
    complementary_explicit_claim,
    requested_requirement_count,
    requirement_units,
)
from app.agent.query_needs import (
    NEED_LABELS,
    assess_need_coverage,
    complementary_claim,
    requested_needs,
)
from app.agent.question_parts import assess_question_parts
from app.agent.task_plan import answer_task, task_summary
from app.domain.evidence import AnswerResponse

RequirementStatus = Literal[
    "not_retrieved",
    "retrieved_but_not_delivered",
    "evidence_insufficient",
    "supported_and_stated",
    "conflicted",
]
STATUSES = (
    "not_retrieved",
    "retrieved_but_not_delivered",
    "evidence_insufficient",
    "supported_and_stated",
    "conflicted",
)


@dataclass(frozen=True)
class RequirementDecision:
    need_id: str
    status: RequirementStatus
    delivered_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class AnswerDecision:
    final_mode: str
    stop_reason: str | None
    requirements: tuple[RequirementDecision, ...]
    claim_ids: tuple[str, ...]
    notes: tuple[str, ...]
    source_bindings: tuple[tuple[str, str, str], ...]

    def summary(self) -> dict:
        counts = Counter(item.status for item in self.requirements)
        binding = {
            "claims": self.claim_ids,
            "sources": self.source_bindings,
            "requirements": [vars(item) for item in self.requirements],
        }
        return {
            "version": "answer-publication-v1",
            "publication_count": 1,
            "final_mode": self.final_mode,
            "stop_reason": self.stop_reason,
            "requirement_counts": {key: counts[key] for key in STATUSES},
            "claim_count": len(self.claim_ids),
            "source_count": len(self.source_bindings),
            "binding_sha256": hashlib.sha256(
                json.dumps(binding, sort_keys=True).encode()
            ).hexdigest(),
            "basis": "bounded_policies_and_verified_citations_not_semantic_proof",
        }


def _requirements(state, task) -> tuple[RequirementDecision, ...]:
    retrieved = {need.need_id: need for need in state.task_plan.needs}
    conflicted = bool(state.ledger and state.ledger.conflicting_aspects)
    decisions = []
    for need in task.needs:
        previous = retrieved[need.need_id]
        status = (
            "conflicted"
            if conflicted
            else "supported_and_stated"
            if need.answer_claim_ids
            else "evidence_insufficient"
            if need.evidence_ids or need.clarification_needed
            else "retrieved_but_not_delivered"
            if previous.evidence_ids
            else "not_retrieved"
        )
        decisions.append(
            RequirementDecision(need.need_id, status, need.evidence_ids, need.answer_claim_ids)
        )
    return tuple(decisions)


def publish_answer(question, state, response: AnswerResponse, sources) -> AnswerResponse:
    """Select facts first, compute all coverage on them, render the response once."""
    if response.mode not in {"answered", "partial"}:
        return response
    claims = list(response.claims)
    notes = []
    warnings = list(response.warnings)
    trace = dict(response.trace)
    partial = response.mode == "partial"
    blocked_all = False
    delivered_by_id = {s.delivered.citation_id: s.delivered for s in sources}
    citation_by_claim = {c.claim_id: c for c in response.citations}
    public_sources = {s.chunk_id: s for s in response.sources}

    def bound(claim):
        citation = citation_by_claim.get(claim.claim_id)
        if (
            not citation
            or not citation.supported
            or not claim.cited_chunk_ids
            or set(citation.cited_chunk_ids) != set(claim.cited_chunk_ids)
        ):
            return False
        for cid in claim.cited_chunk_ids:
            view, public = delivered_by_id.get(cid), public_sources.get(cid)
            if view is None or public is None:
                return False
            hit = view.anchor.hit
            if (public.doc_id, public.index_run_id, public.version_id) != (
                hit.doc_id,
                hit.index_run_id,
                hit.version_id,
            ):
                return False
        return True

    claims = [claim for claim in claims if bound(claim)]
    binding_dropped = len(response.claims) - len(claims)
    trace["delivery_binding_dropped_claims"] = binding_dropped
    if binding_dropped:
        partial = True
        blocked_all = not claims
        notes.append("部分断言无法绑定本次实际交付的有效来源，未予发布。")

    # Applicability is a selection policy, not a later response override. This
    # prevents coverage computed from discarded facts surviving publication.
    applicability = assess_answer_applicability(question, response)
    if applicability is not None:
        trace["query_applicability"] = applicability.audit
        claims = [c for c in claims if c.claim_id in applicability.claim_ids]
        notes.extend(applicability.notes)
        partial |= bool(applicability.notes)
        blocked_all = not claims

    slots = bounded_answer_slots(question, [c.text for c in claims])
    if slots.requested:
        retained = sorted(
            set(slots.retained)
            | {
                i
                for i, claim in enumerate(claims)
                if complementary_claim(question, claim.text)
                or complementary_explicit_claim(question, claim.text)
            }
        )
        trace.update(
            {
                "requested_answer_aspect_count": len(slots.requested),
                "answered_aspect_count": len(slots.satisfied),
                "missing_answer_aspect_count": len(slots.missing),
                "answer_coverage_basis": "bounded_answer_slots_v1",
                "retrieval_coverage_basis": "query_anchor_relevance_not_semantic_proof",
                "answer_sufficiency": answer_sufficiency(
                    question, [claims[i].text for i in slots.retained]
                ),
            }
        )
        claims = [claims[i] for i in retained]
        blocked_all |= not claims
        english = not re.search(r"[\u4e00-\u9fff]", question)
        for slot in slots.missing:
            label = {"duration": "天数", "approver": "审批人"}[slot]
            notes.append(
                f"The verified answer has not yet determined the requested {slot}."
                if english
                else f"当前已核验的回答尚未确定所问的{label}。"
            )
        if slots.conditional:
            notes.append(
                "The applicable condition is not yet determined."
                if english
                else "当前适用条件尚未确定，无法确定应使用哪一分支。"
            )
        partial |= bool(slots.missing)

    texts = [c.text for c in claims]
    delivered = [source.delivered for source in sources]
    packet_incomplete = bool(
        any(o.result.truncated for o in state.open_results)
        or sum(trace.get("packet_drop_reasons", {}).values())
        or sum(trace.get("packet_truncation_reasons", {}).values())
    )
    if requested_needs(question):
        read_ids = {h.hit.chunk_id for hits in state.evidence_by_aspect.values() for h in hits}
        read_ids.update(o.result.target_id for o in state.open_results)
        incomplete = bool(
            packet_incomplete
            or any(match.match.chunk_id not in read_ids for match in state.find_results)
            or (state.focused_find_doc_id is not None and len(state.find_results) >= 20)
        )
        coverage = assess_need_coverage(
            question, texts, [s.text for s in delivered], incomplete_read=incomplete
        )
        notes.extend(f"当前回答尚未完整覆盖所问的{NEED_LABELS[n]}。" for n in coverage.missing)
        if "eligibility" in coverage.missing:
            notes.append("请补充费用类型、金额和实际适用条件，不能仅凭制度摘录确定本次是否可报销。")
        if incomplete:
            notes.append("部分证据因读取或上下文预算未完整交付，无法确认要求已全部覆盖。")
        trace["query_need_coverage"] = {
            "basis": "bounded_reimbursement_statements_v2_not_global_completeness",
            "requested": len(coverage.requested),
            "covered": len(coverage.requested) - len(coverage.missing),
            "missing": len(coverage.missing),
            "incomplete_read": incomplete,
        }
        partial |= bool(coverage.missing or incomplete)

    parts = assess_question_parts(question, texts)
    if parts.requested:
        trace["question_part_coverage"] = {
            "basis": "explicit_clause_necessary_checks_not_semantic_proof",
            "requested": len(parts.requested),
            "missing": len(parts.missing),
            "overflow": parts.overflow,
        }
        notes.extend(f"当前回答尚未核验这一问题：{part[:200]}。" for part in parts.missing)
        if parts.overflow:
            notes.append("问题包含的诉求超过本次有限校验范围，尚不能确认已全部回答。")
        partial |= bool(parts.missing or parts.overflow)

    requested = requested_requirement_count(question)
    exhaustive = bool(re.search(r"全部|所有|\ball\b", question, re.I))
    if state.analysis.intent == "completeness" and (
        requested is not None or (exhaustive and not requested_needs(question))
    ):
        available = requirement_units([s.text for s in delivered])
        stated = requirement_units(texts)
        covered = len(available & stated)
        trace["requirement_list_coverage"] = {
            "basis": "explicit_list_and_delivered_units_not_global_semantics",
            "requested": requested,
            "available_units": len(available),
            "verified_units": covered,
            "incomplete_read": packet_incomplete,
        }
        if not (covered >= (requested or 1) and available <= stated and not packet_incomplete):
            partial = True
            notes.append(
                f"当前可核验的完整条款为{covered}项，尚未完整核验所问的{requested}项要求。"
                if requested is not None
                else "当前读取或回答尚未完整覆盖要求，无法确认已列出所有条款。"
            )

    task = answer_task(state.task_plan, question, claims, delivered)
    trace["task_coverage"] = task_summary(task)
    if task.model_relevance_used:
        partial = True
        notes.append(
            "以下包含按问题关联到的相关资料，尚不足以完整确认该问题，请结合原文核对适用条件。"
        )
    missing = [n for n in task.needs if n.kind in {"explicit", "model"} and not n.answer_claim_ids]
    incomplete = task.read_incomplete and (
        state.analysis.intent == "process" or len(task.needs) > 1
    )
    if missing or incomplete:
        partial = True
        # Explain every known missing obligation, even when a prior policy had
        # already required partial; identical diagnostics are rendered once.
        notes.extend(f"当前回答尚未核验这一问题：{n.text[:200]}。" for n in missing)
        if incomplete:
            notes.append("相关章节存在未完整读取的内容，尚不能确认流程或多项问题已全部覆盖。")
    notes = list(dict.fromkeys(notes))
    warnings = list(dict.fromkeys([*warnings, *notes]))
    claim_ids = {c.claim_id for c in claims}
    cited_ids = {cid for c in claims for cid in c.cited_chunk_ids}
    kept_sources = [s for s in response.sources if s.chunk_id in cited_ids]
    citations = [c for c in response.citations if c.claim_id in claim_ids]
    mode = "not_found" if blocked_all else "partial" if partial else response.mode
    reason = "not_found" if blocked_all else "partial_evidence" if partial else response.stop_reason
    decision = AnswerDecision(
        mode,
        reason,
        _requirements(state, task),
        tuple(c.claim_id for c in claims),
        tuple(notes),
        tuple((s.chunk_id, s.index_run_id or "", s.version_id or "") for s in kept_sources),
    )
    trace.update(final_mode=mode, stop_reason=reason, answer_decision=decision.summary())
    answer = "\n".join([*(c.text for c in claims), *notes])
    if not answer:
        answer = "No supported answer was found in the visible knowledge base."
    return AnswerResponse(
        mode=mode,
        stop_reason=reason,
        answer=answer,
        claims=claims,
        citations=citations,
        sources=kept_sources,
        warnings=warnings,
        trace=trace,
    )
