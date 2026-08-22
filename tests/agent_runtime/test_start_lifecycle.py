from __future__ import annotations

import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.durable_orchestrator import (
    DurableAccessRequestWorkflow,
    DurableToolRunRequest,
)
from app.agent_runtime.durable_store import (
    DurableStoreConflict,
    InjectedIntegrityCrash,
    SQLiteDurableWorkflowStore,
)
from app.agent_runtime.side_effects import AccessRequestDraftArguments
from app.agent_runtime.telemetry import AgentTelemetry, build_tracer_provider
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from app.domain.queries import UserContext
from tests.v2_test_support import RecordingNavigator


def _request(**updates) -> DurableToolRunRequest:
    values = {
        "tenant_id": "tenant-one",
        "user_id": "employee-one",
        "reviewer_user_id": "reviewer-one",
        "session_id": "start-session",
        "run_id": "start-run",
        "trace_id": "start-trace",
        "start_idempotency_key": "client-operation-001",
        "arguments": AccessRequestDraftArguments(
            resource_id="finance/policy-7",
            requested_group="finance-readers",
            reason="Need access for quarter-end review.",
        ),
        "deadline_at_ms": 10_000.0,
        "authentication_expires_at_ms": 10_000.0,
        "approval_expires_at_ms": 9_000.0,
    }
    values.update(updates)
    return DurableToolRunRequest(**values)


def _user(**updates) -> UserContext:
    values = {
        "user_id": "employee-one",
        "tenant_id": "tenant-one",
        "region": "cn",
        "groups": ["employees"],
        "roles": [],
    }
    values.update(updates)
    return UserContext(**values)


def _reviewer() -> UserContext:
    return UserContext(
        user_id="reviewer-one",
        tenant_id="tenant-one",
        region="cn",
        groups=["employees"],
        roles=["knowledge_reviewer"],
    )


def _runtime(state_dir: Path, now: list[float], **kwargs) -> DurableAccessRequestWorkflow:
    return DurableAccessRequestWorkflow(
        V2ToolRegistry(RecordingNavigator(), clock_ms=lambda: now[0]),
        state_dir=state_dir,
        clock_ms=lambda: now[0],
        start_lease_ms=50.0,
        resume_lease_ms=50.0,
        **kwargs,
    )


def _process_start_worker(state_dir, barrier, output) -> None:
    now = [100.0]
    runtime = _runtime(Path(state_dir), now)
    try:
        barrier.wait(timeout=10.0)
        result = runtime.start_access_request(_request())
        output.put(result.model_dump(mode="json"))
    except Exception as exc:  # pragma: no cover - asserted in parent process
        output.put({"error": f"{type(exc).__name__}:{exc}"})
    finally:
        runtime.close()


def test_same_start_key_is_stable_and_does_not_duplicate_checkpoint_or_trajectory(
    tmp_path,
) -> None:
    now = [100.0]
    trajectory = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3")
    runtime = _runtime(tmp_path / "state", now, trajectory_store=trajectory)

    first = runtime.start_access_request(_request())
    second = runtime.start_access_request(_request())

    assert first.status == second.status == "needs_approval"
    assert first.approval == second.approval
    assert first.approval.approval_generation == 1
    assert runtime.store.approval_count() == 1
    record = runtime.store.by_handle(first.approval.approval_handle_id)
    assert record.start_status == "READY"
    assert record.checkpoint_status == "READY"
    assert record.start_attempt == 1
    assert record.start_trajectory_delivered_at_ms is not None
    assert [event.event_type for event in trajectory.load(record.trajectory_session_id)] == [
        "session.started",
        "human_review.requested",
    ]
    snapshot = runtime.graph.get_state(runtime._config(record.thread_id))
    assert snapshot.values["approval_id"] == record.approval_id
    assert snapshot.next
    runtime.close()


def test_two_threads_start_same_key_with_one_database_owner(tmp_path) -> None:
    now = [100.0]
    barrier = Barrier(2)
    state_dir = tmp_path / "state"
    first = _runtime(state_dir, now, after_start_acquired=lambda _: barrier.wait(timeout=5))
    second = _runtime(state_dir, now)

    def start(runtime):
        if runtime is second:
            barrier.wait(timeout=5)
        return runtime.start_access_request(_request())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, (first, second)))

    assert {result.status for result in results}.issubset({"needs_approval", "start_in_progress"})
    approvals = {result.approval.approval_id for result in results}
    handles = {result.approval.approval_handle_id for result in results}
    assert len(approvals) == len(handles) == 1
    assert first.store.approval_count() == 1
    assert first.store.by_handle(next(iter(handles))).start_attempt == 1
    first.close()
    second.close()


def test_two_processes_start_same_key_and_retry_returns_one_ready_generation(tmp_path) -> None:
    state_dir = tmp_path / "state"
    initializer = _runtime(state_dir, [100.0])
    initializer.close()
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    output = context.Queue()
    processes = [
        context.Process(target=_process_start_worker, args=(state_dir, barrier, output))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    results = [output.get(timeout=5) for _ in processes]
    assert not [item for item in results if "error" in item], results
    assert len({item["approval"]["approval_id"] for item in results}) == 1
    assert len({item["approval"]["approval_handle_id"] for item in results}) == 1

    runtime = _runtime(state_dir, [100.0])
    stable = runtime.start_access_request(_request())
    assert stable.status == "needs_approval"
    assert runtime.store.approval_count() == 1
    runtime.close()


def test_new_key_in_same_session_creates_new_generation_and_checkpoint(tmp_path) -> None:
    runtime = _runtime(tmp_path / "state", [100.0])
    first = runtime.start_access_request(_request())
    second = runtime.start_access_request(_request(start_idempotency_key="client-operation-002"))

    assert first.approval.approval_generation == 1
    assert second.approval.approval_generation == 2
    assert first.approval.approval_id != second.approval.approval_id
    assert first.approval.thread_id != second.approval.thread_id
    assert runtime.store.approval_count() == 2
    runtime.close()


def test_same_start_key_with_changed_request_fails_closed(tmp_path) -> None:
    runtime = _runtime(tmp_path / "state", [100.0])
    runtime.start_access_request(_request())
    changed_arguments = AccessRequestDraftArguments(
        resource_id="finance/policy-8",
        requested_group="finance-readers",
        reason="A different operation must not reuse the same key.",
    )

    with pytest.raises(DurableStoreConflict, match="START_IDEMPOTENCY_CONFLICT"):
        runtime.start_access_request(_request(arguments=changed_arguments))
    assert runtime.store.approval_count() == 1
    runtime.close()


def test_expired_approval_start_retry_is_stable_and_cannot_look_pending(tmp_path) -> None:
    now = [100.0]
    runtime = _runtime(tmp_path / "state", now)
    first = runtime.start_access_request(_request())
    now[0] = 9_001.0

    expired = runtime.start_access_request(_request())

    assert expired.status == "expired"
    assert expired.approval.approval_id == first.approval.approval_id
    assert expired.approval.approval_handle_id == first.approval.approval_handle_id
    assert runtime.store.by_handle(first.approval.approval_handle_id).status == "EXPIRED"
    assert runtime.store.approval_count() == 1
    runtime.close()


def test_expired_start_owner_is_fenced_after_new_owner_recovers(tmp_path) -> None:
    store = SQLiteDurableWorkflowStore(tmp_path / "approvals.sqlite3")
    request_json = _request().model_dump_json()
    arguments_hash = "a" * 64
    common = {
        "request_json": request_json,
        "approval_expires_at_ms": 9_000.0,
        "start_scope_sha256": "b" * 64,
        "generation_scope_sha256": "c" * 64,
        "request_binding_sha256": "d" * 64,
        "start_key_sha256": "e" * 64,
        "tool_call_sha256": arguments_hash,
        "continuation_trace_json": "{}",
        "base_session_id": "start-session",
        "lease_ms": 50.0,
    }
    stale = store.begin_start(**common, now_ms=100.0)
    recovered = store.begin_start(**common, now_ms=151.0)

    assert stale.owner_token is not None and recovered.owner_token is not None
    assert stale.record.approval_id == recovered.record.approval_id
    assert recovered.record.start_version == stale.record.start_version + 1
    with pytest.raises(DurableStoreConflict, match="START_FENCING_CONFLICT"):
        store.mark_checkpoint_in_progress(
            approval_id=stale.record.approval_id,
            owner_token=stale.owner_token,
            start_version=stale.record.start_version,
            now_ms=151.0,
        )
    current = store.mark_checkpoint_in_progress(
        approval_id=recovered.record.approval_id,
        owner_token=recovered.owner_token,
        start_version=recovered.record.start_version,
        now_ms=151.0,
    )
    assert current.checkpoint_status == "IN_PROGRESS"


@pytest.mark.parametrize(
    "crash_point",
    [
        "before_approval_insert",
        "after_approval_insert_before_checkpoint",
        "during_checkpoint",
        "after_checkpoint_before_ready",
        "after_ready_before_trajectory",
        "after_trajectory_before_response",
        "during_response",
    ],
)
def test_start_crash_matrix_recovers_same_approval_handle_and_checkpoint(
    tmp_path, crash_point
) -> None:
    now = [100.0]
    trajectory = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3")
    first = _runtime(tmp_path / "state", now, trajectory_store=trajectory)
    with pytest.raises(InjectedIntegrityCrash):
        first.start_access_request(_request(), crash_point=crash_point)
    first.close()

    now[0] = 151.0
    recovered = _runtime(tmp_path / "state", now, trajectory_store=trajectory)
    assert recovered.recover_stale_starts() in {0, 1}
    result = recovered.start_access_request(_request())
    record = recovered.store.by_handle(result.approval.approval_handle_id)

    assert result.status == "needs_approval"
    assert recovered.store.approval_count() == 1
    assert record.start_status == record.checkpoint_status == "READY"
    assert (
        recovered.graph.get_state(recovered._config(record.thread_id)).values["approval_id"]
        == record.approval_id
    )
    events = trajectory.load(record.trajectory_session_id)
    assert [event.event_type for event in events].count("session.started") == 1
    assert [event.event_type for event in events].count("human_review.requested") == 1
    recovered.close()


def test_lost_response_is_reissued_then_acknowledged_and_handle_can_rotate(tmp_path) -> None:
    now = [100.0]
    runtime = _runtime(tmp_path / "state", now)
    first = runtime.start_access_request(_request())
    retried = runtime.start_access_request(_request())

    assert retried.approval == first.approval
    assert (
        runtime.store.by_handle(first.approval.approval_handle_id).client_acknowledged_at_ms is None
    )
    acknowledged = runtime.acknowledge_start(
        retried.approval.approval_handle_id,
        requester=_user(),
    )
    assert acknowledged.client_acknowledged_at_ms == now[0]

    rotated = runtime.reissue_approval_handle(
        first.approval.approval_handle_id,
        requester=_user(),
    )
    assert rotated.approval_id == first.approval.approval_id
    assert rotated.approval_handle_id != first.approval.approval_handle_id
    with pytest.raises(ValueError, match="invalid"):
        runtime.store.by_handle(first.approval.approval_handle_id)
    assert runtime.start_access_request(_request()).approval.approval_handle_id == (
        rotated.approval_handle_id
    )
    runtime.close()


@pytest.mark.parametrize(
    "requester, expected",
    [
        (_user(tenant_id="tenant-two"), "own"),
        (_user(user_id="employee-two"), "own"),
    ],
)
def test_handle_recovery_rejects_wrong_requester_identity(tmp_path, requester, expected) -> None:
    runtime = _runtime(tmp_path / "state", [100.0])
    paused = runtime.start_access_request(_request())
    with pytest.raises(PermissionError, match=expected):
        runtime.reissue_approval_handle(
            paused.approval.approval_handle_id,
            requester=requester,
        )
    runtime.close()


def test_completed_generation_is_stable_and_next_generation_is_independent(tmp_path) -> None:
    now = [100.0]
    trajectory = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3")
    runtime = _runtime(tmp_path / "state", now, trajectory_store=trajectory)
    first = runtime.start_access_request(_request())
    completed = runtime.resume_access_request(
        first.approval.approval_handle_id,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=first.approval.tool_call_sha256,
    )
    repeated_start = runtime.start_access_request(_request())
    second = runtime.start_access_request(_request(start_idempotency_key="client-operation-002"))

    assert repeated_start.status == completed.status == "completed"
    assert repeated_start.draft == completed.draft
    assert second.status == "needs_approval"
    assert second.approval.approval_generation == 2
    assert runtime.store.committed_count() == runtime.store.draft_count() == 1
    assert runtime.store.completion_count() == 1
    first_record = runtime.store.by_handle(first.approval.approval_handle_id)
    second_record = runtime.store.by_handle(second.approval.approval_handle_id)
    assert first_record.trajectory_session_id != second_record.trajectory_session_id
    assert trajectory.verify(first_record.trajectory_session_id)
    assert trajectory.verify(second_record.trajectory_session_id)
    runtime.close()


def test_handle_is_not_logged_traced_or_sufficient_to_authorize(tmp_path) -> None:
    exporter = InMemorySpanExporter()
    provider = build_tracer_provider(exporter=exporter)
    telemetry = AgentTelemetry(provider)
    runtime = _runtime(tmp_path / "state", [100.0], telemetry=telemetry)
    paused = runtime.start_access_request(_request())
    handle = paused.approval.approval_handle_id

    with pytest.raises(PermissionError):
        runtime.resume_access_request(
            handle,
            decision="approve",
            reviewer=UserContext(
                user_id="attacker",
                tenant_id="tenant-one",
                region="cn",
                groups=["employees"],
                roles=["knowledge_reviewer"],
            ),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    provider.force_flush()
    serialized = json.dumps(
        [dict(span.attributes or {}) for span in exporter.get_finished_spans()],
        sort_keys=True,
    )
    assert handle not in serialized
    runtime.close()


def test_start_retry_and_resume_converge_without_duplicate_facts(tmp_path) -> None:
    now = [100.0]
    state_dir = tmp_path / "state"
    first = _runtime(state_dir, now)
    paused = first.start_access_request(_request())
    second = _runtime(state_dir, now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        start_future = pool.submit(second.start_access_request, _request())
        resume_future = pool.submit(
            first.resume_access_request,
            paused.approval.approval_handle_id,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        results = [start_future.result(), resume_future.result()]

    assert {result.status for result in results}.issubset({"needs_approval", "completed"})
    assert first.store.approval_count() == 1
    assert first.store.committed_count() == first.store.draft_count() == 1
    assert first.store.completion_count() == 1
    first.close()
    second.close()


def test_start_schema_persists_hashes_owners_and_generation_without_raw_owner(tmp_path) -> None:
    now = [100.0]
    captured = []
    runtime = _runtime(
        tmp_path / "state",
        now,
        after_start_acquired=lambda record: captured.append(record),
    )
    paused = runtime.start_access_request(_request())
    record = runtime.store.by_handle(paused.approval.approval_handle_id)
    assert captured[0].start_owner_token_sha256 is not None
    assert record.start_scope_sha256 and record.generation_scope_sha256
    assert record.request_binding_sha256 and record.start_key_sha256
    assert record.start_owner_token_sha256 is None
    assert record.start_version == record.start_attempt == record.approval_generation == 1
    with sqlite3.connect(runtime.store.path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM durable_approvals WHERE approval_generation = 1"
        ).fetchone()
    assert row[0] == 1
    runtime.close()
