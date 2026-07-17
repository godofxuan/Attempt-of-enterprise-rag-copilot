from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from threading import Lock
from typing import Iterator, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.request_context import current_request_context


SpanName = Literal[
    "agent.run",
    "model.chat",
    "model.embed",
    "feedback.persist",
    "readiness.database",
    "readiness.index",
    "readiness.models",
]
SPAN_NAMES = {
    "agent.run",
    "model.chat",
    "model.embed",
    "feedback.persist",
    "readiness.database",
    "readiness.index",
    "readiness.models",
}


class SpanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SpanName
    status: Literal["ok", "error"]
    duration_ms: float = Field(ge=0)


class RequestTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=64)
    method: str = Field(min_length=1, max_length=16)
    route: str = Field(min_length=1, max_length=200)
    status_code: int = Field(ge=100, le=599)
    duration_ms: float = Field(ge=0)
    outcome: str = Field(min_length=1, max_length=64)
    model_calls: int = Field(ge=0)
    model_retries: int = Field(ge=0)
    model_errors: int = Field(ge=0)
    spans: list[SpanRecord] = Field(default_factory=list, max_length=64)


class TraceSink(Protocol):
    def append(self, trace: RequestTrace) -> None: ...

    def get(self, request_id: str) -> RequestTrace | None: ...


class InMemoryTraceStore:
    def __init__(self, *, max_records: int) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self._records: deque[RequestTrace] = deque(maxlen=max_records)
        self._lock = Lock()

    def append(self, trace: RequestTrace) -> None:
        with self._lock:
            self._records.append(trace)

    def get(self, request_id: str) -> RequestTrace | None:
        with self._lock:
            for trace in reversed(self._records):
                if trace.request_id == request_id:
                    return trace.model_copy(deep=True)
        return None

    def recent(self) -> list[RequestTrace]:
        with self._lock:
            return [trace.model_copy(deep=True) for trace in self._records]


def _clock_ms() -> float:
    return time.monotonic() * 1000.0


@contextmanager
def trace_span(
    name: str,
    *,
    clock_ms: Callable[[], float] | None = None,
) -> Iterator[None]:
    if name not in SPAN_NAMES:
        raise ValueError("span name is not allowed")
    clock = clock_ms or _clock_ms
    started = float(clock())
    status: Literal["ok", "error"] = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        context = current_request_context()
        if context is not None:
            context.spans.append(
                {
                    "name": name,
                    "status": status,
                    "duration_ms": max(0.0, float(clock()) - started),
                }
            )


__all__ = [
    "InMemoryTraceStore",
    "RequestTrace",
    "SPAN_NAMES",
    "SpanName",
    "SpanRecord",
    "TraceSink",
    "trace_span",
]
