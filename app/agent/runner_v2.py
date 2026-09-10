from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Protocol

from app.agent.citation_verifier import verify_claims
from app.agent.answer_applicability import enforce_answer_applicability
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
from app.domain.evidence_packet import DeliveredEvidence, complete_evidence_prefix
from app.domain.queries import QueryAnalysis, UserContext
from app.domain.retrieved_security import (
    AdmittedEvidenceChunk,
    GuardedSearchResult,
    GuardedV2ToolExecution,
    RetrievedContentSecurityTrace,
)
from app.security.access import redact_trace_payload

ClockMs = Callable[[], float]
_RUNNER_CACHE_LOCK = RLock()


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
    def __init__(self, *, max_evidence_per_aspect: int = 1) -> None:
        if max_evidence_per_aspect < 1 or max_evidence_per_aspect > 8:
            raise ValueError("max_evidence_per_aspect must be between 1 and 8")
        self.max_evidence_per_aspect = max_evidence_per_aspect

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
        if state.ledger is not None and state.ledger.conflicting_aspects:
            return build_conflict_response(state, trace)

        claims: list[Claim] = []
        sources: list[AnswerSource] = []
        visible_hits = _all_visible_hits(state)
        supported_aspects = state.ledger.supported_aspects if state.ledger is not None else []
        claim_index = 0
        for aspect in supported_aspects:
            hits = state.evidence_by_aspect.get(aspect, [])
            if not hits:
                continue
            for evidence in hits[: self.max_evidence_per_aspect]:
                hit = evidence.hit
                claim_index += 1
                claims.append(
                    Claim(
                        claim_id=f"claim-{claim_index}",
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


def build_conflict_response(state: ControllerState, trace: dict) -> AnswerResponse:
    from app.agent.evidence_ledger import _numeric_conflicts

    admitted = {"comparison": _all_visible_hits(state)}
    scope_only = bool(_numeric_conflicts(admitted, scope_ambiguity=True)) and not bool(
        _numeric_conflicts(admitted)
    )
    note = (
        "现有材料的适用范围不同或不完整，当前范围信息不足以比较或确定唯一适用制度。"
        "以下为各自摘录，不构成同一事实冲突或制度优先级裁决。"
        if scope_only else
        "现有可见材料存在潜在不一致，无法据此确定唯一期限或数值。"
        "以下结论仅限已展示摘录，不构成制度优先级裁决。"
    )
    conflict_ids = (
        {item.chunk_id for item in state.ledger.items if item.relation == "conflicts"}
        if state.ledger
        else set()
    )
    views = []
    for evidence in _all_visible_hits(state):
        if evidence.hit.chunk_id not in conflict_ids or len(views) >= 8:
            continue
        text = complete_evidence_prefix(evidence.hit.matched_text, 1000)
        if text.strip():
            views.append(DeliveredEvidence(anchor=evidence, matched_text=text))
    claims = [
        Claim(
            claim_id=f"conflict-{index}",
            text=view.matched_text,
            cited_chunk_ids=[view.citation_id],
        )
        for index, view in enumerate(views, start=1)
    ]
    citations = verify_claims(claims, views)
    supported = {citation.claim_id for citation in citations if citation.supported}
    claims = [claim for claim in claims if claim.claim_id in supported]
    cited_ids = {chunk_id for claim in claims for chunk_id in claim.cited_chunk_ids}
    return AnswerResponse(
        mode="partial",
        stop_reason="partial_evidence",
        answer="\n".join([
            *(claim.text for claim in claims),
            note,
        ]),
        claims=claims,
        citations=[citation for citation in citations if citation.supported],
        sources=[
            AnswerSource(
                doc_id=view.anchor.hit.doc_id,
                source_path=view.anchor.hit.source_path,
                section_path=view.anchor.hit.section_path,
                chunk_id=view.citation_id,
                preview=view.matched_text,
                index_run_id=view.anchor.hit.index_run_id,
                version_id=view.anchor.hit.version_id,
                target_id=view.citation_id,
            )
            for view in views
            if view.citation_id in cited_ids
        ],
        warnings=[
            "Explicit scope differs or is incomplete; insufficient scope to compare."
            if scope_only else
            "Potential same-scope evidence conflict; excerpts are not a selected policy answer."
        ],
        trace={
            **trace, "answer_strategy": "conflict_excerpts", "generation_attempts": 0,
            "stop_reason": "partial_evidence", "final_mode": "partial",
            "comparison_status": (
                "scope_insufficient" if scope_only else "potential_numeric_conflict"
            ),
        },
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
        index_binding: tuple[Path, str, str] | None = None,
    ) -> None:
        self.registry = registry
        self.analyzer = analyzer or RuleFirstQueryAnalyzer()
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000)
        self.controller = controller or V2AgentController(clock_ms=self.clock_ms)
        self.response_builder = response_builder or ExtractiveResponseBuilder()
        self.budget = budget or budget_from_settings()
        self.index_binding = index_binding

    def run(
        self,
        question: str,
        user: UserContext,
        top_k: int | None = None,
    ) -> AnswerResponse:
        from app.runtime.request_context import (
            bind_request_context,
            current_request_context,
            reset_request_context,
        )

        existing = current_request_context()
        token = None
        previous_deadline = existing.deadline_at_ms if existing is not None else None
        if existing is None:
            token = bind_request_context("direct-agent", deadline_ms=self.budget.deadline_ms)
        else:
            existing.deadline_at_ms = min(
                existing.deadline_at_ms, time.monotonic() * 1000 + self.budget.deadline_ms
            )
        try:
            return self._run_version_bound(question, user, top_k)
        finally:
            if token is not None:
                reset_request_context(token)
            elif existing is not None:
                existing.deadline_at_ms = previous_deadline

    def _run_version_bound(
        self,
        question: str,
        user: UserContext,
        top_k: int | None = None,
    ) -> AnswerResponse:
        if self.index_binding is None:
            return self._run(question, user, top_k)
        from app.indexing.store import load_active_pointer

        root, run_id, manifest_sha256 = self.index_binding
        trace = {"index_run_id": run_id, "index_manifest_sha256": manifest_sha256}
        try:
            before = load_active_pointer(root)
            if (before.run_id, before.manifest_sha256) != (run_id, manifest_sha256):
                return _source_free_response(
                    "system", "system_error", {**trace, "index_binding_status": "changed"}
                )
            response = self._run(question, user, top_k)
            trace = {**response.trace, **trace}
            after = load_active_pointer(root)
            # Include activation time to reject activation/rollback during this request.
            if after != before:
                return _source_free_response(
                    "system", "system_error", {**trace, "index_binding_status": "changed"}
                )
            return response.model_copy(
                update={
                    "trace": {
                        **trace,
                        "index_binding_status": "verified",
                    }
                }
            )
        except Exception:
            return _source_free_response(
                "system", "system_error", {**trace, "index_binding_status": "unavailable"}
            )

    def _run(
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
                step_traces.append(_terminal_step_trace(decision, state))
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
                        fallback_action=_evidence_action_for_mode(decision.terminal_mode),
                    ),
                )
                try:
                    response = self.response_builder.build(
                        question=question,
                        state=state,
                        mode=decision.terminal_mode,
                        stop_reason=decision.stop_reason,
                        trace=trace,
                    )
                    response = enforce_answer_applicability(question, response)
                except Exception:
                    response = _source_free_response(
                        "system",
                        "system_error",
                        trace,
                    )
                return response.model_copy(
                    update={
                        "trace": {
                            **response.trace,
                            "controller_stop_reason": decision.stop_reason,
                            "stop_reason": response.stop_reason,
                            "final_mode": response.mode,
                        }
                    }
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
    error_code = execution.result.code if isinstance(execution.result, ToolError) else None
    security_trace = RetrievedContentSecurityTrace.from_counters(
        execution.security_counters,
        stop_reason=execution.security_stop_reason,
    )
    retrieval = {}
    if isinstance(execution.result, ToolError):
        from app.retrieval.scorer_errors import REASONS

        matched = next(
            (
                reason
                for reason in REASONS
                if execution.result.safe_message == f"Reranker failure: {reason}."
            ),
            None,
        )
        if matched:
            retrieval["reranker_failure_reason"] = matched
    if (
        isinstance(execution.result, GuardedSearchResult)
        and "reranker_scored" in execution.result.stage_counts
    ):
        retrieval = {
            "retrieval_mode": execution.result.mode,
            "retrieval_counts": {
                key: execution.result.stage_counts[key]
                for key in ("reranker_scored", "reranker_calls", "reranker_elapsed_ms", "returned")
                if key in execution.result.stage_counts
            },
        }
    return {
        **retrieval,
        "sequence": execution.action.sequence,
        "tool": execution.action.tool,
        "status": execution.status,
        "latency_ms": round(latency_ms, 3),
        "visible_count": execution.visible_count,
        "context_chars_added": execution.context_chars_added,
        "error_code": error_code,
        "budget": _budget_trace(execution.budget_state),
        "retrieved_content_security": security_trace.model_dump(mode="json"),
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
        "budget": _budget_trace(budget_state)
        if budget_state is not None
        else {
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
        "security_filtered": ("Available evidence was withheld by the configured safety policy."),
    }
    if mode not in messages:
        mode = "system"
        stop_reason = "system_error"
    return AnswerResponse(
        mode=mode,
        answer=messages[mode],
        sources=[],
        stop_reason=stop_reason,
        trace={**trace, "stop_reason": stop_reason, "final_mode": mode},
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


def _get_default_v2_runner() -> V2AgentRunner:
    from app.indexing.store import load_active_pointer
    from app.retrieval.canary_config import get_retrieval_canary_settings
    from app.retrieval.serving_config import ServingRetrievalSettings

    settings = get_settings()
    root = settings.v2_indexes_dir.resolve()
    pointer = load_active_pointer(root)
    policies = tuple(get_retrieval_canary_settings().page_fusion_policy_ids)
    # Serialize cold loads; functools' cache alone can load duplicate large snapshots.
    with _RUNNER_CACHE_LOCK:
        return _get_versioned_v2_runner(
            str(root),
            pointer.run_id,
            pointer.manifest_sha256,
            settings.model_dump_json(),
            policies,
            ServingRetrievalSettings().model_dump_json(),
        )


@lru_cache(maxsize=2)
def _get_versioned_v2_runner(
    root: str,
    run_id: str,
    manifest_sha256: str,
    configuration: str,
    page_fusion_policy_ids: tuple[str, ...],
    retrieval_configuration: str = "{}",
) -> V2AgentRunner:
    from app.agent.generation_v2 import GenerationV2ResponseBuilder
    from app.external_datasets.uda_finance_hierarchical import (
        build_finance_known_report_canary,
    )
    from app.retrieval.navigation import DocumentNavigator
    from app.retrieval.pipeline import HybridRetrievalPipeline
    from app.retrieval.snapshot import V2IndexSnapshot
    from app.retriever import _embed_text

    settings = Settings.model_validate_json(configuration)
    snapshot = V2IndexSnapshot.load(Path(root), run_id)
    if snapshot.version.manifest_sha256 != manifest_sha256:
        raise ValueError("serving snapshot does not match active manifest identity")

    def embed_text(text: str) -> list[float]:
        return _embed_text(settings.embedding_model, text)

    pipeline = HybridRetrievalPipeline(snapshot, embed_text=embed_text)
    if page_fusion_policy_ids:
        pipeline = build_finance_known_report_canary(
            pipeline,
            allowed_policy_ids=list(page_fusion_policy_ids),
        )
    navigator = DocumentNavigator(snapshot, pipeline=pipeline)
    from app.retrieval.serving_config import ServingRetrievalSettings
    from app.security.reranking_admission import RerankingContentAdmission
    from app.security.retrieved_admission import RetrievedContentAdmission

    retrieval_settings = ServingRetrievalSettings.model_validate_json(retrieval_configuration)
    scorer = None
    if retrieval_settings.retrieval_profile.startswith("safe_dense_raw"):
        from app.retrieval.local_cross_encoder import get_local_cross_encoder

        scorer = get_local_cross_encoder(
            str(retrieval_settings.reranker_path.resolve()), retrieval_settings.reranker_device
        )
    registry = V2ToolRegistry(
        navigator,
        admission=(
            RerankingContentAdmission(search_scorer=scorer)
            if scorer is not None
            else RetrievedContentAdmission()
        ),
        retrieval_profile=retrieval_settings.retrieval_profile,
    )
    return V2AgentRunner(
        registry=registry,
        response_builder=GenerationV2ResponseBuilder(
            model=settings.chat_model,
        ),
        budget=budget_from_settings(settings),
        index_binding=(Path(root), run_id, manifest_sha256),
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
