from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

from app.agent.citation_verifier import verify_claims
from app.agent.controller_v2 import (
    ControllerDecision,
    ControllerState,
    V2AgentController,
)
from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.agent.tools_v2 import V2ToolRegistry
from app.config import Settings, get_settings
from app.domain.agent import AgentBudget, AgentStopReason, AnswerMode, ToolError
from app.domain.evidence import AnswerResponse, AnswerSource, Claim, EvidenceLedger
from app.domain.queries import QueryAnalysis, UserContext
from app.domain.retrieved_security import (
    AdmittedEvidenceChunk,
    GuardedV2ToolExecution,
)
from app.security.access import redact_trace_payload


ClockMs = Callable[[], float]


class ResponseBuilder(Protocol):
    def build(
        self,
        *,
        question: str,
        state: ControllerState,
        mode: AnswerMode,
        stop_reason: AgentStopReason,
        trace: dict,
    ) -> AnswerResponse: ...


class ExtractiveResponseBuilder:
    def build(
        self,
        *,
        question: str,
        state: ControllerState,
        mode: AnswerMode,
        stop_reason: AgentStopReason,
        trace: dict,
    ) -> AnswerResponse:
        if mode not in {"answered", "partial"}:
            return _source_free_response(mode, stop_reason, trace)

        claims: list[Claim] = []
        sources: list[AnswerSource] = []
        visible_hits = _all_visible_hits(state)
        supported_aspects = (
            state.ledger.supported_aspects if state.ledger is not None else []
        )
        for index, aspect in enumerate(supported_aspects, start=1):
            hits = state.evidence_by_aspect.get(aspect, [])
            if not hits:
                continue
            evidence = hits[0]
            hit = evidence.hit
            claims.append(
                Claim(
                    claim_id=f"claim-{index}",
                    text=hit.matched_text,
                    cited_chunk_ids=[hit.chunk_id],
                )
            )
            if all(source.chunk_id != hit.chunk_id for source in sources):
                sources.append(
                    AnswerSource(
                        doc_id=hit.doc_id,
                        source_path=hit.source_path,
                        section_path=hit.section_path,
                        chunk_id=hit.chunk_id,
                        preview=hit.matched_text[:1000],
                    )
                )

        if not claims or not sources:
            return _source_free_response(
                "system",
                "system_error",
                trace,
            )
        citations = verify_claims(claims, visible_hits)
        verified_mode: AnswerMode = mode
        verified_stop_reason = stop_reason
        warnings: list[str] = []
        if any(not citation.supported for citation in citations):
            verified_mode = "partial"
            verified_stop_reason = "partial_evidence"
            warnings.append("One or more extractive claims failed citation checks.")
        return AnswerResponse(
            mode=verified_mode,
            answer="\n".join(claim.text for claim in claims),
            claims=claims,
            citations=citations,
            sources=sources,
            warnings=warnings,
            stop_reason=verified_stop_reason,
            trace=trace,
        )


class V2AgentRunner:
    def __init__(
        self,
        *,
        registry: V2ToolRegistry,
        analyzer: RuleFirstQueryAnalyzer | None = None,
        controller: V2AgentController | None = None,
        response_builder: ResponseBuilder | None = None,
        budget: AgentBudget | None = None,
        clock_ms: ClockMs | None = None,
    ) -> None:
        self.registry = registry
        self.analyzer = analyzer or RuleFirstQueryAnalyzer()
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000)
        self.controller = controller or V2AgentController(clock_ms=self.clock_ms)
        self.response_builder = response_builder or ExtractiveResponseBuilder()
        self.budget = budget or budget_from_settings()

    def run(
        self,
        question: str,
        user: UserContext,
        top_k: int | None = None,
    ) -> AnswerResponse:
        step_traces: list[dict] = []
        try:
            analysis = self.analyzer.analyze(question, user)
            state = self.controller.initialize(
                analysis,
                user,
                top_k=top_k,
                budget=self.budget,
            )
        except Exception:
            trace = _build_trace(
                intent="unknown",
                analysis_source="rules",
                required_aspect_count=0,
                steps=step_traces,
                stop_reason="system_error",
                budget_state=None,
                evidence=_evidence_trace(
                    None,
                    required=0,
                    fallback_action="system",
                ),
            )
            return _source_free_response("system", "system_error", trace)

        guard_limit = self.budget.max_steps + 2
        for _ in range(guard_limit):
            try:
                decision = self.controller.next_decision(state)
            except Exception:
                return self._system_response(analysis, state, step_traces)

            if decision.terminal_mode is not None:
                step_traces.append(
                    _terminal_step_trace(decision, state)
                )
                trace = _build_trace(
                    intent=analysis.intent,
                    analysis_source=analysis.source,
                    required_aspect_count=len(analysis.required_aspects),
                    steps=step_traces,
                    stop_reason=decision.stop_reason,
                    budget_state=state.budget_state,
                    evidence=_evidence_trace(
                        state.ledger,
                        required=len(analysis.required_aspects),
                        fallback_action=_evidence_action_for_mode(
                            decision.terminal_mode
                        ),
                    ),
                )
                try:
                    return self.response_builder.build(
                        question=question,
                        state=state,
                        mode=decision.terminal_mode,
                        stop_reason=decision.stop_reason,
                        trace=trace,
                    )
                except Exception:
                    return _source_free_response(
                        "system",
                        "system_error",
                        trace,
                    )

            started = self.clock_ms()
            try:
                execution = self.registry.run(
                    decision.action,
                    state.budget_state,
                )
                state = self.controller.observe(state, execution)
            except Exception:
                return self._system_response(analysis, state, step_traces)
            step_traces.append(
                _tool_step_trace(
                    execution,
                    latency_ms=max(0.0, self.clock_ms() - started),
                )
            )

        return self._system_response(analysis, state, step_traces)

    def _system_response(
        self,
        analysis: QueryAnalysis,
        state: ControllerState,
        step_traces: list[dict],
    ) -> AnswerResponse:
        trace = _build_trace(
            intent=analysis.intent,
            analysis_source=analysis.source,
            required_aspect_count=len(analysis.required_aspects),
            steps=step_traces,
            stop_reason="system_error",
            budget_state=state.budget_state,
            evidence=_evidence_trace(
                state.ledger,
                required=len(analysis.required_aspects),
                fallback_action="system",
            ),
        )
        return _source_free_response("system", "system_error", trace)


def _tool_step_trace(
    execution: GuardedV2ToolExecution,
    *,
    latency_ms: float,
) -> dict:
    error_code = (
        execution.result.code
        if isinstance(execution.result, ToolError)
        else None
    )
    return {
        "sequence": execution.action.sequence,
        "tool": execution.action.tool,
        "status": execution.status,
        "latency_ms": round(latency_ms, 3),
        "visible_count": execution.visible_count,
        "context_chars_added": execution.context_chars_added,
        "error_code": error_code,
        "budget": _budget_trace(execution.budget_state),
    }


def _terminal_step_trace(
    decision: ControllerDecision,
    state: ControllerState,
) -> dict:
    return {
        "sequence": decision.action.sequence,
        "tool": decision.action.tool,
        "status": "terminal",
        "latency_ms": 0.0,
        "visible_count": 0,
        "context_chars_added": 0,
        "error_code": None,
        "budget": _budget_trace(state.budget_state),
    }


def _build_trace(
    *,
    intent: str,
    analysis_source: str,
    required_aspect_count: int,
    steps: list[dict],
    stop_reason: str | None,
    budget_state,
    evidence: dict,
) -> dict:
    payload = {
        "intent": intent,
        "analysis_source": analysis_source,
        "required_aspect_count": required_aspect_count,
        "steps": steps,
        "stop_reason": stop_reason,
        "evidence": evidence,
        "budget": _budget_trace(budget_state) if budget_state is not None else {
            "search_calls": 0,
            "find_calls": 0,
            "open_calls": 0,
            "steps": 0,
            "context_chars": 0,
        },
    }
    return redact_trace_payload(payload)


def _evidence_trace(
    ledger: EvidenceLedger | None,
    *,
    required: int,
    fallback_action: str,
) -> dict:
    if ledger is None:
        return {
            "required": required,
            "supported": 0,
            "missing": required,
            "conflicting": 0,
            "coverage": 0.0,
            "recommended_action": fallback_action,
        }
    return {
        "required": len(ledger.required_aspects),
        "supported": len(ledger.supported_aspects),
        "missing": len(ledger.missing_aspects),
        "conflicting": len(ledger.conflicting_aspects),
        "coverage": ledger.coverage,
        "recommended_action": ledger.recommended_action,
    }


def _evidence_action_for_mode(mode: AnswerMode) -> str:
    return {
        "answered": "answer",
        "partial": "partial",
        "unsafe": "refuse",
        "permission": "permission",
        "not_found": "not_found",
        "budget": "budget",
        "system": "system",
        "security_filtered": "security_filtered",
    }[mode]


def _budget_trace(state) -> dict[str, int]:
    return {
        "search_calls": state.search_calls,
        "find_calls": state.find_calls,
        "open_calls": state.open_calls,
        "steps": state.steps,
        "context_chars": state.context_chars,
    }


def _all_visible_hits(state: ControllerState) -> list[AdmittedEvidenceChunk]:
    result: list[AdmittedEvidenceChunk] = []
    seen: set[str] = set()
    for hits in state.evidence_by_aspect.values():
        for hit in hits:
            if hit.hit.chunk_id not in seen:
                seen.add(hit.hit.chunk_id)
                result.append(hit)
    return result


def _source_free_response(
    mode: AnswerMode,
    stop_reason: AgentStopReason,
    trace: dict,
) -> AnswerResponse:
    messages = {
        "unsafe": "I cannot assist with bypassing controls or exposing sensitive data.",
        "permission": "The requested information is unavailable for this identity.",
        "not_found": "No supported answer was found in the visible knowledge base.",
        "system": "The knowledge service could not complete the request.",
        "budget": "The agent stopped before exceeding its execution budget.",
        "security_filtered": (
            "Available evidence was withheld by the configured safety policy."
        ),
    }
    if mode not in messages:
        mode = "system"
        stop_reason = "system_error"
    return AnswerResponse(
        mode=mode,
        answer=messages[mode],
        sources=[],
        stop_reason=stop_reason,
        trace=trace,
    )


def budget_from_settings(settings: Settings | None = None) -> AgentBudget:
    active = settings or get_settings()
    return AgentBudget(
        max_search_calls=active.agent_v2_max_search_calls,
        max_find_calls=active.agent_v2_max_find_calls,
        max_open_calls=active.agent_v2_max_open_calls,
        max_steps=active.agent_v2_max_steps,
        max_context_chars=active.agent_v2_max_context_chars,
        deadline_ms=active.agent_v2_deadline_ms,
    )


@lru_cache(maxsize=1)
def _get_default_v2_runner() -> V2AgentRunner:
    from app.agent.generation_v2 import GenerationV2ResponseBuilder
    from app.retrieval.navigation import DocumentNavigator
    from app.retrieval.pipeline import HybridRetrievalPipeline
    from app.retrieval.snapshot import V2IndexSnapshot
    from app.retriever import _embed_text

    settings = get_settings()
    snapshot = V2IndexSnapshot.load(settings.v2_indexes_dir)

    def embed_text(text: str) -> list[float]:
        return _embed_text(settings.embedding_model, text)

    pipeline = HybridRetrievalPipeline(snapshot, embed_text=embed_text)
    navigator = DocumentNavigator(snapshot, pipeline=pipeline)
    registry = V2ToolRegistry(navigator)
    return V2AgentRunner(
        registry=registry,
        response_builder=GenerationV2ResponseBuilder(
            model=settings.chat_model,
        ),
        budget=budget_from_settings(settings),
    )


def run_agent_v2_chat(
    question: str,
    user: UserContext,
    top_k: int | None = None,
) -> AnswerResponse:
    try:
        analysis = RuleFirstQueryAnalyzer().analyze(question, user)
    except Exception:
        trace = _build_trace(
            intent="unknown",
            analysis_source="rules",
            required_aspect_count=0,
            steps=[],
            stop_reason="system_error",
            budget_state=None,
            evidence=_evidence_trace(
                None,
                required=0,
                fallback_action="system",
            ),
        )
        return _source_free_response("system", "system_error", trace)

    if analysis.intent == "unsafe":
        empty_budget = {
            "search_calls": 0,
            "find_calls": 0,
            "open_calls": 0,
            "steps": 0,
            "context_chars": 0,
        }
        trace = _build_trace(
            intent="unsafe",
            analysis_source=analysis.source,
            required_aspect_count=0,
            steps=[
                {
                    "sequence": 1,
                    "tool": "refuse",
                    "status": "terminal",
                    "latency_ms": 0.0,
                    "visible_count": 0,
                    "context_chars_added": 0,
                    "error_code": None,
                    "budget": empty_budget,
                }
            ],
            stop_reason="unsafe",
            budget_state=None,
            evidence=_evidence_trace(
                None,
                required=0,
                fallback_action="refuse",
            ),
        )
        return _source_free_response("unsafe", "unsafe", trace)

    try:
        return _get_default_v2_runner().run(question, user, top_k)
    except Exception:
        trace = _build_trace(
            intent=analysis.intent,
            analysis_source=analysis.source,
            required_aspect_count=len(analysis.required_aspects),
            steps=[],
            stop_reason="system_error",
            budget_state=None,
            evidence=_evidence_trace(
                None,
                required=len(analysis.required_aspects),
                fallback_action="system",
            ),
        )
        return _source_free_response("system", "system_error", trace)


__all__ = [
    "ExtractiveResponseBuilder",
    "ResponseBuilder",
    "V2AgentRunner",
    "budget_from_settings",
    "run_agent_v2_chat",
]
