from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

from app.external_datasets.finqa_descriptor_shadow_v1 import (
    FinQADescriptorShadowRuntimeV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_shadow_pool_v1 import (
    FinQABoundedShadowWorkerPoolV1,
    FinQAShadowWorkerPoolConfigV1,
)
from app.external_datasets.finqa_shadow_worker_v1 import (
    FinQAIsolatedShadowObservationV1,
    FinQAShadowWorkerDiagnosticsV1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"


def _inputs():
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "none",
                }
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"constant_id": "const_100"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )
    descriptor = RetrievableSafeCandidateDescriptorV3(
        descriptor_id="desc-0000000000000001",
        metric="operating metric",
        row_header="operating metric",
        column_header="current period",
        local_context_hint="annual operating result",
        topic_hint="company operating performance",
        periods=(),
        source_kind="table_cell",
        candidate_count=1,
    )
    payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": 1,
        "represented_candidate_count": 1,
        "quarantined_candidate_count": 0,
        "descriptor_count": 1,
        "descriptors": [descriptor.model_dump(mode="json")],
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    catalog = RetrievableSafeDescriptorCatalogV3(**payload, catalog_sha256=digest)
    question = "Which operating metric changed?"
    primary = FinQADescriptorShadowRuntimeV1().select_primary(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    return primary, question, skeleton, catalog


class _ConcurrentWorker:
    def __init__(self, barrier: Barrier) -> None:
        self._barrier = barrier
        self.closed = False

    def start(self) -> bool:
        return True

    def observe(self, **_: object) -> FinQAIsolatedShadowObservationV1:
        self._barrier.wait(timeout=2)
        return FinQAIsolatedShadowObservationV1(
            outcome="MATCH",
            role_count=1,
            changed_role_count=0,
            common_descriptor_count_at_4=1,
            latency_ms=1,
            worker_peak_rss_bytes=10_000,
            worker_restarted=False,
        )

    def diagnostics(self) -> FinQAShadowWorkerDiagnosticsV1:
        return FinQAShadowWorkerDiagnosticsV1(
            worker_pid=None,
            last_terminated_pid=None,
            last_terminated_exitcode=None,
            restart_count=0,
        )

    def close(self) -> None:
        self.closed = True


class _BlockingWorker(_ConcurrentWorker):
    def __init__(self, started: Event, release: Event) -> None:
        self._started = started
        self._release = release
        self.closed = False

    def observe(self, **_: object) -> FinQAIsolatedShadowObservationV1:
        self._started.set()
        if not self._release.wait(timeout=2):
            raise TimeoutError("test did not release blocking worker")
        return FinQAIsolatedShadowObservationV1(
            outcome="MATCH",
            role_count=1,
            changed_role_count=0,
            common_descriptor_count_at_4=1,
            latency_ms=1,
            worker_peak_rss_bytes=10_000,
            worker_restarted=False,
        )


class _OutcomeWorker(_ConcurrentWorker):
    def __init__(self, barrier: Barrier, outcome: str) -> None:
        self._barrier = barrier
        self._outcome = outcome
        self.closed = False

    def observe(self, **_: object) -> FinQAIsolatedShadowObservationV1:
        self._barrier.wait(timeout=2)
        return FinQAIsolatedShadowObservationV1(
            outcome=self._outcome,
            role_count=1,
            changed_role_count=0,
            common_descriptor_count_at_4=1 if self._outcome == "MATCH" else 0,
            latency_ms=1,
            worker_peak_rss_bytes=10_000,
            worker_restarted=self._outcome == "WORKER_CRASH",
        )


class _SlowCloseWorker(_ConcurrentWorker):
    def __init__(self, close_started: Event, release_close: Event) -> None:
        super().__init__(Barrier(1))
        self._close_started = close_started
        self._release_close = release_close

    def close(self) -> None:
        self._close_started.set()
        if not self._release_close.wait(timeout=2):
            raise TimeoutError("test did not release worker close")
        self.closed = True


def _wait_for_admitted(pool: FinQABoundedShadowWorkerPoolV1, count: int) -> None:
    deadline = time.perf_counter() + 1
    while time.perf_counter() < deadline:
        if pool.metrics().admitted_count >= count:
            return
        time.sleep(0.005)
    raise AssertionError(f"pool did not admit {count} requests")


def _wait_for_deadline_cleanup(pool: FinQABoundedShadowWorkerPoolV1) -> None:
    deadline = time.perf_counter() + 1
    while time.perf_counter() < deadline:
        metrics = pool.metrics()
        if (
            metrics.late_result_discarded_count == 1
            and metrics.cancelled_before_execution_count == 1
        ):
            return
        time.sleep(0.005)
    raise AssertionError("pool did not finish deadline cleanup")


def test_pool_dispatches_concurrently_to_bounded_worker_slots() -> None:
    primary, question, skeleton, catalog = _inputs()
    barrier = Barrier(2)
    workers = [_ConcurrentWorker(barrier) for _ in range(2)]
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=2,
            queue_capacity=2,
            admission_timeout_seconds=0.1,
            response_deadline_seconds=1,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda index: workers[index],
    )
    assert pool.start() is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                pool.observe,
                primary=primary,
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            )
            for _ in range(2)
        ]
        observations = [future.result(timeout=2) for future in futures]

    metrics = pool.metrics()
    assert [item.outcome for item in observations] == ["MATCH", "MATCH"]
    assert metrics.submitted_count == 2
    assert metrics.admitted_count == 2
    assert metrics.completed_count == 2
    assert metrics.active_worker_high_watermark == 2
    assert metrics.queue_high_watermark <= 2
    assert pool.close() is True
    assert all(worker.closed for worker in workers)


def test_pool_rejects_newest_when_worker_and_queue_are_saturated() -> None:
    primary, question, skeleton, catalog = _inputs()
    primary_before = (
        primary.input_binding_sha256,
        primary.result.retriever_version,
        primary.result.generation_calls,
        primary.result.selections.model_dump_json(),
    )
    started = Event()
    release = Event()
    worker = _BlockingWorker(started, release)
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=1,
            queue_capacity=1,
            admission_timeout_seconds=0.01,
            response_deadline_seconds=1,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda _index: worker,
    )
    assert pool.start() is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        assert started.wait(timeout=1)
        second = executor.submit(
            pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        _wait_for_admitted(pool, 2)
        rejected = pool.observe(
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        release.set()
        assert first.result(timeout=2).outcome == "MATCH"
        assert second.result(timeout=2).outcome == "MATCH"

    metrics = pool.metrics()
    assert rejected.outcome == "BACKPRESSURE_REJECTED"
    assert metrics.submitted_count == 3
    assert metrics.admitted_count == 2
    assert metrics.backpressure_rejected_count == 1
    assert metrics.queue_high_watermark == 1
    assert (
        primary.input_binding_sha256,
        primary.result.retriever_version,
        primary.result.generation_calls,
        primary.result.selections.model_dump_json(),
    ) == primary_before
    assert pool.close() is True


def test_deadline_discards_late_result_and_skips_expired_queued_work() -> None:
    primary, question, skeleton, catalog = _inputs()
    started = Event()
    release = Event()
    worker = _BlockingWorker(started, release)
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=1,
            queue_capacity=1,
            admission_timeout_seconds=0.01,
            response_deadline_seconds=0.05,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda _index: worker,
    )
    assert pool.start() is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        assert started.wait(timeout=1)
        second = executor.submit(
            pool.observe,
            primary=primary,
            question=question,
            skeleton=skeleton,
            catalog=catalog,
        )
        _wait_for_admitted(pool, 2)
        assert first.result(timeout=1).outcome == "DEADLINE_EXCEEDED"
        assert second.result(timeout=1).outcome == "DEADLINE_EXCEEDED"
        release.set()

    _wait_for_deadline_cleanup(pool)
    metrics = pool.metrics()
    assert metrics.submitted_count == 2
    assert metrics.admitted_count == 2
    assert metrics.executed_count == 1
    assert metrics.deadline_exceeded_count == 2
    assert metrics.late_result_discarded_count == 1
    assert metrics.cancelled_before_execution_count == 1
    assert pool.close() is True


def test_worker_fault_is_confined_while_peer_slot_completes() -> None:
    primary, question, skeleton, catalog = _inputs()
    barrier = Barrier(2)
    workers = [
        _OutcomeWorker(barrier, "WORKER_CRASH"),
        _OutcomeWorker(barrier, "MATCH"),
    ]
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=2,
            queue_capacity=2,
            admission_timeout_seconds=0.1,
            response_deadline_seconds=1,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda index: workers[index],
    )
    assert pool.start() is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                pool.observe,
                primary=primary,
                question=question,
                skeleton=skeleton,
                catalog=catalog,
            )
            for _ in range(2)
        ]
        outcomes = {future.result(timeout=2).outcome for future in futures}

    metrics = pool.metrics()
    assert outcomes == {"MATCH", "WORKER_CRASH"}
    assert metrics.executed_outcome_counts == {"MATCH": 1, "WORKER_CRASH": 1}
    assert metrics.completed_count == 1
    assert pool.close() is True


def test_real_pool_closes_spawn_workers_and_rejects_new_work() -> None:
    primary, question, skeleton, catalog = _inputs()
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=2,
            queue_capacity=2,
            admission_timeout_seconds=0.1,
            response_deadline_seconds=2,
            shutdown_grace_seconds=5,
        ),
    )
    assert pool.start() is True
    running = pool.diagnostics()
    assert running.state == "RUNNING"
    assert len(running.worker_pids) == 2
    assert all(pid is not None for pid in running.worker_pids)
    assert running.dispatcher_alive_count == 2

    assert pool.close() is True
    closed = pool.diagnostics()
    assert closed.state == "CLOSED"
    assert closed.worker_pids == (None, None)
    assert closed.dispatcher_alive_count == 0
    rejected = pool.observe(
        primary=primary,
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    assert rejected.outcome == "POOL_CLOSED"
    assert pool.metrics().pool_state_rejected_count == 1


def test_concurrent_close_calls_share_one_bounded_shutdown() -> None:
    close_started = Event()
    release_close = Event()
    workers = [
        _SlowCloseWorker(close_started, release_close),
        _SlowCloseWorker(close_started, release_close),
    ]
    pool = FinQABoundedShadowWorkerPoolV1(
        evidence_dir=EVIDENCE,
        config=FinQAShadowWorkerPoolConfigV1(
            worker_count=2,
            queue_capacity=2,
            shutdown_grace_seconds=2,
        ),
        worker_factory=lambda index: workers[index],
    )
    assert pool.start() is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(pool.close)
        second = executor.submit(pool.close)
        assert close_started.wait(timeout=1)
        release_close.set()
        assert first.result(timeout=2) is True
        assert second.result(timeout=2) is True

    diagnostics = pool.diagnostics()
    assert diagnostics.state == "CLOSED"
    assert diagnostics.dispatcher_alive_count == 0
    assert diagnostics.queue_depth == 0
    assert all(worker.closed for worker in workers)
