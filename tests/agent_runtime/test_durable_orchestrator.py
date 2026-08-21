from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.durable_orchestrator import (
    DurableLangGraphOrchestrator,
    DurableToolRunRequest,
)
from app.agent_runtime.side_effects import AccessRequestDraftArguments
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from app.agent_runtime.telemetry import AgentTelemetry, build_tracer_provider
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
):
    return DurableLangGraphOrchestrator(
        V2ToolRegistry(RecordingNavigator(), clock_ms=lambda: now[0]),
        state_dir=state_dir,
        clock_ms=lambda: now[0],
        trajectory_store=trajectory_store,
        checkpointer=checkpointer,
        telemetry=telemetry,
        tenant_status_checker=tenant_status_checker,
        acl_revalidator=acl_revalidator,
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
    with pytest.raises(PermissionError, match="expired"):
        runtime.resume_access_request(
            paused.approval.approval_token,
            decision="approve",
            reviewer=_reviewer(),
            expected_tool_call_sha256=paused.approval.tool_call_sha256,
        )
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
