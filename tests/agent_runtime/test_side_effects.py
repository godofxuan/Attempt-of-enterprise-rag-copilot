from __future__ import annotations

import pytest

from app.agent_runtime.side_effects import (
    AccessRequestDraftArguments,
    SQLiteSideEffectStore,
)
from app.agent_runtime.tool_policy import ToolPolicy, ToolPolicyInput, normalized_arguments_sha256


def _input(arguments: AccessRequestDraftArguments) -> ToolPolicyInput:
    policy = ToolPolicy()
    return ToolPolicyInput(
        tenant_id="tenant-one",
        user_id="employee-one",
        roles=(),
        session_id="session-one",
        run_id="run-one",
        tool_name="create_access_request_draft",
        normalized_arguments_sha256=normalized_arguments_sha256(arguments),
        acl_decision="ALLOW",
        budget_exhausted=False,
        deadline_at_ms=1000.0,
        authentication_expires_at_ms=1000.0,
        evaluated_at_ms=100.0,
        tool_risk=policy.risk_for("create_access_request_draft"),
    )


def test_access_request_is_draft_only_and_duplicate_call_returns_same_result(tmp_path) -> None:
    store = SQLiteSideEffectStore(tmp_path / "effects.sqlite3")
    arguments = AccessRequestDraftArguments(
        resource_id="finance/policy-7",
        requested_group="finance-readers",
        reason="Need access for quarter-end review.",
    )
    value = _input(arguments)

    first = store.create_access_request_draft(value, arguments)
    second = store.create_access_request_draft(value, arguments)

    assert first == second
    assert first.status == "DRAFT"
    assert first.acl_changed is False
    assert store.committed_count() == 1
    assert store.draft_count() == 1


def test_crash_before_commit_rolls_back_and_after_commit_is_recoverable(tmp_path) -> None:
    store = SQLiteSideEffectStore(tmp_path / "effects.sqlite3")
    arguments = AccessRequestDraftArguments(
        resource_id="finance/policy-7",
        requested_group="finance-readers",
        reason="Need access for quarter-end review.",
    )
    value = _input(arguments)

    with pytest.raises(RuntimeError, match="before"):
        store.create_access_request_draft(value, arguments, crash_point="before_commit")
    assert store.committed_count() == 0

    with pytest.raises(RuntimeError, match="after"):
        store.create_access_request_draft(value, arguments, crash_point="after_commit")
    recovered = store.create_access_request_draft(value, arguments)

    assert recovered.status == "DRAFT"
    assert store.committed_count() == 1
