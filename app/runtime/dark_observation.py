from __future__ import annotations

import hashlib
import hmac
import math
import queue
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol


DarkObservationMode = Literal["OFF", "LOCAL_TEST_ONLY"]
DarkObservationProviderOutcome = Literal["MATCH", "DIFFERENT", "NOT_APPLICABLE"]
DarkObservationOfferOutcome = Literal[
    "ADMITTED",
    "DISABLED",
    "SAMPLE_SKIPPED",
    "UNAVAILABLE",
    "BACKPRESSURE",
    "CLOSED",
]

_COUNTER_NAMES = (
    "offered_total",
    "disabled_total",
    "sample_skipped_total",
    "unavailable_total",
    "admitted_total",
    "backpressure_total",
    "closed_rejected_total",
    "execution_started_total",
    "completed_total",
    "provider_error_total",
    "deadline_exceeded_total",
    "shutdown_cancelled_total",
)
_PROVIDER_OUTCOMES: tuple[DarkObservationProviderOutcome, ...] = (
    "MATCH",
    "DIFFERENT",
    "NOT_APPLICABLE",
)


@dataclass(frozen=True)
class DarkObservationRequest:
    request_id: str
    question: str
    primary_mode: str
    primary_stop_reason: str | None


class DarkObservationProvider(Protocol):
    def observe(
        self,
        request: DarkObservationRequest,
        *,
        deadline_monotonic: float,
    ) -> DarkObservationProviderOutcome: ...


@dataclass(frozen=True)
class DarkObservationConfig:
    mode: DarkObservationMode = "OFF"
    sample_basis_points: int = 0
    worker_count: int = 1
    queue_capacity: int = 8
    observation_deadline_ms: int = 100
    shutdown_grace_ms: int = 2_000
    latency_buffer_size: int = 1_000

    def __post_init__(self) -> None:
        if self.mode not in {"OFF", "LOCAL_TEST_ONLY"}:
            raise ValueError("unsupported dark-observation mode")
        if not 0 <= self.sample_basis_points <= 10_000:
            raise ValueError("sample_basis_points must be between 0 and 10000")
        if self.mode == "OFF" and self.sample_basis_points != 0:
            raise ValueError("OFF mode requires zero sampling")
        if self.mode == "LOCAL_TEST_ONLY" and self.sample_basis_points == 0:
            raise ValueError("LOCAL_TEST_ONLY mode requires nonzero sampling")
        if not 1 <= self.worker_count <= 8:
            raise ValueError("worker_count must be between 1 and 8")
        if not 1 <= self.queue_capacity <= 256:
            raise ValueError("queue_capacity must be between 1 and 256")
        if not 1 <= self.observation_deadline_ms <= 60_000:
            raise ValueError("observation_deadline_ms is out of range")
        if not 1 <= self.shutdown_grace_ms <= 60_000:
            raise ValueError("shutdown_grace_ms is out of range")
        if not 10 <= self.latency_buffer_size <= 100_000:
            raise ValueError("latency_buffer_size is out of range")


@dataclass(frozen=True)
class _QueuedObservation:
    request: DarkObservationRequest
    deadline_monotonic: float


class DarkObservationService:
    """Best-effort dark execution that cannot participate in primary decisions."""

    def __init__(
        self,
        config: DarkObservationConfig,
        *,
        provider: DarkObservationProvider | None = None,
        sampling_key: bytes | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if sampling_key is not None and len(sampling_key) < 16:
            raise ValueError("sampling_key must contain at least 16 bytes")
        self.config = config
        self._provider = provider
        self._sampling_key = sampling_key or secrets.token_bytes(32)
        self._clock = clock
        self._queue: queue.Queue[_QueuedObservation] = queue.Queue(
            maxsize=config.queue_capacity
        )
        self._state_lock = threading.RLock()
        self._metrics_lock = threading.Lock()
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._started = False
        self._closed = False
        self._counters = {name: 0 for name in _COUNTER_NAMES}
        self._provider_outcomes = {name: 0 for name in _PROVIDER_OUTCOMES}
        self._offer_latencies_ms: list[float] = []
        self._execution_latencies_ms: list[float] = []
        self._active_workers = 0
        self._active_worker_high_watermark = 0
        self._queue_high_watermark = 0

    def start(self) -> None:
        with self._state_lock:
            if self._closed or self._started:
                return
            self._started = True
            if self.config.mode == "OFF" or self._provider is None:
                return
            self._stop.clear()
            self._workers = [
                threading.Thread(
                    target=self._worker_loop,
                    name=f"rag-dark-observation-{index}",
                    daemon=True,
                )
                for index in range(self.config.worker_count)
            ]
            workers = tuple(self._workers)
        for worker in workers:
            worker.start()

    def offer(
        self,
        *,
        request_id: str,
        question: str,
        primary_mode: str,
        primary_stop_reason: str | None,
    ) -> DarkObservationOfferOutcome:
        started_at = self._clock()
        self._increment("offered_total")
        outcome: DarkObservationOfferOutcome
        try:
            if self.config.mode == "OFF":
                self._increment("disabled_total")
                outcome = "DISABLED"
            else:
                with self._state_lock:
                    started = self._started
                    closed = self._closed
                    provider_available = self._provider is not None
                if closed:
                    self._increment("closed_rejected_total")
                    outcome = "CLOSED"
                elif not started or not provider_available:
                    self._increment("unavailable_total")
                    outcome = "UNAVAILABLE"
                elif not self._selected(request_id):
                    self._increment("sample_skipped_total")
                    outcome = "SAMPLE_SKIPPED"
                else:
                    item = _QueuedObservation(
                        request=DarkObservationRequest(
                            request_id=request_id,
                            question=question,
                            primary_mode=primary_mode,
                            primary_stop_reason=primary_stop_reason,
                        ),
                        deadline_monotonic=(
                            started_at
                            + (self.config.observation_deadline_ms / 1_000.0)
                        ),
                    )
                    try:
                        self._queue.put_nowait(item)
                    except queue.Full:
                        self._increment("backpressure_total")
                        outcome = "BACKPRESSURE"
                    else:
                        self._increment("admitted_total")
                        self._record_queue_high_watermark(self._queue.qsize())
                        outcome = "ADMITTED"
            return outcome
        finally:
            self._record_latency(
                self._offer_latencies_ms,
                max(0.0, (self._clock() - started_at) * 1_000.0),
            )

    def close(self) -> dict[str, int]:
        with self._state_lock:
            if self._closed:
                workers = tuple(self._workers)
            else:
                self._closed = True
                self._stop.set()
                workers = tuple(self._workers)
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            else:
                self._increment("shutdown_cancelled_total")
                self._queue.task_done()

        deadline = self._clock() + (self.config.shutdown_grace_ms / 1_000.0)
        for worker in workers:
            if worker is threading.current_thread():
                continue
            worker.join(timeout=max(0.0, deadline - self._clock()))
        residual = sum(worker.is_alive() for worker in workers)
        return {
            "workers_started": len(workers),
            "workers_stopped": len(workers) - residual,
            "residual_workers": residual,
        }

    def snapshot(self) -> dict[str, object]:
        with self._state_lock:
            if self.config.mode == "OFF":
                status = "OFF"
            elif self._closed:
                status = "CLOSED"
            elif self._provider is None:
                status = "UNAVAILABLE"
            elif self._started:
                status = "RUNNING"
            else:
                status = "NOT_STARTED"
            workers_alive = sum(worker.is_alive() for worker in self._workers)
        with self._metrics_lock:
            counters = dict(self._counters)
            outcomes = dict(self._provider_outcomes)
            offer_latencies = tuple(self._offer_latencies_ms)
            execution_latencies = tuple(self._execution_latencies_ms)
            active_workers = self._active_workers
            active_hwm = self._active_worker_high_watermark
            queue_hwm = self._queue_high_watermark
        return {
            "schema_version": "dark_observation_metrics_v1",
            "mode": self.config.mode,
            "status": status,
            "sampling_basis_points": self.config.sample_basis_points,
            "worker_count": self.config.worker_count,
            "queue_capacity": self.config.queue_capacity,
            "observation_deadline_ms": self.config.observation_deadline_ms,
            "content_retained": False,
            "counters": counters,
            "provider_outcomes": outcomes,
            "high_watermarks": {
                "active_workers": active_hwm,
                "queued_observations": queue_hwm,
            },
            "current": {
                "active_workers": active_workers,
                "queued_observations": self._queue.qsize(),
                "workers_alive": workers_alive,
            },
            "offer_latency_ms": _latency_summary(offer_latencies),
            "execution_latency_ms": _latency_summary(execution_latencies),
        }

    def _selected(self, request_id: str) -> bool:
        digest = hmac.new(
            self._sampling_key,
            request_id.encode("utf-8", errors="strict"),
            hashlib.sha256,
        ).digest()
        bucket = int.from_bytes(digest[:8], "big") % 10_000
        return bucket < self.config.sample_basis_points

    def _worker_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.02)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            if self._stop.is_set():
                self._increment("shutdown_cancelled_total")
                self._queue.task_done()
                return
            self._run_one(item)
            self._queue.task_done()

    def _run_one(self, item: _QueuedObservation) -> None:
        now = self._clock()
        if now >= item.deadline_monotonic:
            self._increment("deadline_exceeded_total")
            return
        with self._metrics_lock:
            self._active_workers += 1
            self._active_worker_high_watermark = max(
                self._active_worker_high_watermark,
                self._active_workers,
            )
            self._counters["execution_started_total"] += 1
        started_at = now
        try:
            provider = self._provider
            if provider is None:
                self._increment("provider_error_total")
                return
            outcome = provider.observe(
                item.request,
                deadline_monotonic=item.deadline_monotonic,
            )
            completed_at = self._clock()
            if completed_at > item.deadline_monotonic:
                self._increment("deadline_exceeded_total")
                return
            if outcome not in _PROVIDER_OUTCOMES:
                self._increment("provider_error_total")
                return
            with self._metrics_lock:
                self._counters["completed_total"] += 1
                self._provider_outcomes[outcome] += 1
        except Exception:
            self._increment("provider_error_total")
        finally:
            elapsed_ms = max(0.0, (self._clock() - started_at) * 1_000.0)
            with self._metrics_lock:
                self._active_workers -= 1
                self._append_bounded(self._execution_latencies_ms, elapsed_ms)

    def _increment(self, name: str) -> None:
        with self._metrics_lock:
            self._counters[name] += 1

    def _record_queue_high_watermark(self, size: int) -> None:
        with self._metrics_lock:
            self._queue_high_watermark = max(self._queue_high_watermark, size)

    def _record_latency(self, values: list[float], latency_ms: float) -> None:
        with self._metrics_lock:
            self._append_bounded(values, latency_ms)

    def _append_bounded(self, values: list[float], value: float) -> None:
        values.append(value)
        overflow = len(values) - self.config.latency_buffer_size
        if overflow > 0:
            del values[:overflow]


def build_dark_observation_service(
    settings: object,
    *,
    provider: DarkObservationProvider | None = None,
    sampling_key: bytes | None = None,
) -> DarkObservationService:
    return DarkObservationService(
        DarkObservationConfig(
            mode=getattr(settings, "dark_observation_mode", "OFF"),
            sample_basis_points=int(
                getattr(settings, "dark_observation_sample_basis_points", 0)
            ),
            worker_count=int(getattr(settings, "dark_observation_worker_count", 1)),
            queue_capacity=int(
                getattr(settings, "dark_observation_queue_capacity", 8)
            ),
            observation_deadline_ms=int(
                getattr(settings, "dark_observation_deadline_ms", 100)
            ),
            shutdown_grace_ms=int(
                getattr(settings, "dark_observation_shutdown_grace_ms", 2_000)
            ),
            latency_buffer_size=int(
                getattr(settings, "metrics_latency_buffer_size", 1_000)
            ),
        ),
        provider=provider,
        sampling_key=sampling_key,
    )


def safe_dark_observation_snapshot(service: object) -> dict[str, object]:
    try:
        snapshot = service.snapshot()
        if not isinstance(snapshot, dict):
            raise TypeError("dark-observation snapshot must be a mapping")
        return snapshot
    except Exception:
        return {
            "schema_version": "dark_observation_metrics_v1",
            "mode": "OFF",
            "status": "UNAVAILABLE",
            "content_retained": False,
        }


def _latency_summary(values: tuple[float, ...]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)

    def percentile(value: float) -> float:
        index = max(0, min(len(ordered) - 1, math.ceil(value * len(ordered)) - 1))
        return round(ordered[index], 3)

    return {
        "count": len(ordered),
        "p50": percentile(0.5),
        "p95": percentile(0.95),
        "max": round(ordered[-1], 3),
    }


__all__ = [
    "DarkObservationConfig",
    "DarkObservationOfferOutcome",
    "DarkObservationProvider",
    "DarkObservationProviderOutcome",
    "DarkObservationRequest",
    "DarkObservationService",
    "build_dark_observation_service",
    "safe_dark_observation_snapshot",
]
