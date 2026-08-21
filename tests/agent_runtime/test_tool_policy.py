from __future__ import annotations

import json

import pytest

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.tool_contract import ToolContext
from app.agent_runtime.tool_gateway import ToolGateway
from app.agent_runtime.tool_policy import (
    PolicyDecision,
    PolicyHookDispatcher,
    SQLitePolicyAuditStore,
    ToolPolicy,
    ToolPolicyInput,
    normalized_arguments_sha256,
)
from app.domain.queries import UserContext
from tests.agent_runtime.test_tool_contract import search_request
from tests.v2_test_support import RecordingNavigator, search_hit, search_result


def policy_input(**updates) -> ToolPolicyInput:
    policy = ToolPolicy()
    values = {
        "tenant_id": "tenant-one",
        "user_id": "employee-one",
        "roles": (),
        "session_id": "session-one",
        "run_id": "run-one",
        "tool_name": "search",
        "normalized_arguments_sha256": normalized_arguments_sha256({"query": "policy"}),
        "acl_decision": "ALLOW",
        "budget_exhausted": False,
        "deadline_at_ms": 1000.0,
        "authentication_expires_at_ms": 1000.0,
        "evaluated_at_ms": 100.0,
        "tool_risk": policy.risk_for("search"),
    }
    values.update(updates)
    return ToolPolicyInput(**values)


def test_deny_precedes_ask_and_allow_and_unknown_tools_fail_closed() -> None:
    policy = ToolPolicy()
    ask_but_denied = policy_input(
        tool_name="create_access_request_draft",
        tool_risk=policy.risk_for("create_access_request_draft"),
        acl_decision="DENY",
    )
    unknown = policy_input(
        tool_name="shell",
        tool_risk=policy.risk_for("shell"),
    )

    assert policy.evaluate(ask_but_denied).decision == PolicyDecision.DENY
    assert policy.evaluate(ask_but_denied).reason_code == "acl_denied"
    assert policy.evaluate(unknown).reason_code == "unregistered_tool"


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"identity_override_attempted": True}, "identity_override_attempted"),
        ({"budget_exhausted": True}, "budget_exhausted"),
        ({"evaluated_at_ms": 1000.0}, "authentication_expired"),
        (
            {
                "evaluated_at_ms": 900.0,
                "deadline_at_ms": 900.0,
                "authentication_expires_at_ms": 1000.0,
            },
            "deadline_expired",
        ),
    ],
)
def test_identity_expiry_budget_and_deadline_fail_closed(updates, reason) -> None:
    assert ToolPolicy().evaluate(policy_input(**updates)).reason_code == reason


def test_ask_cannot_be_treated_as_allow() -> None:
    policy = ToolPolicy()
    result = policy.evaluate(
        policy_input(
            tool_name="create_access_request_draft",
            tool_risk=policy.risk_for("create_access_request_draft"),
        )
    )
    assert result.decision == PolicyDecision.ASK
    assert result.decision != PolicyDecision.ALLOW


def test_hook_failure_blocks_guarded_gateway_output() -> None:
    class BrokenPostHook:
        def pre_tool_use(self, policy_input, result):
            return None

        def post_tool_use(self, policy_input, result, outcome_metadata):
            raise RuntimeError("do not leak this output")

        def tool_error(self, policy_input, result, error_code):
            return None

        def run_stop(self, session_id, run_id, reason):
            return None

    user = UserContext(
        user_id="employee-one",
        tenant_id="tenant-one",
        region="cn",
        groups=["employees"],
    )
    context = ToolContext(
        session_id="session-one",
        trace_id="trace-one",
        request_id="request-one",
        run_id="run-one",
        identity=user,
        acl_scope=("employees",),
        issued_at_ms=10.0,
        expires_at_ms=1000.0,
    )
    gateway = ToolGateway(
        V2ToolRegistry(
            RecordingNavigator(search_results=[search_result([search_hit()])]),
            clock_ms=lambda: 100.0,
        ),
        clock_ms=lambda: 100.0,
        policy_hooks=PolicyHookDispatcher(hooks=(BrokenPostHook(),)),
    )
    gateway.start_session(context)

    result = gateway.execute(search_request(), context)

    assert result.status == "error"
    assert result.error.code == "system"
    assert result.payload is None


def test_policy_audit_hashes_identity_and_redacts_secret_metadata(tmp_path) -> None:
    store = SQLitePolicyAuditStore(tmp_path / "policy.sqlite3")
    dispatcher = PolicyHookDispatcher(audit_store=store)
    value = policy_input()
    result = dispatcher.pre_tool_use(value)
    store.append(
        "tool_error",
        value,
        result,
        {"authorization": "Bearer TEST-SECRET", "error_code": "system"},
    )

    serialized = json.dumps(store.rows())
    assert "tenant-one" not in serialized
    assert "employee-one" not in serialized
    assert "TEST-SECRET" not in serialized
    assert "[REDACTED]" in serialized


def test_tool_error_hook_failure_preserves_original_business_exception(
    tmp_path, monkeypatch
) -> None:
    class OriginalBusinessError(RuntimeError):
        pass

    class BrokenErrorHook:
        def pre_tool_use(self, policy_input, result):
            return None

        def post_tool_use(self, policy_input, result, outcome_metadata):
            return None

        def tool_error(self, policy_input, result, error_code):
            raise ValueError("SECONDARY-HOOK-SECRET")

        def run_stop(self, session_id, run_id, reason):
            return None

    audit = SQLitePolicyAuditStore(tmp_path / "policy.sqlite3")
    dispatcher = PolicyHookDispatcher(hooks=(BrokenErrorHook(),), audit_store=audit)
    user = UserContext(
        user_id="employee-one",
        tenant_id="tenant-one",
        region="cn",
        groups=["employees"],
    )
    context = ToolContext(
        session_id="session-error-hook",
        trace_id="trace-error-hook",
        request_id="request-one",
        run_id="run-error-hook",
        identity=user,
        acl_scope=("employees",),
        issued_at_ms=10.0,
        expires_at_ms=1000.0,
    )
    gateway = ToolGateway(
        V2ToolRegistry(RecordingNavigator(), clock_ms=lambda: 100.0),
        clock_ms=lambda: 100.0,
        policy_hooks=dispatcher,
    )
    gateway.start_session(context)

    def fail_original(*args, **kwargs):
        raise OriginalBusinessError("ORIGINAL-CAUSE")

    monkeypatch.setattr(gateway._registry, "run", fail_original)

    with pytest.raises(OriginalBusinessError, match="ORIGINAL-CAUSE"):
        gateway.execute(search_request(), context)

    serialized = json.dumps(audit.hook_failure_rows())
    assert "tool_error" in serialized
    assert "ValueError" in serialized
    assert "SECONDARY-HOOK-SECRET" not in serialized


def test_run_stop_hook_failure_is_recorded_without_breaking_close(tmp_path) -> None:
    class BrokenStopHook:
        def pre_tool_use(self, policy_input, result):
            return None

        def post_tool_use(self, policy_input, result, outcome_metadata):
            return None

        def tool_error(self, policy_input, result, error_code):
            return None

        def run_stop(self, session_id, run_id, reason):
            raise RuntimeError("RUN-STOP-SECRET")

    audit = SQLitePolicyAuditStore(tmp_path / "policy.sqlite3")
    dispatcher = PolicyHookDispatcher(hooks=(BrokenStopHook(),), audit_store=audit)
    user = UserContext(
        user_id="employee-one",
        tenant_id="tenant-one",
        region="cn",
        groups=["employees"],
    )
    context = ToolContext(
        session_id="session-stop-hook",
        trace_id="trace-stop-hook",
        request_id="request-one",
        run_id="run-stop-hook",
        identity=user,
        acl_scope=("employees",),
        issued_at_ms=10.0,
        expires_at_ms=1000.0,
    )
    gateway = ToolGateway(
        V2ToolRegistry(
            RecordingNavigator(search_results=[search_result([search_hit()])]),
            clock_ms=lambda: 100.0,
        ),
        clock_ms=lambda: 100.0,
        policy_hooks=dispatcher,
    )
    gateway.start_session(context)

    completed = gateway.execute(search_request(), context)
    gateway.close_session(context.session_id)
    gateway.start_session(context)

    assert completed.status == "ok"
    serialized = json.dumps(audit.hook_failure_rows())
    assert "run_stop" in serialized
    assert "RuntimeError" in serialized
    assert "RUN-STOP-SECRET" not in serialized
