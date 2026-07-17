from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import InMemoryTraceStore
from app.runtime.resources import (
    ReadinessSnapshot,
    ReadyIndexInfo,
    ServiceContainer,
)


ROUTES = {
    "/health",
    "/health/live",
    "/health/ready",
    "/agent/v2/chat",
    "/agent/chat",
    "/chat",
    "/ingest",
    "/feedback",
    "/observability/metrics",
    "/observability/traces/{request_id}",
}


class FakeResources:
    def __init__(self, snapshot: ReadinessSnapshot | None = None) -> None:
        self.current = snapshot or ready_snapshot()
        self.start_calls = 0
        self.refresh_calls = 0
        self.close_calls = 0

    def start(self) -> ReadinessSnapshot:
        self.start_calls += 1
        return self.current

    def refresh_if_stale(self) -> ReadinessSnapshot:
        self.refresh_calls += 1
        return self.current

    def close(self) -> None:
        self.close_calls += 1


def ready_snapshot() -> ReadinessSnapshot:
    return ReadinessSnapshot(
        status="ready",
        checks={"database": "ok", "index": "ok", "models": "ok"},
        index=ReadyIndexInfo(
            run_id="test-index",
            chunk_count=64,
            embedding_model="bge-m3",
            embedding_dimension=1024,
            build_duration_ms=100,
            index_size_bytes=1_000,
        ),
        checked_at_utc=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )


def not_ready_snapshot() -> ReadinessSnapshot:
    return ReadinessSnapshot(
        status="not_ready",
        checks={"database": "ok", "index": "error", "models": "ok"},
        index=None,
        checked_at_utc=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )


def make_container(
    *,
    resources: FakeResources | None = None,
    trace_buffer_size: int = 20,
) -> ServiceContainer:
    settings = Settings(
        _env_file=None,
        api_request_deadline_ms=5_000,
        trace_buffer_size=max(10, trace_buffer_size),
    )
    return ServiceContainer(
        settings=settings,
        resources=resources or FakeResources(),
        metrics=MetricsRegistry(
            latency_buffer_size=20,
            allowed_routes=ROUTES,
            memory_provider=lambda: 123_456,
        ),
        traces=InMemoryTraceStore(max_records=trace_buffer_size),
    )
