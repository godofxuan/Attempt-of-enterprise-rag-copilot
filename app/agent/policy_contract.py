"""Strict model proposals; validation here does not grant tool authority."""
from __future__ import annotations

from typing import Annotated, Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


ShortRef = Annotated[str, Field(min_length=1, max_length=80)]
ALL_ACTIONS = frozenset({"search", "find", "open", "clarify", "finish", "abstain"})


class SearchAction(StrictProposal):
    type: Literal["search"]
    query: str = Field(min_length=1, max_length=300)
    query_mode: Literal["refine_original", "need_specific"]


class ClarifyAction(StrictProposal):
    type: Literal["clarify"]
    question: str = Field(min_length=1, max_length=300)
    missing_need_ids: list[ShortRef] = Field(min_length=1, max_length=8)
    reason: Literal["missing_user_fact", "ambiguous_scope"]
    options: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=4)


class AbstainAction(StrictProposal):
    type: Literal["abstain"]
    reason: Literal["no_accessible_evidence", "no_recoverable_evidence"]


class FindAction(StrictProposal):
    type: Literal["find"]
    document_ref: ShortRef
    pattern: str = Field(min_length=1, max_length=120)
    section_ref: ShortRef | None = None


class OpenAction(StrictProposal):
    type: Literal["open"]
    window_ref: ShortRef


class FinishAction(StrictProposal):
    type: Literal["finish"]
    requested_outcome: Literal["complete", "partial"]
    unresolved_need_ids: list[ShortRef] = Field(max_length=8)

    @model_validator(mode="after")
    def complete_has_no_declared_gaps(self):
        if self.requested_outcome == "complete" and self.unresolved_need_ids:
            raise ValueError("complete request cannot declare unresolved needs")
        return self


class NeedAddition(StrictProposal):
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=1)
    source_span: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=180)


class ActionProposal(StrictProposal):
    schema_version: Literal["2"]
    target_need_ids: list[ShortRef] = Field(min_length=1, max_length=8)
    based_on_observation_ids: list[ShortRef] = Field(min_length=1, max_length=8)
    evidence_refs: list[ShortRef] = Field(max_length=8)
    reason_code: Literal[
        "missing_document_evidence", "unread_relevant_window", "ambiguous_user_fact",
        "scope_conflict", "retryable_tool_error", "evidence_ready", "no_recoverable_evidence",
    ]
    add_needs: list[NeedAddition] = Field(max_length=4)
    action: Annotated[SearchAction | FindAction | OpenAction | ClarifyAction | FinishAction | AbstainAction, Field(discriminator="type")]

    @field_validator("target_need_ids", "based_on_observation_ids", "evidence_refs")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate IDs")
        return value


def validate_proposal(raw, *, allowed_actions=ALL_ACTIONS):
    if isinstance(raw, ActionProposal):
        raw = raw.model_dump()
    value = ActionProposal.model_validate(raw)
    if value.action.type not in allowed_actions:
        raise ValueError("action not available in this phase")
    return value


def normalized_action_text(text):
    return re.sub(r"[\W_]+", "", text.casefold())


def validate_rewrite(original, query, *, mode, need_texts):
    """Necessary lexical/relational protection, not a semantic-equivalence proof."""
    from app.agent.task_advisor import _rewrite_constraints

    def constraints(text):
        return {"upper_bound" if t == "最多" else t for t in _rewrite_constraints(text.replace("上限","最多"))}
    if not query.strip() or not constraints(original) <= constraints(query):
        raise ValueError("protected constraint changed")
    normalized = normalized_action_text(query)
    # Keep each numeric/negative predicate with its object, not just token sets.
    clauses = re.split(r"[，,；;。！？?、\n]", original)
    for clause in clauses:
        if re.search(r"\d|不得|不能|无需|无须|未|不|\bnot\b|\bwithout\b", clause, re.I):
            if normalized_action_text(clause) not in normalized:
                raise ValueError("protected predicate changed")
    scopes = re.findall(r"上海|北京|总部|分部|分公司|承包商|正式员工|实习生|《[^》]+》|[A-Za-z]+[-_]\w+", original)
    if any(normalized_action_text(scope) not in normalized for scope in scopes):
        raise ValueError("global applicability changed")
    if mode == "need_specific":
        if not need_texts or not any(normalized_action_text(t) in normalized for t in need_texts):
            raise ValueError("target need lost")
    elif mode != "refine_original":
        raise ValueError("unknown query mode")
    return query


class OriginProposal(StrictProposal):
    source_ref: Literal["Q0", "R1", "R2"]
    quote: str = Field(min_length=1, max_length=600)


class SemanticNeed(StrictProposal):
    local_ref: str = Field(pattern=r"^p[1-8]$")
    label: str = Field(min_length=1, max_length=180)
    kind: Literal["answer", "materials", "process", "limit", "exception", "comparison", "other"]
    origins: list[OriginProposal] = Field(min_length=1, max_length=3)


class NeedEvidenceLink(StrictProposal):
    need_ref: ShortRef
    evidence_ref: ShortRef
    relation: Literal["candidate", "needs_read", "scope_uncertain", "supports_proposal"]


class TaskClarifyAction(StrictProposal):
    type: Literal["clarify"]
    question: str = Field(min_length=1, max_length=300)
    missing_need_refs: list[ShortRef] = Field(min_length=1, max_length=8)
    reason: Literal["missing_user_fact", "ambiguous_scope"]
    options: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=4)


class TaskFinishAction(StrictProposal):
    type: Literal["finish"]
    requested_outcome: Literal["complete", "partial"]
    unresolved_need_refs: list[ShortRef] = Field(max_length=8)


class TaskProposal(StrictProposal):
    schema_version: Literal["task.v1"]
    phase: Literal["initialize", "continue"]
    new_needs: list[SemanticNeed] = Field(max_length=8)
    has_unrepresented_requirements: bool
    target_need_refs: list[ShortRef] = Field(min_length=1, max_length=8)
    based_on_observation_ids: list[ShortRef] = Field(min_length=1, max_length=4)
    need_evidence_links: list[NeedEvidenceLink] = Field(max_length=8)
    reason_code: Literal["initial_investigation", "missing_evidence", "unread_unit",
                         "missing_user_fact", "conflicting_scope", "retryable_error",
                         "evidence_ready", "no_useful_progress"]
    action: Annotated[SearchAction | FindAction | OpenAction | TaskClarifyAction |
                      TaskFinishAction | AbstainAction, Field(discriminator="type")]

    @model_validator(mode="after")
    def phase_shape(self):
        for values in (self.target_need_refs, self.based_on_observation_ids,
                       [n.local_ref for n in self.new_needs]):
            if len(values) != len(set(values)):
                raise ValueError("duplicate references")
        if self.phase == "initialize":
            if (not self.new_needs or self.need_evidence_links
                or self.based_on_observation_ids != ["I0"]
                or self.action.type not in {"search", "clarify", "abstain"}):
                raise ValueError("invalid initialization")
        elif len(self.new_needs) > 4:
            raise ValueError("continuation need capacity")
        return self


class TaskNeedCapacityExceeded(ValueError):
    """No partial plan is committed, but completeness can no longer be claimed."""


def stage_task_proposal(raw, *, plan, user_sources, observations, evidence_refs, allowed_actions):
    """Return a detached plan and host-ID action. Caller commits only after resolution.

    evidence_refs contains only host issued refs mapped to actually admitted citation
    IDs. A model association is retained as a proposal, never an entailment verdict.
    """
    from app.agent.task_plan import NeedOrigin, RequestNeed, TaskPlan

    proposal = TaskProposal.model_validate(raw.model_dump() if isinstance(raw, TaskProposal) else raw)
    if plan.mode != "task" or proposal.phase != ("continue" if plan.needs else "initialize"):
        raise ValueError("phase does not match host state")
    if proposal.action.type not in allowed_actions:
        raise ValueError("action unavailable")
    if (not set(proposal.based_on_observation_ids) <= set(observations)
        or observations[-1] not in proposal.based_on_observation_ids):
        raise ValueError("unknown or stale observation")
    if len(plan.needs) + len(proposal.new_needs) > 8:
        raise TaskNeedCapacityExceeded("need capacity exceeded")
    mapping = {n.need_id: n.need_id for n in plan.needs}
    needs = list(plan.needs)
    for item in proposal.new_needs:
        origins = []
        for origin in item.origins:
            source = user_sources.get(origin.source_ref)
            start = source.find(origin.quote) if source is not None else -1
            if start < 0 or source.find(origin.quote, start + 1) >= 0:
                raise ValueError("need origin not uniquely bound")
            bound = NeedOrigin(source_ref=origin.source_ref, quote=origin.quote,
                               start=start, end=start+len(origin.quote))
            if bound in origins:
                raise ValueError("duplicate origin")
            origins.append(bound)
        if any(n.text == item.label and n.origins == tuple(origins) for n in needs):
            raise ValueError("duplicate need")
        nid = f"N{len(needs)+1}"
        mapping[item.local_ref] = nid
        needs.append(RequestNeed(need_id=nid, text=item.label, kind="model",
                                 semantic_kind=item.kind, origins=tuple(origins)))

    def resolve(refs):
        if len(refs) != len(set(refs)) or any(ref not in mapping for ref in refs):
            raise ValueError("unknown or duplicate need reference")
        return [mapping[ref] for ref in refs]

    targets = resolve(proposal.target_need_refs)
    for link in proposal.need_evidence_links:
        nid = resolve([link.need_ref])[0]
        if link.evidence_ref not in evidence_refs:
            raise ValueError("unknown evidence reference")
        position = next(i for i,n in enumerate(needs) if n.need_id == nid)
        need = needs[position]
        ids = evidence_refs[link.evidence_ref]
        status = {"candidate":"candidate", "needs_read":"needs_read",
                  "scope_uncertain":"conflict", "supports_proposal":"supported_proposal"}[link.relation]
        needs[position] = need.model_copy(update={"model_assessment": status,
            "evidence_ids": tuple(dict.fromkeys((*need.evidence_ids, *ids)))
                if link.relation == "supports_proposal" else need.evidence_ids})
    action = proposal.action.model_dump()
    if action["type"] == "clarify":
        action["missing_need_ids"] = resolve(action.pop("missing_need_refs"))
        if not set(action["missing_need_ids"]) <= set(targets):
            raise ValueError("clarification outside targeted needs")
        needs = [n.model_copy(update={"clarification_needed": True, "model_assessment": "needs_user"})
                 if n.need_id in action["missing_need_ids"] else n for n in needs]
    if action["type"] == "finish":
        action["unresolved_need_ids"] = resolve(action.pop("unresolved_need_refs"))
    reason = {"initial_investigation":"missing_document_evidence", "missing_evidence":"missing_document_evidence",
              "unread_unit":"unread_relevant_window", "missing_user_fact":"ambiguous_user_fact",
              "conflicting_scope":"scope_conflict", "retryable_error":"retryable_tool_error",
              "evidence_ready":"evidence_ready", "no_useful_progress":"no_recoverable_evidence"}[proposal.reason_code]
    parsed = validate_proposal(dict(schema_version="2", target_need_ids=targets,
        based_on_observation_ids=proposal.based_on_observation_ids, evidence_refs=[],
        reason_code=reason, add_needs=[], action=action), allowed_actions=allowed_actions)
    staged = TaskPlan.model_validate({**plan.model_dump(), "needs": needs, "planner_status":"accepted",
        "planner_calls": 1, "overflow":plan.overflow or proposal.has_unrepresented_requirements})
    return staged, parsed


def task_search_query(original, query, *, mode, needs, replies):
    """Use a constrained proposal or original user clauses; never rewrite authority."""
    context = "\n".join([original, *replies])
    try:
        # Targeting is a semantic proposal. The full protected context, not just
        # the need label, still controls numerical/negative/applicability checks.
        return validate_rewrite(context, query, mode="refine_original", need_texts=[])
    except ValueError:
        parts = [o.quote for n in needs for o in n.origins]
        from app.agent.task_advisor import _rewrite_constraints
        parts += [c for c in re.split(r"[，,；;。！？?\n]", context) if _rewrite_constraints(c)]
        fallback = " ".join(dict.fromkeys(parts))
        # A targeted fallback must retain all global constraints as well.
        try:
            return validate_rewrite(context, fallback, mode="refine_original", need_texts=[])
        except ValueError:
            return context
