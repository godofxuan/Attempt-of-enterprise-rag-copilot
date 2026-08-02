from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import InMemoryTraceStore
from app.runtime.resources import (
    ReadinessSnapshot,
    ReadyIndexInfo,
    ServiceContainer,
)
from app.runtime.dark_observation import (
    DarkObservationConfig,
    DarkObservationService,
)
from app.security.identity import (
    AuthenticationFailure,
    FeedbackActorHasher,
    IdentityVerifier,
    Principal,
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
    "/identity/me",
    "/observability/metrics",
    "/observability/traces/{request_id}",
}

USER_HEADERS = {"Authorization": "Bearer user-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer operator-token"}


class StaticIdentityVerifier:
    def ready(self) -> None:
        return None

    def verify_bearer(self, authorization: str | None) -> Principal:
        if authorization is None:
            raise AuthenticationFailure("authentication_required")
        if authorization not in {
            USER_HEADERS["Authorization"],
            OPERATOR_HEADERS["Authorization"],
        }:
            raise AuthenticationFailure("invalid_token")
        now = datetime.now(timezone.utc)
        return Principal(
            subject="operator-one" if "operator" in authorization else "employee-one",
            tenant_id="tenant-one",
            region="cn",
            groups=["employees"],
            roles=["rag.operator"] if "operator" in authorization else [],
            issuer="https://identity.localhost/",
            audience="enterprise-rag-api",
            key_id="test-key-1",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )


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
        checks={"database": "ok", "index": "ok", "models": "ok", "identity": "ok"},
        retrieved_guard="ready",
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
        checks={"database": "ok", "index": "error", "models": "ok", "identity": "ok"},
        retrieved_guard="ready",
        index=None,
        checked_at_utc=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )


def make_container(
    *,
    resources: FakeResources | None = None,
    trace_buffer_size: int = 20,
    identity_verifier: IdentityVerifier | None = None,
    dark_observation: DarkObservationService | None = None,
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
        identity_verifier=identity_verifier or StaticIdentityVerifier(),
        feedback_actor_hasher=FeedbackActorHasher(_key=b"test-feedback-key" * 2),
        dark_observation=dark_observation
        or DarkObservationService(DarkObservationConfig()),
    )
