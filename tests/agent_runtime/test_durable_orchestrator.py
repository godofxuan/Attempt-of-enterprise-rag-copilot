from __future__ import annotations

import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.durable_orchestrator import (
    DurableAccessRequestWorkflow,
    DurableLangGraphOrchestrator,
    DurableToolRunRequest,
)
from app.agent_runtime.durable_store import DurableStoreConflict, ResumeOutcome
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
        "session_id": "durable-session-one",
        "run_id": "durable-run-one",
        "trace_id": "durable-trace-one",
        "arguments": AccessRequestDraftArguments(
            resource_id="finance/policy-7",
            requested_group="finance-readers",
            reason="Need access for quarter-end review.",
        ),
        "deadline_at_ms": 1000.0,
        "authentication_expires_at_ms": 1000.0,
        "approval_expires_at_ms": 900.0,
    }
    values.update(updates)
    return DurableToolRunRequest(**values)


def _reviewer(**updates) -> UserContext:
    values = {
        "user_id": "reviewer-one",
        "tenant_id": "tenant-one",
        "region": "cn",
        "groups": ["employees"],
        "roles": ["knowledge_reviewer"],
    }
    values.update(updates)
    return UserContext(**values)


def _orchestrator(
    state_dir,
    now,
    trajectory_store=None,
    checkpointer=None,
    telemetry=None,
    tenant_status_checker=None,
    acl_revalidator=None,
    resume_lease_ms=50.0,
    after_resume_acquired=None,
):
    return DurableAccessRequestWorkflow(
        V2ToolRegistry(RecordingNavigator(), clock_ms=lambda: now[0]),
        state_dir=state_dir,
        clock_ms=lambda: now[0],
        trajectory_store=trajectory_store,
        checkpointer=checkpointer,
        telemetry=telemetry,
        tenant_status_checker=tenant_status_checker,
        acl_revalidator=acl_revalidator,
        resume_lease_ms=resume_lease_ms,
        after_resume_acquired=after_resume_acquired,
    )


def test_interrupt_survives_process_restart_and_duplicate_resume_is_idempotent(tmp_path) -> None:
    now = [100.0]
    trajectory = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3")
    first_process = _orchestrator(tmp_path / "state", now, trajectory)
    paused = first_process.start_access_request(_request())
    assert paused.status == "needs_approval"
    first_process.close()

    second_process = _orchestrator(tmp_path / "state", now, trajectory)
    completed = second_process.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )
    repeated = second_process.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )

    assert completed.status == "completed"
    assert repeated.resume_outcome == ResumeOutcome.ALREADY_COMPLETED
    assert completed.draft == repeated.draft
    assert completed.draft.acl_changed is False
    assert second_process.side_effects.committed_count() == 1
    assert trajectory.verify("durable-session-one") is True
    with pytest.raises(PermissionError, match="tenant"):
        second_process.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(tenant_id="tenant-two"),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    second_process.close()


def test_wrong_tenant_user_role_hash_and_expiry_cannot_resume(tmp_path) -> None:
    now = [100.0]
    runtime = _orchestrator(tmp_path / "state", now)
    paused = runtime.start_access_request(_request())

    with pytest.raises(PermissionError, match="tenant"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(tenant_id="tenant-two"),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    with pytest.raises(PermissionError, match="identity"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(user_id="reviewer-two"),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    with pytest.raises(PermissionError, match="role"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(roles=[]),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    with pytest.raises(PermissionError, match="arguments"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256="0" * 64,
        )
    now[0] = 901.0
    expired = runtime.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )
    assert expired.status == "expired"
    assert expired.resume_outcome == ResumeOutcome.EXPIRED
    assert runtime.side_effects.committed_count() == 0
    runtime.close()


def test_acl_deny_cannot_be_overridden_by_approval(tmp_path) -> None:
    runtime = _orchestrator(tmp_path / "state", [100.0])
    denied = runtime.start_access_request(_request(acl_decision="DENY"))

    assert denied.status == "denied"
    assert denied.approval is None
    assert runtime.side_effects.committed_count() == 0
    runtime.close()


def test_resume_revalidates_current_tenant_and_acl_state(tmp_path) -> None:
    now = [100.0]
    tenant_active = [True]
    acl = ["ALLOW"]
    runtime = _orchestrator(
        tmp_path / "tenant-state",
        now,
        tenant_status_checker=lambda tenant_id: tenant_active[0],
        acl_revalidator=lambda request: acl[0],
    )
    paused = runtime.start_access_request(_request(session_id="tenant-session"))
    tenant_active[0] = False
    with pytest.raises(PermissionError, match="tenant"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    runtime.close()

    runtime = _orchestrator(
        tmp_path / "acl-state",
        now,
        tenant_status_checker=lambda tenant_id: True,
        acl_revalidator=lambda request: acl[0],
    )
    acl[0] = "ALLOW"
    paused = runtime.start_access_request(_request(session_id="acl-session"))
    acl[0] = "DENY"
    with pytest.raises(PermissionError, match="policy"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    assert runtime.side_effects.committed_count() == 0
    runtime.close()


def test_restart_resume_span_links_to_persisted_interrupt_span(tmp_path) -> None:
    now = [100.0]
    first_exporter = InMemorySpanExporter()
    first = _orchestrator(
        tmp_path / "state",
        now,
        telemetry=AgentTelemetry(build_tracer_provider(first_exporter)),
    )
    paused = first.start_access_request(_request())
    interrupt_span = next(
        span
        for span in first_exporter.get_finished_spans()
        if span.name == "agent.approval.interrupt"
    )
    first.close()

    second_exporter = InMemorySpanExporter()
    restarted = _orchestrator(
        tmp_path / "state",
        now,
        telemetry=AgentTelemetry(build_tracer_provider(second_exporter)),
    )
    restarted.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )
    resume_span = next(
        span
        for span in second_exporter.get_finished_spans()
        if span.name == "agent.approval.resume"
    )

    assert len(resume_span.links) == 1
    assert resume_span.links[0].context.trace_id == interrupt_span.context.trace_id
    assert resume_span.links[0].context.span_id == interrupt_span.context.span_id
    restarted.close()


@pytest.mark.parametrize("crash_point", ["before_commit", "after_commit"])
def test_restart_after_injected_commit_boundary_crash_executes_once(tmp_path, crash_point) -> None:
    now = [100.0]
    first = _orchestrator(tmp_path / "state", now)
    paused = first.start_access_request(_request())
    with pytest.raises(RuntimeError, match="injected crash"):
        first.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
            crash_point=crash_point,
        )
    first.close()

    now[0] = 151.0
    restarted = _orchestrator(tmp_path / "state", now)
    result = restarted.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )

    assert result.status == "completed"
    assert restarted.side_effects.committed_count() == 1
    assert restarted.side_effects.draft_count() == 1
    restarted.close()


def test_checkpointed_approval_decision_cannot_be_changed_during_retry(tmp_path) -> None:
    now = [100.0]
    runtime = _orchestrator(tmp_path / "state", now)
    paused = runtime.start_access_request(_request())
    with pytest.raises(RuntimeError, match="before"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
            crash_point="before_commit",
        )
    with pytest.raises(ValueError, match="already checkpointed"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="reject",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    assert runtime.side_effects.committed_count() == 0
    runtime.close()


def test_two_connections_concurrently_resume_once_and_complete_once(tmp_path) -> None:
    now = [100.0]
    owner_acquired = Event()
    release_owner = Event()
    trajectory_path = tmp_path / "trajectory.sqlite3"

    def hold_owner(record) -> None:
        owner_acquired.set()
        assert release_owner.wait(timeout=5.0)

    first = _orchestrator(
        tmp_path / "state",
        now,
        SQLiteTrajectoryStore(trajectory_path),
        after_resume_acquired=hold_owner,
    )
    paused = first.start_access_request(_request(session_id="concurrent-session"))
    second = _orchestrator(
        tmp_path / "state",
        now,
        SQLiteTrajectoryStore(trajectory_path),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner_future = pool.submit(
            first.resume_access_request,
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        assert owner_acquired.wait(timeout=5.0)
        competing_future = pool.submit(
            second.resume_access_request,
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        competing = competing_future.result(timeout=5.0)
        release_owner.set()
        completed = owner_future.result(timeout=5.0)

    record = second.store.by_token(paused.approval.approval_token)
    events = SQLiteTrajectoryStore(trajectory_path).load("concurrent-session")
    assert competing.status == "already_resuming"
    assert competing.resume_outcome == ResumeOutcome.ALREADY_RESUMING
    assert completed.status == "completed"
    assert record.status == "COMPLETED"
    assert record.attempt == 1
    assert record.version == 1
    assert record.owner_token_sha256 is None
    assert second.store.committed_count() == 1
    assert second.store.draft_count() == 1
    assert second.store.completion_count() == 1
    assert second.store.completion_delivery_count() == 1
    assert [event.event_type for event in events].count("session.completed") == 1
    first.close()
    second.close()


def test_two_store_connections_read_pending_then_only_one_cas_owner(tmp_path) -> None:
    now = [100.0]
    runtime = _orchestrator(tmp_path / "state", now)
    paused = runtime.start_access_request(_request(session_id="pending-cas-race"))
    first_store = runtime.store
    second_store = type(first_store)(first_store.path)
    both_read_pending = Barrier(2)

    def observe_then_claim(store):
        observed = store.by_token(paused.approval.approval_token)
        assert observed.status == "PENDING"
        both_read_pending.wait(timeout=5.0)
        return store.claim_resume(
            approval_id=observed.approval_id,
            approval_token=paused.approval.approval_token,
            decision="approve",
            resumed_by="reviewer-one",
            now_ms=now[0],
            lease_ms=50.0,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(observe_then_claim, (first_store, second_store)))

    assert {claim.outcome for claim in claims} == {
        ResumeOutcome.ACQUIRED,
        ResumeOutcome.ALREADY_RESUMING,
    }
    record = first_store.by_token(paused.approval.approval_token)
    assert record.status == "RESUMING"
    assert record.attempt == 1
    assert record.version == 1
    assert sum(claim.owner_token is not None for claim in claims) == 1
    owner_token = next(claim.owner_token for claim in claims if claim.owner_token is not None)
    persisted_bytes = b"".join(
        path.read_bytes() for path in first_store.path.parent.glob("approvals.sqlite3*")
    )
    assert paused.approval.approval_token.encode() not in persisted_bytes
    assert owner_token.encode() not in persisted_bytes
    runtime.close()


def test_v1_approval_database_is_migrated_in_place(tmp_path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    approval_path = state_dir / "approvals.sqlite3"
    request = _request(session_id="legacy-pending")
    token = hashlib.sha256(b"legacy-approval-fixture").hexdigest()
    with sqlite3.connect(approval_path) as connection:
        connection.execute(
            """
            CREATE TABLE durable_approvals (
                approval_id TEXT PRIMARY KEY,
                token_sha256 TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL UNIQUE,
                request_json TEXT NOT NULL,
                tool_call_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETED','REJECTED')),
                continuation_trace_json TEXT NOT NULL,
                result_json TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO durable_approvals VALUES (?, ?, ?, ?, ?, 'PENDING', ?, NULL)",
            (
                "approval-legacy",
                hashlib.sha256(token.encode()).hexdigest(),
                "durable-legacy-thread",
                request.model_dump_json(),
                hashlib.sha256(b"legacy-call").hexdigest(),
                '{"trace_id":"00000000000000000000000000000001","span_id":"0000000000000001"}',
            ),
        )

    runtime = _orchestrator(state_dir, [100.0])
    migrated = runtime.store.by_token(token)

    assert runtime.store.path == approval_path
    assert migrated.status == "PENDING"
    assert migrated.approval_expires_at_ms == request.approval_expires_at_ms
    assert migrated.version == 0
    assert migrated.attempt == 0
    runtime.close()


@pytest.mark.parametrize(
    ("wrong_reviewer", "message"),
    [
        (_reviewer(tenant_id="tenant-two"), "tenant"),
        (_reviewer(user_id="reviewer-two"), "identity"),
    ],
)
def test_wrong_identity_cannot_compete_for_resume_ownership(
    tmp_path, wrong_reviewer, message
) -> None:
    now = [100.0]
    owner_acquired = Event()
    release_owner = Event()

    def hold_owner(record) -> None:
        owner_acquired.set()
        assert release_owner.wait(timeout=5.0)

    first = _orchestrator(tmp_path / "state", now, after_resume_acquired=hold_owner)
    paused = first.start_access_request(_request(session_id="tenant-race"))
    second = _orchestrator(tmp_path / "state", now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner_future = pool.submit(
            first.resume_access_request,
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        assert owner_acquired.wait(timeout=5.0)
        wrong_future = pool.submit(
            second.resume_access_request,
            paused.approval.approval_token,
            decision="approve",
            reviewer=wrong_reviewer,
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        with pytest.raises(PermissionError, match=message):
            wrong_future.result(timeout=5.0)
        assert second.store.by_token(paused.approval.approval_token).attempt == 1
        release_owner.set()
        assert owner_future.result(timeout=5.0).status == "completed"
    first.close()
    second.close()


def test_expired_resume_lease_is_recovered_with_new_fencing_version(tmp_path) -> None:
    now = [100.0]

    def crash_after_claim(record) -> None:
        raise RuntimeError("simulated process exit after CAS")

    first = _orchestrator(
        tmp_path / "state",
        now,
        resume_lease_ms=50.0,
        after_resume_acquired=crash_after_claim,
    )
    paused = first.start_access_request(_request(session_id="lease-recovery"))
    with pytest.raises(RuntimeError, match="process exit"):
        first.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    first_record = first.store.by_token(paused.approval.approval_token)
    assert first_record.status == "RESUMING"
    assert first_record.version == 1
    first.close()

    now[0] = 151.0
    recovered = _orchestrator(tmp_path / "state", now, resume_lease_ms=50.0)
    result = recovered.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )
    final_record = recovered.store.by_token(paused.approval.approval_token)
    assert result.status == "completed"
    assert result.resume_outcome == ResumeOutcome.RECOVERED
    assert final_record.status == "COMPLETED"
    assert final_record.version == 2
    assert final_record.attempt == 2
    assert recovered.store.committed_count() == 1
    assert recovered.store.completion_count() == 1
    recovered.close()


def test_stale_owner_cannot_finalize_after_lease_recovery(tmp_path) -> None:
    now = [100.0]
    stale_owner_acquired = Event()
    release_stale_owner = Event()

    def hold_stale_owner(record) -> None:
        stale_owner_acquired.set()
        assert release_stale_owner.wait(timeout=5.0)

    stale = _orchestrator(
        tmp_path / "state",
        now,
        resume_lease_ms=50.0,
        after_resume_acquired=hold_stale_owner,
    )
    paused = stale.start_access_request(_request(session_id="stale-owner-fence"))
    recovered = _orchestrator(tmp_path / "state", now, resume_lease_ms=50.0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_future = pool.submit(
            stale.resume_access_request,
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        assert stale_owner_acquired.wait(timeout=5.0)
        now[0] = 151.0
        recovered_result = recovered.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        release_stale_owner.set()
        with pytest.raises(DurableStoreConflict, match="FENCING_CONFLICT"):
            stale_future.result(timeout=5.0)

    record = recovered.store.by_token(paused.approval.approval_token)
    assert recovered_result.status == "completed"
    assert recovered_result.resume_outcome == ResumeOutcome.RECOVERED
    assert record.status == "COMPLETED"
    assert record.version == 2
    assert recovered.store.committed_count() == 1
    assert recovered.store.completion_count() == 1
    stale.close()
    recovered.close()


def test_recoverable_internal_failure_releases_ownership_for_retry(tmp_path, monkeypatch) -> None:
    now = [100.0]
    runtime = _orchestrator(tmp_path / "state", now)
    paused = runtime.start_access_request(_request(session_id="recoverable-failure"))
    original_resume_graph = runtime._resume_graph

    def fail_graph(*args, **kwargs):
        raise OSError("checkpoint temporarily unavailable")

    monkeypatch.setattr(runtime, "_resume_graph", fail_graph)
    with pytest.raises(OSError, match="temporarily unavailable"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
    failed = runtime.store.by_token(paused.approval.approval_token)
    assert failed.status == "FAILED_RECOVERABLE"
    assert failed.failure_code == "OSError"
    assert runtime.store.committed_count() == 0
    assert runtime.store.completion_count() == 0

    monkeypatch.setattr(runtime, "_resume_graph", original_resume_graph)
    completed = runtime.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )
    assert completed.status == "completed"
    assert completed.resume_outcome == ResumeOutcome.RECOVERED
    assert runtime.store.by_token(paused.approval.approval_token).attempt == 2
    runtime.close()


def test_two_connections_concurrently_expire_without_acquiring_ownership(
    tmp_path,
) -> None:
    now = [100.0]
    first = _orchestrator(tmp_path / "state", now)
    paused = first.start_access_request(_request(session_id="concurrent-expiry"))
    second = _orchestrator(tmp_path / "state", now)
    now[0] = 901.0

    def expire(runtime):
        return runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(expire, (first, second)))

    record = first.store.by_token(paused.approval.approval_token)
    assert {result.resume_outcome for result in results} == {ResumeOutcome.EXPIRED}
    assert record.status == "EXPIRED"
    assert record.attempt == 0
    assert record.version == 1
    assert first.store.committed_count() == 0
    assert first.store.completion_count() == 0
    first.close()
    second.close()


@pytest.mark.parametrize(
    "crash_point",
    [
        "before_effect_commit",
        "after_effect_before_completion",
        "after_completion_before_approval",
        "after_approval_before_commit",
        "after_commit_before_response",
    ],
)
def test_atomic_failure_matrix_recovers_without_duplicate_facts(tmp_path, crash_point) -> None:
    now = [100.0]
    first = _orchestrator(tmp_path / crash_point, now, resume_lease_ms=50.0)
    paused = first.start_access_request(_request(session_id=f"failure-{crash_point}"))
    with pytest.raises(RuntimeError, match="injected crash"):
        first.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
            crash_point=crash_point,
        )
    record = first.store.by_token(paused.approval.approval_token)
    committed = first.store.committed_count()
    completions = first.store.completion_count()
    if crash_point == "after_commit_before_response":
        assert (record.status, committed, completions) == ("COMPLETED", 1, 1)
    else:
        assert (record.status, committed, completions) == ("RESUMING", 0, 0)
        now[0] = 151.0
    first.close()

    recovered = _orchestrator(tmp_path / crash_point, now, resume_lease_ms=50.0)
    result = recovered.resume_access_request(
        paused.approval.approval_token,
        decision="approve",
        reviewer=_reviewer(),
        expected_tool_call_sha256=paused.approval.tool_call_sha256,
    )
    assert result.status == "completed"
    assert recovered.store.committed_count() == 1
    assert recovered.store.draft_count() == 1
    assert recovered.store.completion_count() == 1
    assert recovered.store.by_token(paused.approval.approval_token).status == "COMPLETED"
    recovered.close()


def test_post_commit_retry_projects_completion_trajectory_exactly_once(tmp_path) -> None:
    now = [100.0]
    trajectory_path = tmp_path / "trajectory.sqlite3"
    runtime = _orchestrator(
        tmp_path / "state",
        now,
        SQLiteTrajectoryStore(trajectory_path),
    )
    paused = runtime.start_access_request(_request(session_id="post-commit-delivery"))

    with pytest.raises(RuntimeError, match="after commit"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
            crash_point="after_commit_before_response",
        )

    for _ in range(2):
        result = runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
        assert result.status == "completed"
        assert result.resume_outcome == ResumeOutcome.ALREADY_COMPLETED

    events = SQLiteTrajectoryStore(trajectory_path).load("post-commit-delivery")
    event_types = [event.event_type for event in events]
    assert event_types.count("human_review.completed") == 1
    assert event_types.count("terminal.reached") == 1
    assert event_types.count("session.completed") == 1
    assert runtime.store.committed_count() == 1
    assert runtime.store.completion_count() == 1
    assert runtime.store.completion_delivery_count() == 1
    runtime.close()


def test_deprecated_orchestrator_name_is_only_a_scoped_compatibility_alias(
    tmp_path,
) -> None:
    with pytest.warns(DeprecationWarning, match="access-request DRAFT"):
        legacy = DurableLangGraphOrchestrator(
            V2ToolRegistry(RecordingNavigator(), clock_ms=lambda: 100.0),
            state_dir=tmp_path / "legacy",
            clock_ms=lambda: 100.0,
        )
    assert not hasattr(legacy, "run")
    legacy.close()


@pytest.mark.integration
def test_postgres_checkpointer_setup_and_interrupt_roundtrip(tmp_path) -> None:
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is not configured")
    now = [100.0]
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        runtime = _orchestrator(tmp_path / "state", now, checkpointer=saver)
        paused = runtime.start_access_request(
            _request(session_id="postgres-session", run_id="postgres-run")
        )
        assert paused.status == "needs_approval"


@pytest.mark.integration
def test_postgres_checkpointer_concurrent_resume_is_database_fenced(tmp_path) -> None:
    dsn = os.environ.get("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is not configured")
    now = [100.0]
    owner_acquired = Event()
    release_owner = Event()

    def hold_owner(record) -> None:
        owner_acquired.set()
        assert release_owner.wait(timeout=10.0)

    with (
        PostgresSaver.from_conn_string(dsn) as first_saver,
        PostgresSaver.from_conn_string(dsn) as second_saver,
    ):
        first_saver.setup()
        second_saver.setup()
        first = _orchestrator(
            tmp_path / "postgres-concurrent",
            now,
            checkpointer=first_saver,
            after_resume_acquired=hold_owner,
        )
        paused = first.start_access_request(
            _request(
                session_id="postgres-concurrent-session",
                run_id="postgres-concurrent-run",
            )
        )
        second = _orchestrator(
            tmp_path / "postgres-concurrent",
            now,
            checkpointer=second_saver,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            owner_future = pool.submit(
                first.resume_access_request,
                paused.approval.approval_token,
                decision="approve",
                reviewer=_reviewer(),
                expected_tool_call_sha256=paused.approval.tool_call_sha256,
            )
            assert owner_acquired.wait(timeout=10.0)
            competing_future = pool.submit(
                second.resume_access_request,
                paused.approval.approval_token,
                decision="approve",
                reviewer=_reviewer(),
                expected_tool_call_sha256=paused.approval.tool_call_sha256,
            )
            competing = competing_future.result(timeout=10.0)
            release_owner.set()
            completed = owner_future.result(timeout=10.0)

        assert competing.resume_outcome == ResumeOutcome.ALREADY_RESUMING
        assert completed.status == "completed"
        assert second.store.committed_count() == 1
        assert second.store.completion_count() == 1
        assert second.store.by_token(paused.approval.approval_token).attempt == 1
        first.close()
        second.close()
