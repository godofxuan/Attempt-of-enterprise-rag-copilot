from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.db import check_db, init_db
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import InMemoryTraceStore
from app.observability.tracing import trace_span
from app.retrieval.snapshot import V2IndexSnapshot
from app.security.retrieved_content import validate_retrieved_content_guard


class ReadyIndexInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    run_id: str = Field(min_length=1, max_length=200)
    chunk_count: int = Field(ge=0)
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_dimension: int = Field(ge=1)
    build_duration_ms: int = Field(ge=0)
    index_size_bytes: int = Field(ge=0)


class ReadinessSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    checks: dict[Literal["database", "index", "models"], Literal["ok", "error"]]
    retrieved_guard: Literal["ready", "error"]
    index: ReadyIndexInfo | None = None
    checked_at_utc: datetime


DatabaseProbe = Callable[[], None]
IndexProbe = Callable[[], ReadyIndexInfo]
ModelProbe = Callable[[], None]
GuardProbe = Callable[[], None]
GuardValidator = Callable[[], None]

SECURE_ROUTE_TEMPLATES = frozenset(
    {
        "/health",
        "/health/live",
        "/health/ready",
        "/agent/v2/chat",
        "/feedback",
        "/observability/metrics",
        "/observability/traces/{request_id}",
    }
)
LEGACY_ROUTE_TEMPLATES = frozenset({"/ingest", "/chat", "/agent/chat"})
COMPATIBILITY_ROUTE_TEMPLATES = SECURE_ROUTE_TEMPLATES | LEGACY_ROUTE_TEMPLATES
DEFAULT_ROUTE_TEMPLATES = SECURE_ROUTE_TEMPLATES


@dataclass(frozen=True)
class ServiceContainer:
    settings: Settings
    resources: Any
    metrics: MetricsRegistry
    traces: InMemoryTraceStore


def build_service_container(
    settings: Settings,
    *,
    guard_validator: GuardValidator | None = None,
) -> ServiceContainer:
    validator = guard_validator or validate_retrieved_content_guard
    try:
        validator()
    except Exception:
        raise RuntimeError(
            "retrieved-content guard policy validation failed"
        ) from None
    return ServiceContainer(
        settings=settings,
        resources=RuntimeResources(settings),
        metrics=MetricsRegistry(
            latency_buffer_size=settings.metrics_latency_buffer_size,
            allowed_routes=DEFAULT_ROUTE_TEMPLATES,
        ),
        traces=InMemoryTraceStore(max_records=settings.trace_buffer_size),
    )


class RuntimeResources:
    def __init__(
        self,
        settings: Settings | Any,
        *,
        database_probe: DatabaseProbe | None = None,
        index_probe: IndexProbe | None = None,
        model_probe: ModelProbe | None = None,
        guard_probe: GuardProbe | None = None,
        clock: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self._database_probe = database_probe or self._probe_database
        self._index_probe = index_probe or self._probe_index
        self._model_probe = model_probe or self._probe_models
        self._guard_probe = guard_probe or self._probe_guard
        self._clock = clock
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self._snapshot: ReadinessSnapshot | None = None
        self._last_checked_at: float | None = None
        self.started = False
        self.closed = False

    def start(self) -> ReadinessSnapshot:
        self.started = True
        self.closed = False
        return self._refresh()

    def refresh_if_stale(self) -> ReadinessSnapshot:
        if self._snapshot is None or self._last_checked_at is None:
            return self._refresh()
        age = self._clock() - self._last_checked_at
        if age >= float(self.settings.readiness_ttl_seconds):
            return self._refresh()
        return self._snapshot

    def close(self) -> None:
        self.closed = True

    def _refresh(self) -> ReadinessSnapshot:
        checks: dict[str, str] = {}
        index_info: ReadyIndexInfo | None = None
        for name, span_name, probe in (
            ("database", "readiness.database", self._database_probe),
            ("index", "readiness.index", self._index_probe),
            ("models", "readiness.models", self._model_probe),
        ):
            try:
                with trace_span(span_name):
                    result = probe()
                checks[name] = "ok"
                if name == "index":
                    index_info = result
            except Exception:
                checks[name] = "error"
                if name == "index":
                    index_info = None
        guard_status: Literal["ready", "error"] = "ready"
        try:
            with trace_span("readiness.retrieved_guard"):
                self._guard_probe()
        except Exception:
            guard_status = "error"
        ready = (
            all(value == "ok" for value in checks.values())
            and guard_status == "ready"
        )
        self._snapshot = ReadinessSnapshot(
            status="ready" if ready else "not_ready",
            checks=checks,
            retrieved_guard=guard_status,
            index=index_info if ready else None,
            checked_at_utc=self._utcnow(),
        )
        self._last_checked_at = self._clock()
        return self._snapshot

    def _probe_database(self) -> None:
        init_db()
        if not check_db():
            raise RuntimeError("database probe failed")

    def _probe_index(self) -> ReadyIndexInfo:
        snapshot = V2IndexSnapshot.load(self.settings.v2_indexes_dir)
        manifest = snapshot.version.manifest
        return ReadyIndexInfo(
            run_id=manifest.run_id,
            chunk_count=manifest.indexed_chunk_count,
            embedding_model=manifest.embedding.model,
            embedding_dimension=manifest.embedding.dimension,
            build_duration_ms=manifest.duration_ms,
            index_size_bytes=sum(item.byte_count for item in manifest.artifacts),
        )

    def _probe_models(self) -> None:
        parsed = urlparse(self.settings.llm_base_url)
        url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
        session = requests.Session()
        session.trust_env = False
        response = session.get(
            url,
            timeout=self.settings.readiness_probe_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        available = {
            _base_model_name(item.get("name", ""))
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        required = {
            _base_model_name(self.settings.embedding_model),
            _base_model_name(self.settings.chat_model),
        }
        if not required.issubset(available):
            raise RuntimeError("required models are unavailable")

    def _probe_guard(self) -> None:
        validate_retrieved_content_guard()


def _base_model_name(value: str) -> str:
    normalized = value.strip()
    return normalized[:-7] if normalized.endswith(":latest") else normalized


__all__ = [
    "COMPATIBILITY_ROUTE_TEMPLATES",
    "DEFAULT_ROUTE_TEMPLATES",
    "LEGACY_ROUTE_TEMPLATES",
    "ReadinessSnapshot",
    "ReadyIndexInfo",
    "RuntimeResources",
    "SECURE_ROUTE_TEMPLATES",
    "ServiceContainer",
    "build_service_container",
]
