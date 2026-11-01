from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, Lock
from uuid import uuid4

ClockMs = Callable[[], float]


class RequestDeadlineExceeded(RuntimeError):
    pass


class ModelBudgetExceeded(RuntimeError):
    pass


@dataclass
class ActualModelBudget:
    policy_limit: int = 4
    generation_limit: int = 2
    total_limit: int = 6
    counts: dict[str, int] = field(default_factory=lambda: {"policy": 0, "generation": 0})
    attempts: list[dict] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock, repr=False)

    def reserve(self, purpose):
        with self.lock:
            limit = self.policy_limit if purpose == "policy" else self.generation_limit
            if self.counts[purpose] >= limit or sum(self.counts.values()) >= self.total_limit:
                raise ModelBudgetExceeded("actual model request budget exhausted")
            self.counts[purpose] += 1
            attempt_id = uuid4().hex
            self.attempts.append({"attempt_id": attempt_id, "purpose": purpose, "status": "reserved"})
            return attempt_id


@dataclass
class RequestContext:
    request_id: str
    started_at_ms: float
    deadline_at_ms: float
    spans: list[dict[str, object]] = field(default_factory=list)
    model_calls: int = 0
    model_retries: int = 0
    model_errors: int = 0
    cancelled: Event = field(default_factory=Event, repr=False)
    execution_nonce: str = field(default_factory=lambda: uuid4().hex)
    attempt_budget: ActualModelBudget | None = None
    model_attempts: list[dict] = field(default_factory=list)


_CURRENT_REQUEST: ContextVar[RequestContext | None] = ContextVar(
    "enterprise_rag_request_context",
    default=None,
)
_MODEL_PURPOSE = ContextVar("model_purpose", default="generation")
_MODEL_CALL_DEADLINE = ContextVar("model_call_deadline", default=None)
_MODEL_SEND_OBSERVER = ContextVar("model_send_observer", default=None)


@contextmanager
def model_purpose(purpose: str, *, timeout_seconds: float | None = None):
    if purpose not in {"policy", "generation"}:
        raise ValueError("unknown model purpose")
    token = _MODEL_PURPOSE.set(purpose)
    deadline = _MODEL_CALL_DEADLINE.set(None if timeout_seconds is None else time.monotonic()+timeout_seconds)
    try:
        yield
    finally:
        _MODEL_CALL_DEADLINE.reset(deadline)
        _MODEL_PURPOSE.reset(token)


@contextmanager
def model_send_observer(observer):
    """Evaluation-only hook; observer may reject before any network send."""
    token = _MODEL_SEND_OBSERVER.set(observer)
    try:
        yield
    finally:
        _MODEL_SEND_OBSERVER.reset(token)


def reserve_model_send(operation, *, clock_ms=None):
    context = current_request_context()
    if remaining_seconds(clock_ms=clock_ms) == 0:
        raise RequestDeadlineExceeded("request cancelled or expired")
    purpose = _MODEL_PURPOSE.get() if operation == "chat" else "embedding"
    attempt_id = uuid4().hex
    if context is not None and context.attempt_budget is not None and operation == "chat":
        attempt_id = context.attempt_budget.reserve(purpose)
    observer = _MODEL_SEND_OBSERVER.get()
    if observer is not None:
        observer({"operation": operation, "purpose": purpose, "attempt_id": attempt_id})
    return attempt_id, purpose


def model_call_remaining():
    deadline = _MODEL_CALL_DEADLINE.get()
    return None if deadline is None else max(0, deadline-time.monotonic())


def _default_clock_ms() -> float:
    return time.monotonic() * 1000.0


def bind_request_context(
    request_id: str,
    *,
    deadline_ms: int | float,
    clock_ms: ClockMs | None = None,
) -> Token[RequestContext | None]:
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request ID must be a non-empty string")
    if not isinstance(deadline_ms, (int, float)) or deadline_ms <= 0:
        raise ValueError("deadline must be positive")
    clock = clock_ms or _default_clock_ms
    started_at = float(clock())
    context = RequestContext(
        request_id=request_id.strip(),
        started_at_ms=started_at,
        deadline_at_ms=started_at + float(deadline_ms),
    )
    return _CURRENT_REQUEST.set(context)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _CURRENT_REQUEST.reset(token)


def current_request_context() -> RequestContext | None:
    return _CURRENT_REQUEST.get()


def current_request_id() -> str | None:
    context = current_request_context()
    return context.request_id if context is not None else None


def remaining_seconds(*, clock_ms: ClockMs | None = None) -> float | None:
    context = current_request_context()
    if context is None:
        return None
    if context.cancelled.is_set():
        return 0.0
    clock = clock_ms or _default_clock_ms
    return max(0.0, (context.deadline_at_ms - float(clock())) / 1000.0)


def effective_timeout_seconds(
    configured_seconds: float,
    *,
    clock_ms: ClockMs | None = None,
) -> float:
    if configured_seconds <= 0:
        raise ValueError("configured timeout must be positive")
    remaining = remaining_seconds(clock_ms=clock_ms)
    if remaining is None:
        return float(configured_seconds)
    if remaining <= 0:
        raise RequestDeadlineExceeded("request deadline exhausted")
    return min(float(configured_seconds), remaining)


__all__ = [
    "ClockMs",
    "RequestContext",
    "RequestDeadlineExceeded",
    "bind_request_context",
    "current_request_context",
    "current_request_id",
    "effective_timeout_seconds",
    "remaining_seconds",
    "reset_request_context",
]
