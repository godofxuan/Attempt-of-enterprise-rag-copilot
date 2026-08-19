from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.tool_contract import (
    ToolContext,
    ToolContractErrorCode,
    ToolError,
    ToolRequest,
    ToolResult,
)
from app.domain.agent import AgentAction, BudgetState, ToolError as DomainToolError
from app.domain.retrieved_security import GuardedV2ToolExecution


ClockMs = Callable[[], float]


@dataclass
class _ActiveToolSession:
    context: ToolContext
    identity_fingerprint: str
    budget_state: BudgetState


class ToolGateway:
    """Fail-closed session boundary in front of the existing guarded registry."""

    def __init__(
        self,
        registry: V2ToolRegistry,
        *,
        clock_ms: ClockMs | None = None,
    ) -> None:
        if not isinstance(registry, V2ToolRegistry):
            raise TypeError("tool gateway requires V2ToolRegistry")
        self._registry = registry
        self._clock_ms = clock_ms or (lambda: time.time() * 1000.0)
        self._sessions: dict[str, _ActiveToolSession] = {}
        self._lock = RLock()

    def start_session(self, context: ToolContext) -> None:
        if not isinstance(context, ToolContext):
            raise TypeError("tool session requires a typed ToolContext")
        now = float(self._clock_ms())
        if now < context.issued_at_ms or now >= context.expires_at_ms:
            raise ValueError("tool context is not currently valid")
        with self._lock:
            if context.session_id in self._sessions:
                raise ValueError("tool session already exists")
            self._sessions[context.session_id] = _ActiveToolSession(
                context=context,
                identity_fingerprint=context.identity_fingerprint(),
                budget_state=BudgetState(
                    budget=context.budget,
                    deadline_at_ms=context.expires_at_ms,
                ),
            )

    def close_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def execute(self, request: ToolRequest, context: ToolContext) -> ToolResult:
        result, _ = self.execute_with_domain(request, context)
        return result

    def execute_with_domain(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> tuple[ToolResult, GuardedV2ToolExecution | None]:
        if not isinstance(request, ToolRequest) or not isinstance(context, ToolContext):
            raise TypeError("gateway requires typed request and context")
        with self._lock:
            session = self._sessions.get(context.session_id)
            if session is None:
                return self._failure(request, context, BudgetState(), "stale_context", "The tool session is not active."), None
            mismatch = self._context_mismatch(session, context)
            if mismatch is not None:
                return self._failure(request, context, session.budget_state, mismatch[0], mismatch[1]), None
            if float(self._clock_ms()) >= context.expires_at_ms:
                return self._failure(request, context, session.budget_state, "stale_context", "The tool session has expired."), None
            if request.tool not in context.allowed_tools:
                return self._failure(request, context, session.budget_state, "unauthorized", "The requested tool is not authorized for this session."), None
            if request.arguments.user != context.identity:
                return self._failure(request, context, session.budget_state, "identity_mismatch", "Tool arguments do not match the authenticated identity."), None
            if request.context_request_id != context.request_id:
                return self._failure(request, context, session.budget_state, "identity_mismatch", "Tool request correlation does not match the trusted context."), None

            action = _to_agent_action(request)
            execution = self._registry.run(action, session.budget_state)
            session.budget_state = execution.budget_state
            if isinstance(execution.result, DomainToolError):
                return self._failure(
                    request,
                    context,
                    execution.budget_state,
                    execution.result.code,
                    execution.result.safe_message,
                    retryable=execution.result.retryable,
                    security_counters=execution.security_counters,
                ), execution
            return ToolResult(
                session_id=context.session_id,
                trace_id=context.trace_id,
                request_id=context.request_id,
                tool=request.tool,
                sequence=request.sequence,
                status="ok",
                payload=execution.result,
                budget_state=execution.budget_state,
                security_counters=execution.security_counters,
            ), execution

    @staticmethod
    def _context_mismatch(
        session: _ActiveToolSession,
        supplied: ToolContext,
    ) -> tuple[ToolContractErrorCode, str] | None:
        expected = session.context
        if supplied.trace_id != expected.trace_id or supplied.request_id != expected.request_id:
            return "identity_mismatch", "Tool session correlation does not match."
        if supplied.identity_fingerprint() != session.identity_fingerprint:
            return "identity_mismatch", "Tool session identity does not match."
        if supplied != expected:
            return "identity_mismatch", "Tool context differs from the server-issued context."
        return None

    @staticmethod
    def _failure(
        request: ToolRequest,
        context: ToolContext,
        state: BudgetState,
        code: ToolContractErrorCode,
        message: str,
        *,
        retryable: bool = False,
        security_counters=None,
    ) -> ToolResult:
        return ToolResult(
            session_id=context.session_id,
            trace_id=context.trace_id,
            request_id=context.request_id,
            tool=request.tool,
            sequence=request.sequence,
            status="error",
            error=ToolError(code=code, retryable=retryable, safe_message=message),
            budget_state=state,
            security_counters=security_counters,
        )


def _to_agent_action(request: ToolRequest) -> AgentAction:
    values = {
        "sequence": request.sequence,
        "tool": request.tool,
        "purpose": request.purpose,
        "aspect": request.aspect,
        f"{request.tool}_request": request.arguments,
    }
    return AgentAction(**values)


__all__ = ["ToolGateway"]
