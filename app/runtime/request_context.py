from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


ClockMs = Callable[[], float]


class RequestDeadlineExceeded(RuntimeError):
    pass


@dataclass
class RequestContext:
    request_id: str
    started_at_ms: float
    deadline_at_ms: float
    spans: list[dict[str, object]] = field(default_factory=list)
    model_calls: int = 0
    model_retries: int = 0
    model_errors: int = 0


_CURRENT_REQUEST: ContextVar[RequestContext | None] = ContextVar(
    "enterprise_rag_request_context",
    default=None,
)


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
