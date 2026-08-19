from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.agent.controller_v2 import (
    ControllerDecision,
    ControllerState,
    V2AgentController,
)
from app.agent.query_analysis import RuleFirstQueryAnalyzer
from app.agent.runner_v2 import (
    ExtractiveResponseBuilder,
    ResponseBuilder,
    V2AgentRunner,
    _build_trace,
    _evidence_action_for_mode,
    _evidence_trace,
    _source_free_response,
    _terminal_step_trace,
    _tool_step_trace,
)
from app.agent.tools_v2 import V2ToolRegistry, build_tool_error_execution
from app.agent_runtime.tool_contract import ToolContext, ToolRequest
from app.agent_runtime.tool_gateway import ToolGateway
from app.agent_runtime.trajectory import SQLiteTrajectoryStore, TrajectoryRecorder
from app.domain.agent import AgentBudget, ToolErrorCode
from app.domain.evidence import AnswerResponse
from app.domain.queries import QueryAnalysis, UserContext
from app.domain.retrieved_security import (
    GuardedFindResult,
    GuardedOpenAdmittedResult,
    GuardedSearchResult,
    GuardedV2ToolExecution,
)


ClockMs = Callable[[], float]
OrchestratorName = Literal["bounded", "langgraph"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentRunRequest(_StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    user: UserContext
    request_id: str = Field(min_length=1, max_length=200)
    trace_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    top_k: int | None = Field(default=None, ge=1, le=20)


class AgentRunResult(_StrictModel):
    orchestrator: OrchestratorName
    request_id: str
    trace_id: str
    session_id: str
    response: AnswerResponse
    node_trace: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)


class AgentOrchestrator(Protocol):
    name: OrchestratorName

    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


class _ContractToolSession:
    def __init__(
        self,
        registry: V2ToolRegistry,
        context: ToolContext,
        *,
        clock_ms: ClockMs,
        recorder: TrajectoryRecorder | None = None,
    ) -> None:
        self._context = context
        self._gateway = ToolGateway(registry, clock_ms=clock_ms)
        self._gateway.start_session(context)
        self._recorder = recorder

    def run(self, action, budget_state) -> GuardedV2ToolExecution:
        arguments = {
            "search": action.search_request,
            "find": action.find_request,
            "open": action.open_request,
        }.get(action.tool)
        if arguments is None:
            return build_tool_error_execution(
                action,
                budget_state,
                code="invalid_args",
                message="The requested tool is not available.",
            )
        request = ToolRequest(
            context_request_id=self._context.request_id,
            tool=action.tool,
            sequence=action.sequence,
            purpose=action.purpose,
            aspect=action.aspect,
            arguments=arguments,
        )
        step_id = f"step-{action.sequence}"
        self._recorder.record(
            "step.started",
            step_id=step_id,
            tool_name=action.tool,
            payload={"purpose": action.purpose, "aspect": action.aspect},
        ) if self._recorder is not None else None
        if self._recorder is not None:
            self._recorder.record(
                "tool.requested",
                step_id=step_id,
                tool_name=action.tool,
                payload=_tool_request_summary(request),
            )
        result, execution = self._gateway.execute_with_domain(
            request,
            self._context,
        )
        if self._recorder is not None:
            self._record_tool_outcome(result, execution, step_id)
        if execution is not None:
            return execution
        return build_tool_error_execution(
            action,
            result.budget_state,
            code=_domain_error_code(result.error.code),
            message=result.error.safe_message,
            retryable=result.error.retryable,
        )

    def _record_tool_outcome(self, result, execution, step_id: str) -> None:
        if result.status == "error":
            self._recorder.record(
                "tool.failed",
                step_id=step_id,
                tool_name=result.tool,
                error_code=result.error.code,
                payload={
                    "retryable": result.error.retryable,
                    "safe_message": result.error.safe_message,
                },
            )
        else:
            summary = _tool_result_summary(execution)
            self._recorder.record(
                "tool.completed",
                step_id=step_id,
                tool_name=result.tool,
                payload=summary,
            )
            self._recorder.record(
                "retrieval.completed",
                step_id=step_id,
                tool_name=result.tool,
                payload=summary,
            )
            if execution.visible_count:
                self._recorder.record(
                    "evidence.admitted",
                    step_id=step_id,
                    tool_name=result.tool,
                    payload=summary,
                )
            if execution.security_counters.quarantined_count:
                self._recorder.record(
                    "evidence.rejected",
                    step_id=step_id,
                    tool_name=result.tool,
                    payload={
                        "count": execution.security_counters.quarantined_count,
                        "risk_categories": execution.security_counters.risk_categories,
                        "rule_ids": execution.security_counters.rule_ids,
                    },
                )
        self._recorder.record(
            "budget.updated",
            step_id=step_id,
            tool_name=result.tool,
            payload=result.budget_state.model_dump(mode="json"),
        )

    def close(self) -> None:
        self._gateway.close_session(self._context.session_id)


def _domain_error_code(code: str) -> ToolErrorCode:
    if code in {"unauthorized", "identity_mismatch"}:
        return "permission"
    if code == "stale_context":
        return "timeout"
    if code in {
        "invalid_args",
        "not_found",
        "permission",
        "timeout",
        "budget",
        "system",
    }:
        return code
    return "system"


class BoundedControllerAdapter:
    name: Literal["bounded"] = "bounded"

    def __init__(
        self,
        registry: V2ToolRegistry,
        *,
        analyzer: RuleFirstQueryAnalyzer | None = None,
        controller: V2AgentController | None = None,
        response_builder: ResponseBuilder | None = None,
        budget: AgentBudget | None = None,
        clock_ms: ClockMs | None = None,
        trajectory_store: SQLiteTrajectoryStore | None = None,
    ) -> None:
        self.registry = registry
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000.0)
        self.analyzer = analyzer or RuleFirstQueryAnalyzer()
        self.controller = controller or V2AgentController(clock_ms=self.clock_ms)
        self.response_builder = response_builder or ExtractiveResponseBuilder()
        self.budget = budget or AgentBudget()
        self.trajectory_store = trajectory_store

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        started = self.clock_ms()
        recorder = _begin_trajectory(self.trajectory_store, request, self.name)
        tools = _new_tool_session(
            self.registry,
            request,
            self.budget,
            clock_ms=self.clock_ms,
            recorder=recorder,
        )
        try:
            runner = V2AgentRunner(
                registry=tools,
                analyzer=self.analyzer,
                controller=self.controller,
                response_builder=self.response_builder,
                budget=self.budget,
                clock_ms=self.clock_ms,
            )
            response = runner.run(request.question, request.user, request.top_k)
            _complete_trajectory(recorder, response, self.name)
        finally:
            tools.close()
        return AgentRunResult(
            orchestrator=self.name,
            request_id=request.request_id,
            trace_id=request.trace_id,
            session_id=request.session_id,
            response=response,
            node_trace=["bounded.run"],
            latency_ms=max(0.0, self.clock_ms() - started),
        )


class _GraphState(TypedDict, total=False):
    request: AgentRunRequest
    analysis: QueryAnalysis
    controller_state: ControllerState
    decision: ControllerDecision
    response: AnswerResponse
    step_traces: list[dict]
    node_trace: list[str]
    loop_count: int


class LangGraphOrchestratorAdapter:
    name: Literal["langgraph"] = "langgraph"

    def __init__(
        self,
        registry: V2ToolRegistry,
        *,
        analyzer: RuleFirstQueryAnalyzer | None = None,
        controller: V2AgentController | None = None,
        response_builder: ResponseBuilder | None = None,
        budget: AgentBudget | None = None,
        clock_ms: ClockMs | None = None,
        trajectory_store: SQLiteTrajectoryStore | None = None,
    ) -> None:
        self.registry = registry
        self.clock_ms = clock_ms or (lambda: time.monotonic() * 1000.0)
        self.analyzer = analyzer or RuleFirstQueryAnalyzer()
        self.controller = controller or V2AgentController(clock_ms=self.clock_ms)
        self.response_builder = response_builder or ExtractiveResponseBuilder()
        self.budget = budget or AgentBudget()
        self.trajectory_store = trajectory_store

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        started = self.clock_ms()
        recorder = _begin_trajectory(self.trajectory_store, request, self.name)
        tools = _new_tool_session(
            self.registry,
            request,
            self.budget,
            clock_ms=self.clock_ms,
            recorder=recorder,
        )
        graph = self._compile(tools)
        try:
            state = graph.invoke(
                {
                    "request": request,
                    "step_traces": [],
                    "node_trace": [],
                    "loop_count": 0,
                },
                config={"recursion_limit": self.budget.max_steps * 3 + 10},
            )
            _complete_trajectory(recorder, state["response"], self.name)
        finally:
            tools.close()
        return AgentRunResult(
            orchestrator=self.name,
            request_id=request.request_id,
            trace_id=request.trace_id,
            session_id=request.session_id,
            response=state["response"],
            node_trace=state["node_trace"],
            latency_ms=max(0.0, self.clock_ms() - started),
        )

    def _compile(self, tools: _ContractToolSession):
        builder = StateGraph(_GraphState)
        builder.add_node("analyze", self._analyze_node)
        builder.add_node("decide", self._decide_node)
        builder.add_node("execute", lambda state: self._execute_node(state, tools))
        builder.add_node("publish", self._publish_node)
        builder.add_edge(START, "analyze")
        builder.add_conditional_edges(
            "analyze",
            _route_after_analyze,
            {"decide": "decide", "done": END},
        )
        builder.add_conditional_edges(
            "decide",
            _route_after_decide,
            {"execute": "execute", "publish": "publish", "done": END},
        )
        builder.add_conditional_edges(
            "execute",
            _route_after_execute,
            {"decide": "decide", "done": END},
        )
        builder.add_edge("publish", END)
        return builder.compile()

    def _analyze_node(self, state: _GraphState) -> dict:
        request = state["request"]
        nodes = [*state["node_trace"], "analyze"]
        try:
            analysis = self.analyzer.analyze(request.question, request.user)
            controller_state = self.controller.initialize(
                analysis,
                request.user,
                top_k=request.top_k,
                budget=self.budget,
            )
            return {
                "analysis": analysis,
                "controller_state": controller_state,
                "node_trace": nodes,
            }
        except Exception:
            trace = _empty_system_trace()
            return {
                "response": _source_free_response("system", "system_error", trace),
                "node_trace": nodes,
            }

    def _decide_node(self, state: _GraphState) -> dict:
        nodes = [*state["node_trace"], "decide"]
        if state["loop_count"] > self.budget.max_steps + 1:
            return {
                "response": _system_response(state),
                "node_trace": [*nodes, "runaway_guard"],
            }
        try:
            decision = self.controller.next_decision(state["controller_state"])
            return {"decision": decision, "node_trace": nodes}
        except Exception:
            return {"response": _system_response(state), "node_trace": nodes}

    def _execute_node(
        self,
        state: _GraphState,
        tools: _ContractToolSession,
    ) -> dict:
        nodes = [*state["node_trace"], "execute"]
        started = self.clock_ms()
        try:
            execution = tools.run(
                state["decision"].action,
                state["controller_state"].budget_state,
            )
            controller_state = self.controller.observe(
                state["controller_state"],
                execution,
            )
            step = _tool_step_trace(
                execution,
                latency_ms=max(0.0, self.clock_ms() - started),
            )
            return {
                "controller_state": controller_state,
                "step_traces": [*state["step_traces"], step],
                "node_trace": nodes,
                "loop_count": state["loop_count"] + 1,
            }
        except Exception:
            return {"response": _system_response(state), "node_trace": nodes}

    def _publish_node(self, state: _GraphState) -> dict:
        nodes = [*state["node_trace"], "publish"]
        decision = state["decision"]
        controller_state = state["controller_state"]
        steps = [*state["step_traces"], _terminal_step_trace(decision, controller_state)]
        trace = _runtime_trace(state["analysis"], controller_state, decision, steps)
        try:
            response = self.response_builder.build(
                question=state["request"].question,
                state=controller_state,
                mode=decision.terminal_mode,
                stop_reason=decision.stop_reason,
                trace=trace,
            )
        except Exception:
            response = _source_free_response("system", "system_error", trace)
        return {"response": response, "step_traces": steps, "node_trace": nodes}


def _new_tool_session(
    registry: V2ToolRegistry,
    request: AgentRunRequest,
    budget: AgentBudget,
    *,
    clock_ms: ClockMs,
    recorder: TrajectoryRecorder | None = None,
) -> _ContractToolSession:
    issued = float(clock_ms())
    context = ToolContext(
        session_id=request.session_id,
        trace_id=request.trace_id,
        request_id=request.request_id,
        identity=request.user,
        acl_scope=tuple(request.user.groups),
        budget=budget,
        issued_at_ms=issued,
        expires_at_ms=issued + budget.deadline_ms,
    )
    return _ContractToolSession(
        registry,
        context,
        clock_ms=clock_ms,
        recorder=recorder,
    )


def _begin_trajectory(
    store: SQLiteTrajectoryStore | None,
    request: AgentRunRequest,
    orchestrator: OrchestratorName,
) -> TrajectoryRecorder | None:
    if store is None:
        return None
    recorder = TrajectoryRecorder(
        store,
        session_id=request.session_id,
        trace_id=request.trace_id,
    )
    recorder.record(
        "session.started",
        payload={
            "request_id": request.request_id,
            "orchestrator": orchestrator,
            "tenant_id": request.user.tenant_id,
            "user_id": request.user.user_id,
        },
    )
    recorder.record("user.message", payload={"question": request.question})
    return recorder


def _complete_trajectory(
    recorder: TrajectoryRecorder | None,
    response: AnswerResponse,
    orchestrator: OrchestratorName,
) -> None:
    if recorder is None:
        return
    for claim in response.claims:
        payload = {
            "claim_id": claim.claim_id,
            "cited_chunk_ids": claim.cited_chunk_ids,
        }
        recorder.record("claim.proposed", payload=payload)
        recorder.record("claim.accepted", payload=payload)
    for citation in response.citations:
        recorder.record(
            "citation.checked",
            payload=citation.model_dump(mode="json"),
        )
    recorder.record(
        "terminal.reached",
        terminal_reason=response.stop_reason,
        payload={
            "mode": response.mode,
            "answer": response.answer,
            "sources": [
                {
                    "doc_id": source.doc_id,
                    "chunk_id": source.chunk_id,
                    "source_path": source.source_path,
                }
                for source in response.sources
            ],
            "warnings": response.warnings,
        },
    )
    recorder.record(
        "session.completed",
        terminal_reason=response.stop_reason,
        payload={"orchestrator": orchestrator, "mode": response.mode},
    )


def _tool_request_summary(request: ToolRequest) -> dict:
    arguments = request.arguments
    if request.tool == "search":
        return {
            "tool_call_id": arguments.request_id,
            "query": arguments.query,
            "purpose": arguments.purpose,
            "top_k": arguments.top_k,
            "mode": arguments.mode,
        }
    if request.tool == "find":
        return {
            "tool_call_id": arguments.request_id,
            "doc_id": arguments.doc_id,
            "pattern": arguments.pattern,
            "max_results": arguments.max_results,
        }
    return {
        "tool_call_id": arguments.request_id,
        "target_type": arguments.target_type,
        "target_id": arguments.target_id,
        "max_chars": arguments.max_chars,
    }


def _tool_result_summary(execution: GuardedV2ToolExecution) -> dict:
    result = execution.result
    items: list[dict] = []
    if isinstance(result, GuardedSearchResult):
        items = [
            {
                "doc_id": item.hit.doc_id,
                "chunk_id": item.hit.chunk_id,
                "version_id": item.hit.version_id,
                "source_path": item.hit.source_path,
            }
            for item in result.hits
        ]
    elif isinstance(result, GuardedFindResult):
        items = [
            {"doc_id": item.match.doc_id, "chunk_id": item.match.chunk_id}
            for item in result.matches
        ]
    elif isinstance(result, GuardedOpenAdmittedResult):
        item = result.item.result
        items = [
            {
                "doc_id": item.doc_id,
                "target_id": item.target_id,
                "source_path": item.source_path,
            }
        ]
    return {
        "status": execution.status,
        "visible_count": execution.visible_count,
        "items": items,
        "security": execution.security_counters.model_dump(mode="json"),
    }


def _runtime_trace(
    analysis: QueryAnalysis,
    state: ControllerState,
    decision: ControllerDecision,
    steps: list[dict],
) -> dict:
    return _build_trace(
        intent=analysis.intent,
        analysis_source=analysis.source,
        required_aspect_count=len(analysis.required_aspects),
        steps=steps,
        stop_reason=decision.stop_reason,
        budget_state=state.budget_state,
        evidence=_evidence_trace(
            state.ledger,
            required=len(analysis.required_aspects),
            fallback_action=_evidence_action_for_mode(decision.terminal_mode),
        ),
    )


def _system_response(state: _GraphState) -> AnswerResponse:
    analysis = state.get("analysis")
    controller_state = state.get("controller_state")
    if analysis is None or controller_state is None:
        trace = _empty_system_trace()
    else:
        trace = _build_trace(
            intent=analysis.intent,
            analysis_source=analysis.source,
            required_aspect_count=len(analysis.required_aspects),
            steps=state.get("step_traces", []),
            stop_reason="system_error",
            budget_state=controller_state.budget_state,
            evidence=_evidence_trace(
                controller_state.ledger,
                required=len(analysis.required_aspects),
                fallback_action="system",
            ),
        )
    return _source_free_response("system", "system_error", trace)


def _empty_system_trace() -> dict:
    return _build_trace(
        intent="unknown",
        analysis_source="rules",
        required_aspect_count=0,
        steps=[],
        stop_reason="system_error",
        budget_state=None,
        evidence={
            "required": 0,
            "supported": 0,
            "missing": 0,
            "conflicting": 0,
            "coverage": 0.0,
            "recommended_action": "system",
        },
    )


def _route_after_analyze(state: _GraphState) -> Literal["decide", "done"]:
    return "done" if "response" in state else "decide"


def _route_after_decide(
    state: _GraphState,
) -> Literal["execute", "publish", "done"]:
    if "response" in state:
        return "done"
    return "publish" if state["decision"].terminal_mode is not None else "execute"


def _route_after_execute(state: _GraphState) -> Literal["decide", "done"]:
    return "done" if "response" in state else "decide"


__all__ = [
    "AgentOrchestrator",
    "AgentRunRequest",
    "AgentRunResult",
    "BoundedControllerAdapter",
    "LangGraphOrchestratorAdapter",
]
