from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.evidence_ledger import build_ledger
from app.agent.evidence_relevance import has_query_anchor_support
from app.agent.tools_v2 import V2ToolExecution
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
    FindResult,
    OpenRequest,
    OpenResult,
    QueryAnalysis,
    SearchHit,
    SearchRequest,
    SearchResult,
    UserContext,
)


ClockMs = Callable[[], float]


class ControllerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: QueryAnalysis
    user: UserContext
    top_k: int = Field(ge=1, le=20)
    budget_state: BudgetState
    evidence_by_aspect: dict[str, list[SearchHit]] = Field(default_factory=dict)
    attempted_search_aspects: list[str] = Field(default_factory=list)
    opened_doc_ids: list[str] = Field(default_factory=list)
    open_results: list[OpenResult] = Field(default_factory=list)
    find_results: list[FindResult] = Field(default_factory=list)
    denied_only_signal: bool = False
    ledger: EvidenceLedger | None = None
    last_error: ToolError | None = None


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
    def __init__(self, *, clock_ms: ClockMs | None = None) -> None:
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000)

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
        return ControllerState(
            analysis=analysis,
            user=user,
            top_k=top_k or 5,
            budget_state=BudgetState(
                budget=active_budget,
                deadline_at_ms=now + active_budget.deadline_ms,
            ),
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

        open_decision = self._completeness_open(state, sequence)
        if open_decision is not None:
            return open_decision

        ledger = state.ledger or build_ledger(
            state.analysis,
            state.evidence_by_aspect,
            denied_only=state.denied_only_signal
            and not _all_visible_hits(state.evidence_by_aspect),
            budget_exhausted=self._hard_budget_exhausted(state),
        )
        if ledger.recommended_action == "answer":
            return _terminal(
                sequence,
                tool="answer",
                mode="answered",
                stop_reason="completed",
                purpose="answer because every required aspect has visible evidence",
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
        execution: V2ToolExecution,
    ) -> ControllerState:
        evidence = {
            aspect: list(hits)
            for aspect, hits in state.evidence_by_aspect.items()
        }
        attempted = list(state.attempted_search_aspects)
        opened_doc_ids = list(state.opened_doc_ids)
        open_results = list(state.open_results)
        find_results = list(state.find_results)
        denied_signal = state.denied_only_signal
        last_error: ToolError | None = None
        action = execution.action
        result = execution.result

        if action.tool == "search" and action.aspect is not None:
            if action.aspect not in attempted:
                attempted.append(action.aspect)
            if isinstance(result, SearchResult):
                supported_hits = [
                    hit
                    for hit in result.hits
                    if has_query_anchor_support(
                        action.search_request.query,
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
            if isinstance(result, OpenResult):
                open_results.append(result)
        elif action.tool == "find" and isinstance(result, FindResult):
            find_results.append(result)

        if isinstance(result, ToolError):
            if not (result.code == "not_found" and action.tool in {"find", "open"}):
                last_error = result

        next_state = state.model_copy(
            update={
                "budget_state": execution.budget_state,
                "evidence_by_aspect": evidence,
                "attempted_search_aspects": attempted,
                "opened_doc_ids": opened_doc_ids,
                "open_results": open_results,
                "find_results": find_results,
                "denied_only_signal": denied_signal,
                "last_error": last_error,
            }
        )
        if state.analysis.intent != "unsafe":
            ledger = build_ledger(
                state.analysis,
                evidence,
                denied_only=denied_signal and not _all_visible_hits(evidence),
                budget_exhausted=self._hard_budget_exhausted(next_state),
            )
            next_state = next_state.model_copy(update={"ledger": ledger})
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

    def _completeness_open(
        self,
        state: ControllerState,
        sequence: int,
    ) -> ControllerDecision | None:
        if state.analysis.intent != "completeness":
            return None
        for hit in _all_visible_hits(state.evidence_by_aspect):
            if hit.doc_id in state.opened_doc_ids:
                continue
            remaining = (
                state.budget_state.budget.max_context_chars
                - state.budget_state.context_chars
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
                        target_id=hit.doc_id,
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


def _merge_hits(existing: list[SearchHit], latest: list[SearchHit]) -> list[SearchHit]:
    result = list(existing)
    seen = {hit.chunk_id for hit in result}
    for hit in latest:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            result.append(hit)
    return result


def _all_visible_hits(evidence: dict[str, list[SearchHit]]) -> list[SearchHit]:
    result: list[SearchHit] = []
    seen: set[str] = set()
    for hits in evidence.values():
        for hit in hits:
            if hit.chunk_id not in seen:
                seen.add(hit.chunk_id)
                result.append(hit)
    return result


__all__ = [
    "ControllerDecision",
    "ControllerState",
    "V2AgentController",
]
