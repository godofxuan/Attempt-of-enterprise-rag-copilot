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
    explicit_request_subject,
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
from app.agent.task_plan import answer_task, task_summary, need_matches
from app.domain.evidence import AnswerResponse, Clarification

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
    basis: str = "bounded_coverage_not_independent_semantic_proof"


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
            "requirements": [vars(item) for item in self.requirements],
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
            RequirementDecision(
                need.need_id,
                status,
                need.evidence_ids,
                need.answer_claim_ids,
                "bound_generation_relation_not_independent_semantic_proof"
                if need.answer_relation_status is not None
                else "bounded_coverage_not_independent_semantic_proof",
            )
        )
    return tuple(decisions)


def packet_incomplete_for_publication(state, trace, sources, claims, task_mode):
    packet_incomplete = bool(
        any(o.result.truncated for o in state.open_results)
        or sum(trace.get("packet_drop_reasons", {}).values())
        or sum(trace.get("packet_truncation_reasons", {}).values())
    )
    if task_mode and trace.get("generation_wire_protocol") in {
        "selected_source_units_only",
        "grounded_answer_blocks_v1",
    }:
        # Candidate packing is not the answer's dependency set. Preserve actual
        # cited-source/required-read truncation and missing aspect guards; do not
        # call an uncited candidate's omitted tail an incomplete delivered answer.
        cited = {cid for claim in claims for cid in claim.cited_chunk_ids}
        used = [source for source in sources if source.delivered.citation_id in cited]
        used_truncated = sum(bool(source.packet_truncated) for source in used)
        packed = trace.get("packed_aspect_coverage", {})
        missing_aspect = packed.get("covered", 0) < packed.get("required", 0)
        explicit_read_truncated = any(o.result.truncated for o in state.open_results)
        packet_incomplete = bool(
            used_truncated
            or missing_aspect
            or explicit_read_truncated
            or (state.analysis.intent == "completeness" and packet_incomplete)
        )
        trace["publication_packet_coverage"] = {
            "basis": "actual_cited_sources_and_required_reads_v1",
            "cited_source_count": len(used),
            "cited_truncated_count": used_truncated,
            "missing_aspect": missing_aspect,
            "explicit_read_truncated": explicit_read_truncated,
            "blocking_incomplete": packet_incomplete,
        }
    return packet_incomplete


def publish_answer(question, state, response: AnswerResponse, sources) -> AnswerResponse:
    """Select facts first, compute all coverage on them, render the response once."""
    from app.runtime.request_context import remaining_seconds, RequestDeadlineExceeded

    if remaining_seconds() == 0:
        raise RequestDeadlineExceeded("publication cancelled or past deadline")
    terminal = state.terminal_request or {}
    clarification = None
    if terminal.get("type") == "clarify":
        clarification = Clarification.model_validate(
            {k: terminal[k] for k in ("question", "reason", "missing_need_ids", "options")}
        )
    if response.mode == "clarify":
        if clarification is None:
            raise ValueError("clarification requires a validated host terminal request")
        decision = AnswerDecision("clarify", "clarification_needed", (), (), (), ())
        return AnswerResponse(
            mode="clarify",
            answer=clarification.question,
            clarification=clarification,
            stop_reason="clarification_needed",
            trace={
                **response.trace,
                "final_mode": "clarify",
                "stop_reason": "clarification_needed",
                "answer_decision": decision.summary(),
            },
        )
    if response.mode not in {"answered", "partial"}:
        if response.mode == "not_found" and terminal:
            decision = AnswerDecision("not_found", "not_found", (), (), (), ())
            return response.model_copy(
                update={"trace": {**response.trace, "answer_decision": decision.summary()}}
            )
        return response
    claims = list(response.claims)
    task_mode = state.task_plan.mode == "task"
    notes = []
    warnings = list(response.warnings)
    trace = dict(response.trace)
    partial = response.mode == "partial" or clarification is not None
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

    from app.agent.answer_applicability import business_scope_matches

    scoped = [
        c
        for c in claims
        if business_scope_matches(state.task_plan.business_scope, c.text)
        and all(
            business_scope_matches(
                state.task_plan.business_scope, delivered_by_id[cid].text, source_context=True
            )
            for cid in c.cited_chunk_ids
        )
    ]
    trace["business_scope_dropped_claims"] = len(claims) - len(scoped)
    if len(scoped) != len(claims):
        notes.append("与已补充业务归属不符的条款未予发布。")
        partial = True
    claims = scoped
    # Navigation admission establishes access, not relevance to this question.
    if task_mode:
        need_ids = {n.need_id for n in state.task_plan.needs}
        relevant = [
            c
            for c in claims
            if c.need_refs
            and set(c.need_refs) <= need_ids
            and citation_by_claim[c.claim_id].support_kind == "exact_span"
        ]
        trace["task_unbound_claims_dropped"] = len(claims) - len(relevant)
        if len(relevant) != len(claims):
            partial = True
            notes.append("部分陈述缺少有效诉求映射或完整原文绑定，未予发布。")
        claims = relevant
    elif terminal and state.task_plan.needs:
        from app.agent.question_parts import claim_is_relevant

        relevant = [c for c in claims if claim_is_relevant(question, c.text)]
        trace["task_irrelevant_claims_dropped"] = len(claims) - len(relevant)
        if len(relevant) != len(claims):
            partial = True
            notes.append("无法确认回答所问诉求的条款未予发布。")
        claims = relevant
    blocked_all |= not claims

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
                or any(
                    n.kind in {"explicit", "domain"}
                    and need_matches(n, question, [claim.text])
                    and (
                        not explicit_request_subject(question)
                        or explicit_request_subject(question) in claim.text
                    )
                    for n in state.task_plan.needs
                )
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
    packet_incomplete = packet_incomplete_for_publication(state, trace, sources, claims, task_mode)
    if not task_mode and requested_needs(question):
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
    if not task_mode and parts.requested:
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
    if (
        not task_mode
        and state.analysis.intent == "completeness"
        and (requested is not None or (exhaustive and not requested_needs(question)))
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
    if "generation_need_relations" in trace:
        from app.agent.task_plan import apply_need_evaluations

        task = apply_need_evaluations(task, question, claims, trace["generation_need_relations"])
        trace["need_relation_authority"] = (
            "BOUND_GENERATION_PROPOSAL_RECHECKED_AFTER_FINAL_CLAIM_SELECTION"
        )
    draft = trace.get("generation_draft_units")
    if draft is not None:
        from app.agent.generation_v2 import _claim_binding

        current = {c.claim_id: _claim_binding(c) for c in claims}
        valid = (
            draft.get("version") == "exact-draft-units-v1"
            and draft.get("question_sha256") == hashlib.sha256(question.encode("utf8")).hexdigest()
        )
        missing_content = [
            row["unit_sha256"]
            for row in draft.get("required_content", [])
            if not valid
            or not set(row.get("claim_bindings", {})).intersection(
                cid
                for cid, fingerprint in current.items()
                if fingerprint == row.get("claim_bindings", {}).get(cid)
            )
        ]
        lost = bool(not valid or missing_content or draft.get("unresolved_unit_sha256"))
        trace["draft_delivery_binding"] = {
            "valid_request_binding": valid,
            "missing_content": missing_content,
            "unresolved_units": len(draft.get("unresolved_unit_sha256", [])),
            "restored_claim_ids": draft.get("restored_claim_ids", []),
            "complete": not lost,
            "basis": "exact_source_backed_draft_units_rechecked_on_final_published_claims",
        }
        if lost:
            partial = True
            notes.append("模型候选中的来源条款未完整交付，尚不能确认原问题已完整回答。")
            task = task.model_copy(
                update={
                    "needs": tuple(
                        n.model_copy(update={"answer_claim_ids": ()}) for n in task.needs
                    )
                }
            )
    trace["task_coverage"] = task_summary(task)
    if task_mode:
        # Public labels come from user-owned origins, never retrieved/model prose.
        trace["task_requirements"] = [
            {
                "need_id": n.need_id,
                "request_quote": (" / ".join(o.quote for o in n.origins) or n.text)[:600],
                "status": "supported_and_stated"
                if n.answer_claim_ids
                else "needs_user"
                if n.clarification_needed
                else "unresolved",
                "claim_ids": list(n.answer_claim_ids),
            }
            for n in task.needs
        ]
    if task.overflow:
        partial = True
        notes.append("问题诉求超过本次处理范围，请缩小问题范围；当前回答未覆盖全部诉求。")
    unresolved = set(terminal.get("unresolved_need_ids", []))
    if unresolved:
        partial = True
        notes.extend(
            f"当前回答尚未核验这一问题：{(' / '.join(o.quote for o in n.origins) or n.text)[:200]}。"
            for n in task.needs
            if n.need_id in unresolved
        )
    if terminal.get("type") == "abstain":
        partial = True
        notes.append("当前仅保留已核验事实，尚无更多可用证据完成该问题。")
    if clarification is not None:
        notes.append(clarification.question)
    if task.model_relevance_used:
        partial = True
        notes.append(
            "以下包含按问题关联到的相关资料，尚不足以完整确认该问题，请结合原文核对适用条件。"
        )
    missing = [
        n
        for n in task.needs
        if (
            n.kind in {"explicit", "model"}
            or terminal
            or "generation_need_relations" in trace
            or (n.domain_key or "").startswith(("device_", "business_amount:"))
        )
        and not n.answer_claim_ids
    ]
    incomplete = (task.read_incomplete or (packet_incomplete if task_mode else False)) and (
        task_mode or state.analysis.intent == "process" or len(task.needs) > 1
    )
    if task_mode and (not task.needs or any(n.model_assessment == "conflict" for n in task.needs)):
        partial = True
        notes.append("任务需求或证据适用范围仍有未解决的问题，不能确认已完整回答。")
    if missing or incomplete:
        partial = True
        # Explain every known missing obligation, even when a prior policy had
        # already required partial; identical diagnostics are rendered once.
        notes.extend(
            f"当前回答尚未核验这一问题：{(' / '.join(o.quote for o in n.origins) if task_mode and n.origins else n.text)[:200]}。"
            for n in missing
        )
        if incomplete:
            notes.append("相关章节存在未完整读取的内容，尚不能确认流程或多项问题已全部覆盖。")
    notes = list(dict.fromkeys(notes))
    from app.agent.answer_blocks import retained_blocks

    blocks, block_errors = retained_blocks(response.answer_blocks, claims, question)
    trace["answer_expression"] = {
        "basis": "model_expression_with_exact_provenance_and_finite_consistency_not_entailment",
        "retained": len(blocks),
        "rejected": block_errors,
    }
    if block_errors:
        partial = True
        notes.append("部分解释与当前保留的依据不一致，未予发布；下方保留可核验原文。")
    warnings = list(dict.fromkeys([*warnings, *notes]))
    claim_ids = {c.claim_id for c in claims}
    cited_ids = {cid for c in claims for cid in c.cited_chunk_ids}
    kept_sources = [s for s in response.sources if s.chunk_id in cited_ids]
    citations = [c for c in response.citations if c.claim_id in claim_ids]
    mode = "not_found" if blocked_all else "partial" if partial else response.mode
    reason = "not_found" if blocked_all else "partial_evidence" if partial else response.stop_reason
    if trace.get("answer_strategy") == "bounded_insufficiency" and not claims:
        mode, reason = "partial", "partial_evidence"
    if clarification is not None and not claims:
        mode, reason = "clarify", "clarification_needed"
    decision = AnswerDecision(
        mode,
        reason,
        _requirements(state, task),
        tuple(c.claim_id for c in claims),
        tuple(notes),
        tuple((s.chunk_id, s.index_run_id or "", s.version_id or "") for s in kept_sources),
    )
    trace.update(final_mode=mode, stop_reason=reason, answer_decision=decision.summary())
    expression = [
        ("在用户给定假设下（尚未查询实际个人记录）：" if block.kind == "conditional" else "")
        + block.text
        for block in blocks
    ]
    basis = [c.text for c in claims if c.text not in expression]
    answer = "\n".join(
        dict.fromkeys(
            [*expression, *(["依据与适用条件："] if expression and basis else []), *basis, *notes]
        )
    )
    if not answer:
        answer = (
            "当前可访问的资料尚未提供所问内容的充分依据。"
            if re.search(r"[\u4e00-\u9fff]", question)
            else "No supported answer was found in the visible knowledge base."
        )
    return AnswerResponse(
        mode=mode,
        stop_reason=reason,
        answer=answer,
        claims=claims,
        answer_blocks=blocks,
        citations=citations,
        sources=kept_sources,
        warnings=warnings,
        trace=trace,
        clarification=clarification,
    )
