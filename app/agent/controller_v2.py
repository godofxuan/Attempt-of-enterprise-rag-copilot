from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.evidence_ledger import build_ledger, evidence_view, with_open_evidence
from app.agent.evidence_relevance import has_query_anchor_support
from app.agent.query_needs import material_terms, relevant_need_count, requested_needs
from app.agent.task_advisor import TaskAdvisor
from app.agent.task_plan import TaskPlan, build_task_plan, need_matches, observe_task
from app.domain.agent import (
    AgentAction,
    AgentBudget,
    AgentStopReason,
    AnswerMode,
    BudgetState,
    ToolError,
)
from app.domain.evidence import EvidenceLedger
from app.domain.queries import (
    FindRequest,
    OpenRequest,
    QueryAnalysis,
    SearchRequest,
    UserContext,
)
from app.domain.retrieved_security import (
    AdmittedEvidenceChunk,
    AdmittedFindMatch,
    AdmittedOpenResult,
    GuardedFindResult,
    GuardedOpenAdmittedResult,
    GuardedSearchResult,
    GuardedV2ToolExecution,
)

ClockMs = Callable[[], float]


class ControllerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: QueryAnalysis
    user: UserContext
    top_k: int = Field(ge=1, le=20)
    budget_state: BudgetState
    evidence_by_aspect: dict[str, list[AdmittedEvidenceChunk]] = Field(default_factory=dict)
    attempted_search_aspects: list[str] = Field(default_factory=list)
    opened_doc_ids: list[str] = Field(default_factory=list)
    open_results: list[AdmittedOpenResult] = Field(default_factory=list)
    find_results: list[AdmittedFindMatch] = Field(default_factory=list)
    focused_find_doc_id: str | None = None
    focused_open_count: int = Field(default=0, ge=0, le=2)
    denied_only_signal: bool = False
    security_filtered_signal: bool = False
    ledger: EvidenceLedger | None = None
    last_error: ToolError | None = None
    task_plan: TaskPlan = Field(default_factory=TaskPlan)
    retry_query: str | None = None
    retry_attempted: bool = False
    advice_status: str = "off"
    recovery_candidates: list[AdmittedEvidenceChunk] = Field(default_factory=list, max_length=5)


class ControllerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AgentAction
    terminal_mode: AnswerMode | None = None
    stop_reason: AgentStopReason | None = None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> ControllerDecision:
        terminal_tool = self.action.tool in {"answer", "refuse", "stop"}
        if terminal_tool != (self.terminal_mode is not None):
            raise ValueError("terminal action and terminal mode must match")
        if terminal_tool != (self.stop_reason is not None):
            raise ValueError("terminal action and stop reason must match")
        return self


class V2AgentController:
    def __init__(
        self,
        *,
        clock_ms: ClockMs | None = None,
        task_advisor: TaskAdvisor | None = None,
        recovery_advisor: TaskAdvisor | None = None,
    ) -> None:
        if task_advisor is not None and recovery_advisor is not None:
            raise ValueError("eager and gap-driven advice are mutually exclusive")
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000)
        self.task_advisor = task_advisor
        self.recovery_advisor = recovery_advisor

    def initialize(
        self,
        analysis: QueryAnalysis,
        user: UserContext,
        *,
        top_k: int | None = None,
        budget: AgentBudget | None = None,
    ) -> ControllerState:
        active_budget = budget or AgentBudget()
        now = self.clock_ms()
        state = ControllerState(
            analysis=analysis,
            task_plan=build_task_plan(analysis),
            user=user,
            top_k=top_k or 5,
            budget_state=BudgetState(
                budget=active_budget,
                deadline_at_ms=now + active_budget.deadline_ms,
            ),
        )
        if self.task_advisor and analysis.intent not in {"unsafe", "comparison"}:
            state.task_plan = self.task_advisor.plan(analysis.original_question, state.task_plan)
        return state

    def prepare_advice(self, state: ControllerState) -> ControllerState:
        """Run at most one post-read suggestion; it cannot certify an answer."""
        if self.recovery_advisor is not None:
            return self._prepare_recovery(state)
        if (
            self.task_advisor is None
            or state.task_plan.assessor_calls
            or state.analysis.intent in {"unsafe", "comparison"}
            or state.last_error
            or self._hard_budget_exhausted(state)
            or set(state.analysis.required_aspects) - set(state.attempted_search_aspects)
            or not _all_visible_hits(state.evidence_by_aspect)
            or (state.ledger and state.ledger.conflicting_aspects)
        ):
            return state
        sequence = state.budget_state.steps + 1
        if self._focused_read(state, sequence) or self._completeness_open(state, sequence):
            return state
        values = with_open_evidence(state.evidence_by_aspect, state.open_results)
        evidence = {
            evidence_view(item).citation_id: evidence_view(item)
            for items in values.values()
            for item in items
        }
        advice = self.task_advisor.assess(
            state.analysis.original_question, state.task_plan, list(evidence.values())
        )
        task = state.task_plan.model_copy(update={"assessor_calls": 1})
        retry = None
        if (
            advice.status == "accepted"
            and state.budget_state.search_calls < state.budget_state.budget.max_search_calls
        ):
            missing = {item.need_id for item in advice.assessments if item.status == "missing"}
            need = next(
                (
                    item
                    for item in task.needs
                    if item.need_id in missing
                    and not item.clarification_needed
                    and item.kind != "whole"
                ),
                None,
            )
            if need is not None:
                candidate = state.analysis.original_question + "\n" + need.text
                if len(candidate) <= 1000 and candidate not in state.analysis.search_queries:
                    retry = candidate
        return _validated_state(
            state, task_plan=task, retry_query=retry, advice_status=advice.status
        )

    def _prepare_recovery(self, state: ControllerState) -> ControllerState:
        if (
            state.task_plan.recovery_calls
            or state.retry_attempted
            or state.analysis.intent in {"unsafe", "comparison"}
            or state.last_error
            or self._hard_budget_exhausted(state)
            or state.denied_only_signal
            or state.security_filtered_signal
            or state.budget_state.search_calls >= state.budget_state.budget.max_search_calls
            or set(state.analysis.required_aspects) - set(state.attempted_search_aspects)
            or (state.ledger and state.ledger.conflicting_aspects)
        ):
            return state
        sequence = state.budget_state.steps + 1
        if self._focused_read(state, sequence) or self._completeness_open(state, sequence):
            return state
        missing = [
            need.need_id
            for need in state.task_plan.needs
            if not need.evidence_ids and not need.clarification_needed
        ]
        if not missing:
            return state
        values = with_open_evidence(state.evidence_by_aspect, state.open_results)
        views = {
            evidence_view(v).citation_id: evidence_view(v)
            for items in values.values()
            for v in items
        }
        # These are already ACL/version/Guard-admitted hits. A lexical relevance
        # rejection must not be confused with a security rejection.
        for candidate in state.recovery_candidates:
            view = evidence_view(candidate)
            views.setdefault(view.citation_id, view)
        advice = self.recovery_advisor.recover(
            state.analysis.original_question,
            state.task_plan,
            list(views.values()),
            missing_ids=missing,
        )
        retry = (
            advice.query if advice.status == "accepted" and advice.decision == "search" else None
        )
        if retry and retry.strip() in {q.strip() for q in state.analysis.search_queries}:
            retry = None
        if advice.status == "accepted" and advice.decision == "read":
            selected = next(
                (
                    h
                    for h in state.recovery_candidates
                    if h.hit.chunk_id == advice.citation_id
                    and has_query_anchor_support(
                        state.analysis.original_question, h, advisory_partial=True
                    )
                ),
                None,
            )
            if selected is not None:
                evidence = {k: list(v) for k, v in state.evidence_by_aspect.items()}
                aspect = state.analysis.required_aspects[0]
                evidence[aspect] = _merge_hits(evidence.get(aspect, []), [selected])
                task = observe_task(
                    state.task_plan,
                    state.analysis.original_question,
                    [
                        evidence_view(v)
                        for items in with_open_evidence(evidence, state.open_results).values()
                        for v in items
                    ],
                    read_incomplete=state.task_plan.read_incomplete,
                )
                return _validated_state(
                    state,
                    evidence_by_aspect=evidence,
                    ledger=build_ledger(state.analysis, evidence, open_results=state.open_results),
                    task_plan=task.model_copy(
                        update={"recovery_calls": 1, "model_relevance_used": True}
                    ),
                    advice_status="recovery_read_partial",
                )
        return _validated_state(
            state,
            task_plan=state.task_plan.model_copy(update={"recovery_calls": 1}),
            retry_query=retry,
            advice_status="recovery_" + advice.status,
        )

    def next_decision(self, state: ControllerState) -> ControllerDecision:
        sequence = state.budget_state.steps + 1
        if state.analysis.intent == "unsafe":
            return _terminal(
                sequence,
                tool="refuse",
                mode="unsafe",
                stop_reason="unsafe",
                purpose="refuse unsafe request before any tool call",
            )

        error_decision = self._decision_for_error(state, sequence)
        if error_decision is not None:
            return error_decision
        if self._hard_budget_exhausted(state):
            return self._budget_terminal(state, sequence)

        for aspect in state.analysis.required_aspects:
            if aspect in state.attempted_search_aspects:
                continue
            query = _query_for_aspect(state.analysis, aspect)
            purpose = f"collect visible evidence for required aspect: {aspect}"
            return ControllerDecision(
                action=AgentAction(
                    sequence=sequence,
                    tool="search",
                    purpose=purpose,
                    aspect=aspect,
                    search_request=SearchRequest(
                        request_id=f"agent-step-{sequence}",
                        query=query,
                        purpose=purpose,
                        user=state.user,
                        filters=state.analysis.filters,
                        top_k=state.top_k,
                        candidate_k=min(200, max(state.top_k, state.top_k * 4)),
                        mode="hybrid",
                        include_parent=True,
                    ),
                )
            )

        if state.retry_query and not state.retry_attempted:
            return ControllerDecision(
                action=AgentAction(
                    sequence=sequence,
                    tool="search",
                    purpose="bounded task-gap retry with original question preserved",
                    aspect=state.analysis.required_aspects[0],
                    search_request=SearchRequest(
                        request_id=f"agent-step-{sequence}",
                        query=state.retry_query,
                        purpose="one optional task-gap retry",
                        user=state.user,
                        filters=state.analysis.filters,
                        top_k=state.top_k,
                        candidate_k=min(200, max(state.top_k, state.top_k * 4)),
                        mode="hybrid",
                        include_parent=True,
                    ),
                )
            )
        open_decision = self._focused_read(state, sequence) or self._completeness_open(
            state, sequence
        )
        if open_decision is not None:
            return open_decision

        if state.security_filtered_signal and not _all_visible_hits(state.evidence_by_aspect):
            return _terminal(
                sequence,
                tool="stop",
                mode="security_filtered",
                stop_reason="evidence_filtered",
                purpose="stop because available evidence was filtered by safety policy",
            )

        ledger = state.ledger or build_ledger(
            state.analysis,
            state.evidence_by_aspect,
            open_results=state.open_results,
            denied_only=state.denied_only_signal
            and not _all_visible_hits(state.evidence_by_aspect),
            budget_exhausted=self._hard_budget_exhausted(state),
        )
        if ledger.conflicting_aspects:
            return _terminal(
                sequence,
                tool="answer",
                mode="partial",
                stop_reason="partial_evidence",
                purpose="return unresolved conflicting evidence without choosing a winner",
            )
        if ledger.recommended_action == "answer":
            advisory = state.task_plan.model_relevance_used
            return _terminal(
                sequence,
                tool="answer",
                mode="partial" if advisory else "answered",
                stop_reason="partial_evidence" if advisory else "completed",
                purpose="return model-suggested relevant evidence without certifying completeness"
                if advisory
                else "answer because every required aspect has visible evidence",
            )
        if ledger.recommended_action == "partial":
            return _terminal(
                sequence,
                tool="answer",
                mode="partial",
                stop_reason="partial_evidence",
                purpose="return supported evidence because the budget is exhausted",
            )
        if ledger.recommended_action == "permission":
            return _terminal(
                sequence,
                tool="stop",
                mode="permission",
                stop_reason="permission",
                purpose="stop with a generic permission outcome",
            )
        if ledger.recommended_action == "not_found":
            return _terminal(
                sequence,
                tool="stop",
                mode="not_found",
                stop_reason="not_found",
                purpose="stop because no visible evidence matched",
            )
        if ledger.recommended_action == "budget":
            return _terminal(
                sequence,
                tool="stop",
                mode="budget",
                stop_reason="budget_exhausted",
                purpose="stop because no evidence was found within the budget",
            )
        if ledger.supported_aspects:
            return _terminal(
                sequence,
                tool="answer",
                mode="partial",
                stop_reason="partial_evidence",
                purpose="return partial evidence after bounded aspect searches",
            )
        return _terminal(
            sequence,
            tool="stop",
            mode="not_found",
            stop_reason="not_found",
            purpose="stop after bounded searches found no supported aspect",
        )

    def observe(
        self,
        state: ControllerState,
        execution: GuardedV2ToolExecution,
    ) -> ControllerState:
        if not isinstance(execution, GuardedV2ToolExecution):
            raise TypeError("Controller.observe requires a guarded tool execution")
        evidence = {aspect: list(hits) for aspect, hits in state.evidence_by_aspect.items()}
        attempted = list(state.attempted_search_aspects)
        opened_doc_ids = list(state.opened_doc_ids)
        open_results = list(state.open_results)
        find_results = list(state.find_results)
        denied_signal = state.denied_only_signal
        security_filtered_signal = state.security_filtered_signal or (
            execution.security_stop_reason == "evidence_filtered"
        )
        last_error: ToolError | None = None
        focused_find_doc_id = state.focused_find_doc_id
        focused_open_count = state.focused_open_count
        recovery_candidates = list(state.recovery_candidates)
        action = execution.action
        result = execution.result

        if action.tool == "search" and action.aspect is not None:
            if action.aspect not in attempted:
                attempted.append(action.aspect)
            if isinstance(result, GuardedSearchResult):
                if self.recovery_advisor is not None and not recovery_candidates:
                    recovery_candidates = list(result.hits[:5])
                supported_hits = [
                    hit
                    for hit in result.hits
                    if has_query_anchor_support(
                        state.analysis.original_question
                        if self.recovery_advisor is not None
                        else action.search_request.query,
                        hit,
                    )
                ]
                evidence[action.aspect] = _merge_hits(
                    evidence.get(action.aspect, []),
                    supported_hits,
                )
                if not result.hits and result.internal_denied_count > 0:
                    denied_signal = True
        elif action.tool == "open" and action.open_request is not None:
            target_id = action.open_request.target_id
            if target_id not in opened_doc_ids:
                opened_doc_ids.append(target_id)
            if isinstance(result, GuardedOpenAdmittedResult):
                open_results.append(result.item)
            if action.open_request.anchor_chunk_id is not None:
                focused_open_count = min(2, focused_open_count + 1)
        elif action.tool == "find" and isinstance(result, GuardedFindResult):
            find_results.extend(result.matches)

        if action.tool == "find" and action.find_request.anchor_chunk_id is not None:
            focused_find_doc_id = action.find_request.doc_id

        if isinstance(result, ToolError):
            if not (result.code == "not_found" and action.tool in {"find", "open"}):
                last_error = result

        next_state = _validated_state(
            state,
            budget_state=execution.budget_state,
            evidence_by_aspect=evidence,
            attempted_search_aspects=attempted,
            opened_doc_ids=opened_doc_ids,
            open_results=open_results,
            find_results=find_results,
            denied_only_signal=denied_signal,
            security_filtered_signal=security_filtered_signal,
            last_error=last_error,
            focused_find_doc_id=focused_find_doc_id,
            focused_open_count=focused_open_count,
            recovery_candidates=recovery_candidates,
            retry_attempted=state.retry_attempted
            or bool(
                action.tool == "search"
                and state.retry_query
                and action.search_request.query == state.retry_query
            ),
        )
        if state.analysis.intent != "unsafe":
            ledger = build_ledger(
                state.analysis,
                evidence,
                open_results=open_results,
                denied_only=denied_signal and not _all_visible_hits(evidence),
                budget_exhausted=self._hard_budget_exhausted(next_state),
            )
            next_state = _validated_state(next_state, ledger=ledger)
            views = with_open_evidence(evidence, open_results)
            unique_views = {
                evidence_view(view).citation_id: evidence_view(view)
                for values in views.values()
                for view in values
            }
            read_ids = {hit.hit.chunk_id for hits in evidence.values() for hit in hits}
            read_ids.update(item.result.target_id for item in open_results)
            task = observe_task(
                state.task_plan,
                state.analysis.original_question,
                list(unique_views.values()),
                searched=action.tool == "search",
                read_incomplete=any(item.result.truncated for item in open_results)
                or any(item.match.chunk_id not in read_ids for item in find_results),
            )
            next_state = _validated_state(next_state, task_plan=task)
        return next_state

    def _decision_for_error(
        self,
        state: ControllerState,
        sequence: int,
    ) -> ControllerDecision | None:
        error = state.last_error
        if error is None:
            return None
        if error.code == "permission":
            return _terminal(
                sequence,
                tool="stop",
                mode="permission",
                stop_reason="permission",
                purpose="stop after a generic permission failure",
            )
        if error.code == "budget":
            return self._budget_terminal(state, sequence)
        return _terminal(
            sequence,
            tool="stop",
            mode="system",
            stop_reason="system_error",
            purpose="stop after a structured tool failure",
        )

    def _hard_budget_exhausted(self, state: ControllerState) -> bool:
        budget = state.budget_state.budget
        if state.budget_state.steps >= budget.max_steps:
            return True
        if state.budget_state.context_chars >= budget.max_context_chars:
            return True
        deadline = state.budget_state.deadline_at_ms
        return deadline is not None and self.clock_ms() >= deadline

    def _budget_terminal(
        self,
        state: ControllerState,
        sequence: int,
    ) -> ControllerDecision:
        if _all_visible_hits(state.evidence_by_aspect):
            return _terminal(
                sequence,
                tool="answer",
                mode="partial",
                stop_reason="partial_evidence",
                purpose="return visible evidence after reaching a hard budget",
            )
        return _terminal(
            sequence,
            tool="stop",
            mode="budget",
            stop_reason="budget_exhausted",
            purpose="stop before exceeding a hard budget",
        )

    def _focused_read(self, state: ControllerState, sequence: int) -> ControllerDecision | None:
        needs = requested_needs(state.analysis.original_question)
        generic = state.analysis.intent == "process" or len(state.task_plan.needs) > 1
        if (
            not ("materials" in needs or len(needs) > 1 or generic)
            or state.analysis.intent == "comparison"
        ):
            return None
        hits = _all_visible_hits(state.evidence_by_aspect)
        if not hits or (state.ledger and state.ledger.conflicting_aspects):
            return None
        anchor = hits[0].hit
        budget = state.budget_state.budget
        if state.focused_find_doc_id is None:
            if state.budget_state.find_calls >= budget.max_find_calls:
                return None
            return ControllerDecision(
                action=AgentAction(
                    sequence=sequence,
                    tool="find",
                    purpose="locate bounded evidence in the admitted anchor section",
                    aspect=state.analysis.required_aspects[0],
                    find_request=FindRequest(
                        request_id=f"agent-step-{sequence}",
                        user=state.user,
                        doc_id=anchor.doc_id,
                        pattern=state.analysis.original_question[:500],
                        match_mode="anchor_section",
                        max_results=20,
                        anchor_chunk_id=anchor.chunk_id,
                        filters=state.analysis.filters,
                    ),
                )
            )
        if state.focused_open_count >= 2 or state.budget_state.open_calls >= budget.max_open_calls:
            return None
        seen_text = "\n".join(
            [*(h.hit.matched_text for h in hits), *(o.result.content for o in state.open_results)]
        )
        known_materials = material_terms(seen_text)
        seen_ids = set(state.opened_doc_ids)
        delivered_prefixes = {h.hit.chunk_id: h.hit.matched_text[:1200] for h in hits}
        candidates = [
            m.match
            for m in state.find_results
            if m.match.doc_id == anchor.doc_id
            and m.match.chunk_id not in seen_ids
            and m.match.preview not in delivered_prefixes.get(m.match.chunk_id, "")
            and (generic or relevant_need_count(m.match.preview, needs))
        ]
        candidates.sort(
            key=lambda match: (
                -sum(
                    need_matches(need, state.analysis.original_question, [match.preview])
                    for need in state.task_plan.needs
                    if not need.evidence_ids
                ),
                -len(material_terms(match.preview) - known_materials),
                -relevant_need_count(match.preview, needs),
                match.chunk_id,
            )
        )
        remaining = budget.max_context_chars - state.budget_state.context_chars
        if not candidates or remaining <= 0:
            return None
        return ControllerDecision(
            action=AgentAction(
                sequence=sequence,
                tool="open",
                purpose="read a located same-scope evidence chunk",
                aspect=state.analysis.required_aspects[0],
                open_request=OpenRequest(
                    request_id=f"agent-step-{sequence}",
                    user=state.user,
                    target_type="chunk",
                    target_id=candidates[0].chunk_id,
                    max_chars=min(2000, remaining),
                    start_char=candidates[0].preview_start,
                    anchor_chunk_id=anchor.chunk_id,
                    filters=state.analysis.filters,
                ),
            )
        )

    def _completeness_open(
        self,
        state: ControllerState,
        sequence: int,
    ) -> ControllerDecision | None:
        if state.analysis.intent != "completeness":
            return None
        needs = requested_needs(state.analysis.original_question)
        if "materials" in needs or len(needs) > 1 or len(state.task_plan.needs) > 1:
            # The focused path must never fall back to an unscoped full-document prefix.
            return None
        for hit in _all_visible_hits(state.evidence_by_aspect):
            raw_hit = hit.hit
            if raw_hit.doc_id in state.opened_doc_ids:
                continue
            remaining = (
                state.budget_state.budget.max_context_chars - state.budget_state.context_chars
            )
            if remaining <= 0:
                return None
            purpose = "open the visible document for completeness coverage"
            return ControllerDecision(
                action=AgentAction(
                    sequence=sequence,
                    tool="open",
                    purpose=purpose,
                    aspect=state.analysis.required_aspects[0],
                    open_request=OpenRequest(
                        request_id=f"agent-step-{sequence}",
                        user=state.user,
                        target_type="document",
                        target_id=raw_hit.doc_id,
                        max_chars=min(4000, remaining),
                    ),
                )
            )
        return None


def _terminal(
    sequence: int,
    *,
    tool: str,
    mode: AnswerMode,
    stop_reason: AgentStopReason,
    purpose: str,
) -> ControllerDecision:
    return ControllerDecision(
        action=AgentAction(sequence=sequence, tool=tool, purpose=purpose),
        terminal_mode=mode,
        stop_reason=stop_reason,
    )


def _query_for_aspect(analysis: QueryAnalysis, aspect: str) -> str:
    try:
        index = analysis.required_aspects.index(aspect)
    except ValueError:
        return analysis.search_queries[0]
    if index < len(analysis.search_queries):
        return analysis.search_queries[index]
    return analysis.search_queries[0]


def _merge_hits(
    existing: list[AdmittedEvidenceChunk],
    latest: list[AdmittedEvidenceChunk],
) -> list[AdmittedEvidenceChunk]:
    result = list(existing)
    seen = {item.hit.chunk_id for item in result}
    for hit in latest:
        if hit.hit.chunk_id not in seen:
            seen.add(hit.hit.chunk_id)
            result.append(hit)
    return result


def _all_visible_hits(
    evidence: dict[str, list[AdmittedEvidenceChunk]],
) -> list[AdmittedEvidenceChunk]:
    result: list[AdmittedEvidenceChunk] = []
    seen: set[str] = set()
    for hits in evidence.values():
        for hit in hits:
            if hit.hit.chunk_id not in seen:
                seen.add(hit.hit.chunk_id)
                result.append(hit)
    return result


def _validated_state(
    state: ControllerState,
    **updates,
) -> ControllerState:
    values = {field_name: getattr(state, field_name) for field_name in ControllerState.model_fields}
    values.update(updates)
    return ControllerState(**values)


__all__ = [
    "ControllerDecision",
    "ControllerState",
    "V2AgentController",
]
