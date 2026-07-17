from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.observability.tracing import (
    InMemoryTraceStore,
    RequestTrace,
    SpanRecord,
    trace_span,
)
from app.runtime.request_context import (
    bind_request_context,
    current_request_context,
    reset_request_context,
)


def request_trace(request_id: str) -> RequestTrace:
    return RequestTrace(
        request_id=request_id,
        method="POST",
        route="/agent/v2/chat",
        status_code=200,
        duration_ms=12.5,
        outcome="answered",
        model_calls=1,
        model_retries=0,
        model_errors=0,
        spans=[SpanRecord(name="agent.run", status="ok", duration_ms=10.0)],
    )


def test_trace_store_is_bounded_and_returns_latest_record_by_request_id() -> None:
    store = InMemoryTraceStore(max_records=2)

    store.append(request_trace("req-1"))
    store.append(request_trace("req-2"))
    store.append(request_trace("req-3"))

    assert store.get("req-1") is None
    assert store.get("req-2") == request_trace("req-2")
    assert [item.request_id for item in store.recent()] == ["req-2", "req-3"]


def test_trace_models_forbid_content_and_identity_fields() -> None:
    with pytest.raises(ValidationError):
        RequestTrace(
            request_id="req",
            method="POST",
            route="/agent/v2/chat",
            status_code=200,
            duration_ms=1.0,
            outcome="answered",
            model_calls=0,
            model_retries=0,
            model_errors=0,
            spans=[],
            question="PROJECT NIGHTFALL",
        )

    payload = request_trace("req").model_dump(mode="json")
    serialized = json.dumps(payload)
    keys = set(payload)
    for span in payload["spans"]:
        keys.update(span)
    for forbidden in ["question", "answer", "tenant", "groups", "chunk", "doc_id"]:
        assert forbidden not in keys
    assert "PROJECT NIGHTFALL" not in serialized


def test_trace_span_records_only_name_status_and_duration() -> None:
    times = iter([10.0, 35.0])
    token = bind_request_context("req", deadline_ms=1_000, clock_ms=lambda: 0.0)
    try:
        with trace_span("model.chat", clock_ms=lambda: next(times)):
            pass
        context = current_request_context()
        assert context is not None
        assert context.spans == [
            {"name": "model.chat", "status": "ok", "duration_ms": 25.0}
        ]
    finally:
        reset_request_context(token)


def test_trace_span_records_safe_error_status_without_exception_text() -> None:
    times = iter([2.0, 5.0])
    token = bind_request_context("req", deadline_ms=1_000, clock_ms=lambda: 0.0)
    try:
        with pytest.raises(RuntimeError, match="secret"):
            with trace_span("agent.run", clock_ms=lambda: next(times)):
                raise RuntimeError("password=secret-path")
        context = current_request_context()
        assert context is not None
        assert context.spans == [
            {"name": "agent.run", "status": "error", "duration_ms": 3.0}
        ]
        assert "secret-path" not in str(context.spans)
    finally:
        reset_request_context(token)


def test_trace_span_rejects_unbounded_or_content_bearing_names() -> None:
    with pytest.raises(ValueError, match="span name"):
        with trace_span("question.PROJECT_NIGHTFALL"):
            pass
