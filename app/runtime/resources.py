from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field
from urllib3.util import Timeout

from app.config import Settings
from app.db import ContentDigest, check_db, init_db
from app.observability.metrics import MetricsRegistry
from app.observability.tracing import InMemoryTraceStore
from app.observability.tracing import trace_span
from app.retrieval.snapshot import V2IndexSnapshot
from app.security.retrieved_content import validate_retrieved_content_guard
from app.security.identity import (
    FeedbackActorPseudonymizer,
    IdentityVerifier,
    build_feedback_actor_hasher,
    build_identity_verifier,
)


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
    checks: dict[
        Literal["database", "index", "models", "identity"],
        Literal["ok", "error"],
    ]
    retrieved_guard: Literal["ready", "error"]
    index: ReadyIndexInfo | None = None
    checked_at_utc: datetime


DatabaseProbe = Callable[[], None]
DatabaseInitializer = Callable[[], None]
IndexProbe = Callable[[], ReadyIndexInfo]
ModelProbe = Callable[[ReadyIndexInfo], None]
GuardProbe = Callable[[], None]
GuardValidator = Callable[[], None]
IdentityProbe = Callable[[], None]

SECURE_ROUTE_TEMPLATES = frozenset(
    {
        "/health",
        "/health/live",
        "/health/ready",
        "/agent/v2/chat",
        "/feedback",
        "/identity/me",
        "/observability/metrics",
        "/observability/traces/{request_id}",
    }
)
DEFAULT_ROUTE_TEMPLATES = SECURE_ROUTE_TEMPLATES


@dataclass(frozen=True)
class ServiceContainer:
    settings: Settings
    resources: Any
    metrics: MetricsRegistry
    traces: InMemoryTraceStore
    identity_verifier: IdentityVerifier
    feedback_actor_hasher: FeedbackActorPseudonymizer


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
    identity_verifier = build_identity_verifier(settings)
    feedback_actor_hasher = build_feedback_actor_hasher(settings)

    def identity_probe() -> None:
        identity_verifier.ready()
        feedback_actor_hasher.ready()

    return ServiceContainer(
        settings=settings,
        resources=RuntimeResources(
            settings,
            identity_probe=identity_probe,
            database_content_digest=feedback_actor_hasher.content_digest,
        ),
        metrics=MetricsRegistry(
            latency_buffer_size=settings.metrics_latency_buffer_size,
            allowed_routes=DEFAULT_ROUTE_TEMPLATES,
        ),
        traces=InMemoryTraceStore(max_records=settings.trace_buffer_size),
        identity_verifier=identity_verifier,
        feedback_actor_hasher=feedback_actor_hasher,
    )


class RuntimeResources:
    def __init__(
        self,
        settings: Settings | Any,
        *,
        database_initializer: DatabaseInitializer | None = None,
        database_probe: DatabaseProbe | None = None,
        index_probe: IndexProbe | None = None,
        model_probe: ModelProbe | None = None,
        guard_probe: GuardProbe | None = None,
        identity_probe: IdentityProbe | None = None,
        database_content_digest: ContentDigest | None = None,
        clock: Callable[[], float] = time.monotonic,
        deadline_clock: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self._database_initializer = (
            database_initializer
            or (
                (lambda: None)
                if database_probe is not None
                else self._initialize_database
            )
        )
        self._database_probe = database_probe or self._probe_database
        self._index_probe = index_probe or self._probe_index
        self._model_probe: ModelProbe = (
            self._probe_models
            if model_probe is None
            else lambda _index_info: model_probe()
        )
        self._guard_probe = guard_probe or self._probe_guard
        self._identity_probe = identity_probe or self._probe_identity
        self._database_content_digest = database_content_digest
        self._clock = clock
        self._deadline_clock = deadline_clock
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self._snapshot: ReadinessSnapshot | None = None
        self._last_checked_at: float | None = None
        self._database_initialization_failed = False
        self._database_initialization_attempted = False
        self._refresh_lock = threading.RLock()
        self._refresh_thread: threading.Thread | None = None
        self._refresh_wakeup = threading.Event()
        self._refresh_completed = threading.Event()
        self._stop_refresh = threading.Event()
        self.started = False
        self.closed = False

    def start(self) -> ReadinessSnapshot:
        with self._refresh_lock:
            self.started = True
            self.closed = False
            self._stop_refresh.clear()
            self._refresh_wakeup.clear()
            self._refresh_completed.clear()
            self._snapshot = self._unavailable_snapshot()
            self._last_checked_at = None
            initial = self._snapshot
        self.refresh_in_background()
        return initial

    def refresh_if_stale(self) -> ReadinessSnapshot:
        with self._refresh_lock:
            if self._snapshot is None:
                return self._unavailable_snapshot()
            if self._last_checked_at is None:
                return self._snapshot
            age = self._clock() - self._last_checked_at
            if age >= float(self.settings.readiness_ttl_seconds):
                return self._unavailable_snapshot(
                    checked_at_utc=self._snapshot.checked_at_utc
                )
            return self._snapshot

    def refresh_in_background(self) -> bool:
        with self._refresh_lock:
            if self.closed or not self.started:
                return False
            self._refresh_completed.clear()
            thread = self._refresh_thread
            if thread is not None and thread.is_alive():
                self._refresh_wakeup.set()
                return True
            thread = threading.Thread(
                target=self._background_refresh_loop,
                name="rag-readiness-refresh",
                daemon=True,
            )
            self._refresh_thread = thread
        thread.start()
        return True

    def wait_for_refresh(self, timeout: float) -> bool:
        return self._refresh_completed.wait(timeout=max(0.0, timeout))

    def close(self) -> None:
        with self._refresh_lock:
            if self.closed:
                return
            self.closed = True
            self._stop_refresh.set()
            self._refresh_wakeup.set()
            thread = self._refresh_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(
                timeout=float(
                    getattr(
                        self.settings,
                        "readiness_probe_timeout_seconds",
                        1.0,
                    )
                )
            )

    def _background_refresh_loop(self) -> None:
        if not self._database_initialization_attempted:
            try:
                self._database_initializer()
                self._database_initialization_failed = False
            except Exception:
                self._database_initialization_failed = True
            finally:
                self._database_initialization_attempted = True

        while not self._stop_refresh.is_set():
            snapshot = self._collect_snapshot()
            with self._refresh_lock:
                if self.closed or self._stop_refresh.is_set():
                    return
                self._snapshot = snapshot
                self._last_checked_at = self._clock()
                self._refresh_completed.set()
            self._refresh_wakeup.wait(
                timeout=float(self.settings.readiness_ttl_seconds)
            )
            self._refresh_wakeup.clear()

    def _collect_snapshot(self) -> ReadinessSnapshot:
        checks: dict[str, str] = {}
        index_info: ReadyIndexInfo | None = None
        for name, span_name, probe in (
            ("database", "readiness.database", self._database_probe),
            ("index", "readiness.index", self._index_probe),
            (
                "models",
                "readiness.models",
                lambda: self._model_probe(index_info)
                if index_info is not None
                else _raise_index_unavailable_for_model_probe(),
            ),
            ("identity", "readiness.identity", self._identity_probe),
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
        return ReadinessSnapshot(
            status="ready" if ready else "not_ready",
            checks=checks,
            retrieved_guard=guard_status,
            index=index_info if ready else None,
            checked_at_utc=self._utcnow(),
        )

    def _unavailable_snapshot(
        self,
        *,
        checked_at_utc: datetime | None = None,
    ) -> ReadinessSnapshot:
        return ReadinessSnapshot(
            status="not_ready",
            checks={
                "database": "error",
                "index": "error",
                "models": "error",
                "identity": "error",
            },
            retrieved_guard="error",
            index=None,
            checked_at_utc=checked_at_utc or self._utcnow(),
        )

    def _initialize_database(self) -> None:
        init_db(
            self.settings,
            content_digest=self._database_content_digest,
        )

    def _probe_database(self) -> None:
        if self._database_initialization_failed:
            raise RuntimeError("database initialization failed")
        if not check_db(self.settings):
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

    def _probe_models(self, index_info: ReadyIndexInfo) -> None:
        parsed = urlparse(self.settings.llm_base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        connect_timeout = float(
            self.settings.readiness_probe_timeout_seconds
        )
        deadline = self._deadline_clock() + float(
            self.settings.readiness_model_load_timeout_seconds
        )

        def request_timeout() -> Timeout:
            remaining = deadline - self._deadline_clock()
            if remaining <= 0:
                raise RuntimeError("model readiness probe deadline exceeded")
            return Timeout(
                total=remaining,
                connect=min(connect_timeout, remaining),
            )

        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                f"{origin}/api/tags",
                timeout=request_timeout(),
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
                _base_model_name(self.settings.evidence_model),
            }
            if not required.issubset(available):
                raise RuntimeError("required models are unavailable")

            response = session.post(
                f"{origin}/api/embed",
                json={
                    "model": self.settings.embedding_model,
                    "input": "readiness",
                },
                timeout=request_timeout(),
            )
            response.raise_for_status()
            _require_embedding_probe_payload(
                response.json(),
                expected_dimension=index_info.embedding_dimension,
            )

            generation_models = dict.fromkeys(
                (
                    self.settings.chat_model,
                    self.settings.evidence_model,
                )
            )
            for model in generation_models:
                response = session.post(
                    f"{origin}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Reply with OK.",
                            }
                        ],
                        "stream": False,
                        "keep_alive": "5m",
                        "options": {"temperature": 0},
                    },
                    timeout=request_timeout(),
                )
                response.raise_for_status()
                _require_chat_probe_payload(response.json())

    def _probe_guard(self) -> None:
        validate_retrieved_content_guard()

    def _probe_identity(self) -> None:
        raise RuntimeError("identity boundary was not configured")


def _base_model_name(value: str) -> str:
    normalized = value.strip()
    return normalized[:-7] if normalized.endswith(":latest") else normalized


def _require_embedding_probe_payload(
    payload: Any,
    *,
    expected_dimension: int,
) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("embedding model probe returned invalid data")
    embeddings = payload.get("embeddings")
    if (
        not isinstance(embeddings, list)
        or len(embeddings) != 1
        or not isinstance(embeddings[0], list)
        or len(embeddings[0]) != expected_dimension
        or any(
            type(value) not in {int, float}
            or not math.isfinite(float(value))
            for value in embeddings[0]
        )
    ):
        raise RuntimeError("embedding model probe returned invalid data")


def _require_chat_probe_payload(payload: Any) -> None:
    message = payload.get("message") if isinstance(payload, dict) else None
    if (
        not isinstance(message, dict)
        or not isinstance(message.get("content"), str)
        or not message["content"].strip()
    ):
        raise RuntimeError("chat model probe returned invalid data")


def _raise_index_unavailable_for_model_probe() -> None:
    raise RuntimeError("active index is unavailable for model probe")


__all__ = [
    "DEFAULT_ROUTE_TEMPLATES",
    "ReadinessSnapshot",
    "ReadyIndexInfo",
    "RuntimeResources",
    "SECURE_ROUTE_TEMPLATES",
    "ServiceContainer",
    "build_service_container",
]
