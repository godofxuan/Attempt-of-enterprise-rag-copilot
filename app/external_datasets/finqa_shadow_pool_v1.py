from __future__ import annotations

import queue
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQAPrimaryDescriptorDecisionV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowObservationV1,
    FinQAIsolatedShadowWorkerV1,
    FinQAShadowWorkerConfigV1,
    FinQAShadowWorkerDiagnosticsV1,
)


POOL_OBSERVATION_VERSION = "finqa_pooled_shadow_observation_v1"
PoolOutcomeV1 = Literal[
    "MATCH",
    "DIVERGED",
    "INPUT_MISMATCH",
    "PAYLOAD_REJECTED",
    "WORKER_ERROR",
    "WORKER_TIMEOUT",
    "WORKER_CRASH",
    "BACKPRESSURE_REJECTED",
    "DEADLINE_EXCEEDED",
    "POOL_NOT_RUNNING",
    "POOL_CLOSED",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowWorkerPoolConfigV1(_StrictFrozenModel):
    worker_count: int = Field(default=2, ge=1, le=16)
    queue_capacity: int = Field(default=4, ge=1, le=256)
    admission_timeout_seconds: float = Field(default=0.25, ge=0, le=30)
    response_deadline_seconds: float = Field(default=2.0, gt=0, le=60)
    shutdown_grace_seconds: float = Field(default=20.0, gt=0, le=60)


class FinQAPooledShadowObservationV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_pooled_shadow_observation_v1"
    ] = POOL_OBSERVATION_VERSION
    outcome: PoolOutcomeV1
    role_count: int = Field(ge=0, le=8)
    changed_role_count: int = Field(ge=0, le=8)
    common_descriptor_count_at_4: int = Field(ge=0, le=32)
    queue_wait_ms: float = Field(ge=0)
    execution_latency_ms: float = Field(ge=0)
    end_to_end_latency_ms: float = Field(ge=0)
    worker_peak_rss_bytes: int | None = Field(default=None, ge=0)
    worker_restarted: bool
    worker_slot: int | None = Field(default=None, ge=0, le=15)

    @model_validator(mode="after")
    def validate_counts(self) -> FinQAPooledShadowObservationV1:
        if (
            self.changed_role_count > self.role_count
            or self.common_descriptor_count_at_4 > self.role_count * 4
        ):
            raise ValueError("E14 pooled observation counts are inconsistent")
        return self


class FinQAShadowPoolMetricsV1(_StrictFrozenModel):
    submitted_count: int = Field(ge=0)
    admitted_count: int = Field(ge=0)
    executed_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    backpressure_rejected_count: int = Field(ge=0)
    deadline_exceeded_count: int = Field(ge=0)
    pool_state_rejected_count: int = Field(ge=0)
    late_result_discarded_count: int = Field(ge=0)
    cancelled_before_execution_count: int = Field(ge=0)
    active_worker_high_watermark: int = Field(ge=0)
    queue_high_watermark: int = Field(ge=0)
    returned_outcome_counts: dict[str, int]
    executed_outcome_counts: dict[str, int]
    worker_restart_count: int = Field(ge=0)
    worker_pool_rss_upper_bound_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_totals(self) -> FinQAShadowPoolMetricsV1:
        if self.admitted_count > self.submitted_count:
            raise ValueError("E14 admitted count exceeds submissions")
        if self.completed_count > self.admitted_count:
            raise ValueError("E14 completed count exceeds admissions")
        if self.active_worker_high_watermark < 0 or self.queue_high_watermark < 0:
            raise ValueError("E14 high-water marks must be non-negative")
        return self


class FinQAShadowPoolDiagnosticsV1(_StrictFrozenModel):
    state: Literal["NEW", "RUNNING", "CLOSING", "CLOSED"]
    worker_pids: tuple[int | None, ...]
    dispatcher_alive_count: int = Field(ge=0)
    queue_depth: int = Field(ge=0)


class _ShadowWorker(Protocol):
    def start(self) -> bool: ...

    def observe(
        self,
        *,
        primary: FinQAPrimaryDescriptorDecisionV1,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> FinQAIsolatedShadowObservationV1: ...

    def diagnostics(self) -> FinQAShadowWorkerDiagnosticsV1: ...

    def close(self) -> None: ...


@dataclass
class _PoolJobV1:
    primary: FinQAPrimaryDescriptorDecisionV1
    question: str
    skeleton: SemanticProgramSkeletonV2
    catalog: RetrievableSafeDescriptorCatalogV3
    admitted_at: float
    deadline_at: float
    role_count: int
    done: Event = field(default_factory=Event)
    lock: Lock = field(default_factory=Lock)
    result: FinQAPooledShadowObservationV1 | None = None
    cancelled: bool = False


_STOP = object()


class FinQABoundedShadowWorkerPoolV1:
    def __init__(
        self,
        *,
        evidence_dir: Path,
        config: FinQAShadowWorkerPoolConfigV1 | None = None,
        worker_config: FinQAShadowWorkerConfigV1 | None = None,
        worker_factory: Callable[[int], _ShadowWorker] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.evidence_dir = evidence_dir.resolve()
        self.config = config or FinQAShadowWorkerPoolConfigV1()
        self.worker_config = worker_config or FinQAShadowWorkerConfigV1()
        self._clock = clock
        self._worker_factory = worker_factory or self._default_worker_factory
        self._queue: queue.Queue[_PoolJobV1 | object] = queue.Queue(
            maxsize=self.config.queue_capacity
        )
        self._state_lock = Lock()
        self._metrics_lock = Lock()
        self._closed_event = Event()
        self._state: Literal["NEW", "RUNNING", "CLOSING", "CLOSED"] = "NEW"
        self._close_completed: bool | None = None
        self._workers: list[_ShadowWorker] = []
        self._threads: list[Thread] = []
        self._submitted_count = 0
        self._admitted_count = 0
        self._executed_count = 0
        self._active_workers = 0
        self._active_worker_high_watermark = 0
        self._queue_high_watermark = 0
        self._late_result_discarded_count = 0
        self._cancelled_before_execution_count = 0
        self._returned_outcomes: Counter[str] = Counter()
        self._executed_outcomes: Counter[str] = Counter()
        self._worker_peak_rss: dict[int, int] = {}

    def __enter__(self) -> FinQABoundedShadowWorkerPoolV1:
        if not self.start():
            raise RuntimeError("E14 shadow worker pool failed to start")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _default_worker_factory(self, _index: int) -> _ShadowWorker:
        return FinQAIsolatedShadowWorkerV1(
            evidence_dir=self.evidence_dir,
            config=self.worker_config,
        )

    def start(self) -> bool:
        with self._state_lock:
            if self._state == "RUNNING":
                return True
            if self._state != "NEW":
                return False
            workers = [
                self._worker_factory(index)
                for index in range(self.config.worker_count)
            ]
            started: list[_ShadowWorker] = []
            for worker in workers:
                if not worker.start():
                    for active in started:
                        active.close()
                    self._state = "CLOSED"
                    return False
                started.append(worker)
            self._workers = workers
            self._state = "RUNNING"
            self._threads = [
                Thread(
                    target=self._dispatch,
                    args=(index, worker),
                    daemon=True,
                    name=f"finqa-e14-shadow-dispatch-{index}",
                )
                for index, worker in enumerate(workers)
            ]
            for thread in self._threads:
                thread.start()
            return True

    def _failure(
        self,
        *,
        outcome: PoolOutcomeV1,
        role_count: int,
        started: float,
    ) -> FinQAPooledShadowObservationV1:
        return FinQAPooledShadowObservationV1(
            outcome=outcome,
            role_count=role_count,
            changed_role_count=0,
            common_descriptor_count_at_4=0,
            queue_wait_ms=0,
            execution_latency_ms=0,
            end_to_end_latency_ms=max(0.0, (self._clock() - started) * 1_000),
            worker_restarted=False,
        )

    def _record_returned(self, outcome: PoolOutcomeV1) -> None:
        with self._metrics_lock:
            self._returned_outcomes[outcome] += 1

    def _dispatch(self, worker_slot: int, worker: _ShadowWorker) -> None:
        while True:
            queued = self._queue.get()
            if queued is _STOP:
                self._queue.task_done()
                return
            assert isinstance(queued, _PoolJobV1)
            job = queued
            execution_started = self._clock()
            with job.lock:
                if job.cancelled:
                    with self._metrics_lock:
                        self._cancelled_before_execution_count += 1
                    self._queue.task_done()
                    continue
            if execution_started >= job.deadline_at:
                result = self._failure(
                    outcome="DEADLINE_EXCEEDED",
                    role_count=job.role_count,
                    started=job.admitted_at,
                )
                with job.lock:
                    if not job.cancelled:
                        job.result = result
                        job.done.set()
                self._queue.task_done()
                continue
            with self._metrics_lock:
                self._executed_count += 1
                self._active_workers += 1
                self._active_worker_high_watermark = max(
                    self._active_worker_high_watermark,
                    self._active_workers,
                )
            try:
                worker_result = worker.observe(
                    primary=job.primary,
                    question=job.question,
                    skeleton=job.skeleton,
                    catalog=job.catalog,
                )
            except Exception:
                worker_result = FinQAIsolatedShadowObservationV1(
                    outcome="WORKER_ERROR",
                    role_count=job.role_count,
                    changed_role_count=0,
                    common_descriptor_count_at_4=0,
                    latency_ms=max(
                        0.0,
                        (self._clock() - execution_started) * 1_000,
                    ),
                    worker_restarted=False,
                )
            finished = self._clock()
            result = FinQAPooledShadowObservationV1(
                outcome=worker_result.outcome,
                role_count=worker_result.role_count,
                changed_role_count=worker_result.changed_role_count,
                common_descriptor_count_at_4=(
                    worker_result.common_descriptor_count_at_4
                ),
                queue_wait_ms=max(
                    0.0,
                    (execution_started - job.admitted_at) * 1_000,
                ),
                execution_latency_ms=worker_result.latency_ms,
                end_to_end_latency_ms=max(
                    0.0,
                    (finished - job.admitted_at) * 1_000,
                ),
                worker_peak_rss_bytes=worker_result.worker_peak_rss_bytes,
                worker_restarted=worker_result.worker_restarted,
                worker_slot=worker_slot,
            )
            with self._metrics_lock:
                self._active_workers -= 1
                self._executed_outcomes[worker_result.outcome] += 1
                if worker_result.worker_peak_rss_bytes is not None:
                    self._worker_peak_rss[worker_slot] = max(
                        self._worker_peak_rss.get(worker_slot, 0),
                        worker_result.worker_peak_rss_bytes,
                    )
            with job.lock:
                if job.cancelled or finished >= job.deadline_at:
                    with self._metrics_lock:
                        self._late_result_discarded_count += 1
                    if not job.cancelled:
                        job.result = self._failure(
                            outcome="DEADLINE_EXCEEDED",
                            role_count=job.role_count,
                            started=job.admitted_at,
                        )
                        job.done.set()
                else:
                    job.result = result
                    job.done.set()
            self._queue.task_done()

    def observe(
        self,
        *,
        primary: FinQAPrimaryDescriptorDecisionV1,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> FinQAPooledShadowObservationV1:
        started = self._clock()
        role_count = len(primary.result.selections.selections)
        with self._metrics_lock:
            self._submitted_count += 1
        deadline_at = started + self.config.response_deadline_seconds
        job = _PoolJobV1(
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
            admitted_at=started,
            deadline_at=deadline_at,
            role_count=role_count,
        )
        admission_timeout = min(
            self.config.admission_timeout_seconds,
            max(0.0, deadline_at - self._clock()),
        )
        saturated = False
        with self._state_lock:
            state = self._state
            if state == "RUNNING":
                try:
                    self._queue.put(job, timeout=admission_timeout)
                except queue.Full:
                    saturated = True
        if state != "RUNNING" or saturated:
            if saturated:
                outcome: PoolOutcomeV1 = "BACKPRESSURE_REJECTED"
            else:
                outcome = (
                    "POOL_CLOSED"
                    if state in {"CLOSING", "CLOSED"}
                    else "POOL_NOT_RUNNING"
                )
            result = self._failure(
                outcome=outcome,
                role_count=role_count,
                started=started,
            )
            self._record_returned(outcome)
            return result
        with self._metrics_lock:
            self._admitted_count += 1
            self._queue_high_watermark = max(
                self._queue_high_watermark,
                self._queue.qsize(),
            )

        remaining = max(0.0, deadline_at - self._clock())
        job.done.wait(timeout=remaining)
        with job.lock:
            if job.result is None:
                job.cancelled = True
                result = self._failure(
                    outcome="DEADLINE_EXCEEDED",
                    role_count=role_count,
                    started=started,
                )
            else:
                result = job.result
        self._record_returned(result.outcome)
        return result

    def metrics(self) -> FinQAShadowPoolMetricsV1:
        with self._metrics_lock:
            returned = dict(sorted(self._returned_outcomes.items()))
            executed = dict(sorted(self._executed_outcomes.items()))
            restart_count = sum(
                worker.diagnostics().restart_count for worker in self._workers
            )
            return FinQAShadowPoolMetricsV1(
                submitted_count=self._submitted_count,
                admitted_count=self._admitted_count,
                executed_count=self._executed_count,
                completed_count=(
                    returned.get("MATCH", 0) + returned.get("DIVERGED", 0)
                ),
                backpressure_rejected_count=returned.get(
                    "BACKPRESSURE_REJECTED", 0
                ),
                deadline_exceeded_count=returned.get("DEADLINE_EXCEEDED", 0),
                pool_state_rejected_count=(
                    returned.get("POOL_NOT_RUNNING", 0)
                    + returned.get("POOL_CLOSED", 0)
                ),
                late_result_discarded_count=self._late_result_discarded_count,
                cancelled_before_execution_count=(
                    self._cancelled_before_execution_count
                ),
                active_worker_high_watermark=(
                    self._active_worker_high_watermark
                ),
                queue_high_watermark=self._queue_high_watermark,
                returned_outcome_counts=returned,
                executed_outcome_counts=executed,
                worker_restart_count=restart_count,
                worker_pool_rss_upper_bound_bytes=sum(
                    self._worker_peak_rss.values()
                ),
            )

    def diagnostics(self) -> FinQAShadowPoolDiagnosticsV1:
        with self._state_lock:
            state = self._state
            workers = tuple(self._workers)
            threads = tuple(self._threads)
        return FinQAShadowPoolDiagnosticsV1(
            state=state,
            worker_pids=tuple(
                worker.diagnostics().worker_pid for worker in workers
            ),
            dispatcher_alive_count=sum(thread.is_alive() for thread in threads),
            queue_depth=self._queue.qsize(),
        )

    def close(self) -> bool:
        wait_for_owner = False
        with self._state_lock:
            if self._state == "CLOSED":
                return bool(self._close_completed)
            if self._state == "CLOSING":
                wait_for_owner = True
            if self._state == "NEW":
                self._state = "CLOSED"
                self._close_completed = True
                self._closed_event.set()
                return True
            if not wait_for_owner:
                self._state = "CLOSING"

        if wait_for_owner:
            if not self._closed_event.wait(
                timeout=self.config.shutdown_grace_seconds
            ):
                return False
            with self._state_lock:
                return bool(self._close_completed)

        complete = False
        try:
            while True:
                try:
                    queued = self._queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(queued, _PoolJobV1):
                    with queued.lock:
                        if queued.result is None:
                            queued.result = self._failure(
                                outcome="POOL_CLOSED",
                                role_count=queued.role_count,
                                started=queued.admitted_at,
                            )
                            queued.done.set()
                self._queue.task_done()
            for _ in self._threads:
                self._queue.put(_STOP)

            deadline = self._clock() + self.config.shutdown_grace_seconds
            for thread in self._threads:
                thread.join(timeout=max(0.0, deadline - self._clock()))
            complete = all(not thread.is_alive() for thread in self._threads)
            if complete:
                for worker in self._workers:
                    try:
                        worker.close()
                    except Exception:
                        complete = False
            return complete
        finally:
            with self._state_lock:
                self._state = "CLOSED"
                self._close_completed = complete
                self._closed_event.set()


__all__ = [
    "FinQABoundedShadowWorkerPoolV1",
    "FinQAPooledShadowObservationV1",
    "FinQAShadowPoolDiagnosticsV1",
    "FinQAShadowPoolMetricsV1",
    "FinQAShadowWorkerPoolConfigV1",
]
