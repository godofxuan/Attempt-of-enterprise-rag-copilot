from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


POLICY_VERSION = "tool-policy.v1"


class ToolRisk(StrEnum):
    READ_ONLY = "READ_ONLY"
    SENSITIVE_READ = "SENSITIVE_READ"
    SIDE_EFFECT = "SIDE_EFFECT"
    ADMIN_FORBIDDEN = "ADMIN_FORBIDDEN"


class PolicyDecision(StrEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ToolPolicyInput(_FrozenModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    roles: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    session_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=100)
    normalized_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acl_decision: Literal["ALLOW", "DENY"]
    budget_exhausted: bool
    deadline_at_ms: float = Field(ge=0)
    authentication_expires_at_ms: float = Field(ge=0)
    evaluated_at_ms: float = Field(ge=0)
    tool_risk: ToolRisk
    policy_version: Literal["tool-policy.v1"] = POLICY_VERSION
    identity_override_attempted: bool = False


class PolicyResult(_FrozenModel):
    decision: PolicyDecision
    reason_code: str = Field(min_length=1, max_length=100)
    policy_version: Literal["tool-policy.v1"] = POLICY_VERSION


class ToolHook(Protocol):
    def pre_tool_use(self, policy_input: ToolPolicyInput, result: PolicyResult) -> None: ...

    def post_tool_use(
        self,
        policy_input: ToolPolicyInput,
        result: PolicyResult,
        outcome_metadata: Mapping[str, Any],
    ) -> None: ...

    def tool_error(
        self,
        policy_input: ToolPolicyInput,
        result: PolicyResult,
        error_code: str,
    ) -> None: ...

    def run_stop(self, session_id: str, run_id: str, reason: str) -> None: ...


class NoOpToolHook:
    def pre_tool_use(self, policy_input: ToolPolicyInput, result: PolicyResult) -> None:
        return None

    def post_tool_use(
        self,
        policy_input: ToolPolicyInput,
        result: PolicyResult,
        outcome_metadata: Mapping[str, Any],
    ) -> None:
        return None

    def tool_error(
        self,
        policy_input: ToolPolicyInput,
        result: PolicyResult,
        error_code: str,
    ) -> None:
        return None

    def run_stop(self, session_id: str, run_id: str, reason: str) -> None:
        return None


class ToolPolicy:
    """Deterministic authorization policy. Models cannot alter this decision."""

    _RISKS: dict[str, ToolRisk] = {
        "search": ToolRisk.READ_ONLY,
        "find": ToolRisk.READ_ONLY,
        "open": ToolRisk.SENSITIVE_READ,
        "export_evidence_bundle": ToolRisk.SIDE_EFFECT,
        "create_access_request_draft": ToolRisk.SIDE_EFFECT,
        "mutate_acl": ToolRisk.ADMIN_FORBIDDEN,
        "unrestricted_fetch": ToolRisk.ADMIN_FORBIDDEN,
        "raw_database_query": ToolRisk.ADMIN_FORBIDDEN,
    }
    _ASK = {"export_evidence_bundle", "create_access_request_draft"}

    def risk_for(self, tool_name: str) -> ToolRisk:
        return self._RISKS.get(tool_name, ToolRisk.ADMIN_FORBIDDEN)

    def evaluate(self, value: ToolPolicyInput) -> PolicyResult:
        if value.acl_decision == "DENY":
            return PolicyResult(decision=PolicyDecision.DENY, reason_code="acl_denied")
        if value.identity_override_attempted:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason_code="identity_override_attempted",
            )
        if value.tool_risk == ToolRisk.ADMIN_FORBIDDEN:
            reason = (
                "admin_tool_forbidden"
                if value.tool_name in self._RISKS
                else "unregistered_tool"
            )
            return PolicyResult(decision=PolicyDecision.DENY, reason_code=reason)
        if value.evaluated_at_ms >= value.authentication_expires_at_ms:
            return PolicyResult(decision=PolicyDecision.DENY, reason_code="authentication_expired")
        if value.evaluated_at_ms >= value.deadline_at_ms:
            return PolicyResult(decision=PolicyDecision.DENY, reason_code="deadline_expired")
        if value.budget_exhausted:
            return PolicyResult(decision=PolicyDecision.DENY, reason_code="budget_exhausted")
        if value.tool_name in self._ASK:
            return PolicyResult(decision=PolicyDecision.ASK, reason_code="human_approval_required")
        return PolicyResult(decision=PolicyDecision.ALLOW, reason_code="policy_allowed")


class SQLitePolicyAuditStore:
    """Append-only, metadata-only policy audit log."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS tool_policy_audit (
                    audit_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    tenant_hash TEXT NOT NULL,
                    user_hash TEXT NOT NULL,
                    session_hash TEXT NOT NULL,
                    run_hash TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    outcome_json TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS tool_policy_audit_no_update
                BEFORE UPDATE ON tool_policy_audit BEGIN
                    SELECT RAISE(ABORT, 'policy audit is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS tool_policy_audit_no_delete
                BEFORE DELETE ON tool_policy_audit BEGIN
                    SELECT RAISE(ABORT, 'policy audit is append-only');
                END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def append(
        self,
        lifecycle: str,
        policy_input: ToolPolicyInput,
        result: PolicyResult,
        outcome_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        safe_outcome = sanitize_metadata(outcome_metadata or {})
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_policy_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    datetime.now(timezone.utc).isoformat(),
                    lifecycle,
                    _hash_identifier(policy_input.tenant_id),
                    _hash_identifier(policy_input.user_id),
                    _hash_identifier(policy_input.session_id),
                    _hash_identifier(policy_input.run_id),
                    policy_input.tool_name,
                    policy_input.normalized_arguments_sha256,
                    result.decision.value,
                    result.reason_code,
                    result.policy_version,
                    canonical_json(safe_outcome),
                ),
            )

    def rows(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_policy_audit ORDER BY created_at, audit_id"
            ).fetchall()
        return [dict(row) for row in rows]


class PolicyHookDispatcher:
    def __init__(
        self,
        *,
        policy: ToolPolicy | None = None,
        hooks: Sequence[ToolHook] = (),
        audit_store: SQLitePolicyAuditStore | None = None,
    ) -> None:
        self.policy = policy or ToolPolicy()
        self.hooks = tuple(hooks)
        self.audit_store = audit_store

    def pre_tool_use(self, value: ToolPolicyInput) -> PolicyResult:
        result = self.policy.evaluate(value)
        try:
            for hook in self.hooks:
                hook.pre_tool_use(value, result)
        except Exception as exc:
            result = PolicyResult(decision=PolicyDecision.DENY, reason_code="pre_hook_failed")
            self._audit("pre_tool_use", value, result, {"hook_error_type": type(exc).__name__})
            return result
        self._audit("pre_tool_use", value, result)
        return result

    def post_tool_use(
        self,
        value: ToolPolicyInput,
        result: PolicyResult,
        output: Any,
        *,
        schema: type[BaseModel] | None = None,
    ) -> PolicyResult:
        try:
            validated = schema.model_validate(output) if schema is not None else output
            metadata = limited_outcome_metadata(validated)
            for hook in self.hooks:
                hook.post_tool_use(value, result, metadata)
        except Exception as exc:
            denied = PolicyResult(decision=PolicyDecision.DENY, reason_code="post_hook_failed")
            self._audit("post_tool_use", value, denied, {"hook_error_type": type(exc).__name__})
            return denied
        self._audit("post_tool_use", value, result, metadata)
        return result

    def tool_error(self, value: ToolPolicyInput, result: PolicyResult, error_code: str) -> None:
        try:
            for hook in self.hooks:
                hook.tool_error(value, result, error_code)
        finally:
            self._audit("tool_error", value, result, {"error_code": error_code})

    def run_stop(self, *, session_id: str, run_id: str, reason: str) -> None:
        for hook in self.hooks:
            hook.run_stop(session_id, run_id, reason)

    def _audit(
        self,
        lifecycle: str,
        value: ToolPolicyInput,
        result: PolicyResult,
        outcome: Mapping[str, Any] | None = None,
    ) -> None:
        if self.audit_store is not None:
            self.audit_store.append(lifecycle, value, result, outcome)


def normalized_arguments_sha256(arguments: Any) -> str:
    if isinstance(arguments, BaseModel):
        arguments = arguments.model_dump(mode="json")
    return hashlib.sha256(canonical_json(arguments).encode("utf-8")).hexdigest()


def side_effect_key(value: ToolPolicyInput) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "tenant_id": value.tenant_id,
                "user_id": value.user_id,
                "run_id": value.run_id,
                "tool_name": value.tool_name,
                "arguments_sha256": value.normalized_arguments_sha256,
            }
        ).encode("utf-8")
    ).hexdigest()


def limited_outcome_metadata(output: Any) -> dict[str, Any]:
    if isinstance(output, BaseModel):
        raw = output.model_dump(mode="json")
    elif isinstance(output, Mapping):
        raw = dict(output)
    else:
        raw = {"type": type(output).__name__}
    metadata: dict[str, Any] = {"output_type": type(output).__name__}
    for key in ("status", "tool", "sequence", "reason_code"):
        if key in raw and isinstance(raw[key], (str, int, float, bool, type(None))):
            metadata[key] = raw[key]
    payload = raw.get("payload")
    if isinstance(payload, Mapping):
        for key in ("outcome", "stop_reason"):
            if key in payload and isinstance(
                payload[key], (str, int, float, bool, type(None))
            ):
                metadata[f"payload_{key}"] = payload[key]
    metadata["output_sha256"] = hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()
    return metadata


def sanitize_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    secret_parts = ("authorization", "token", "secret", "password", "cookie", "api_key")
    for raw_key, raw_value in value.items():
        key = str(raw_key)[:100]
        if any(part in key.lower() for part in secret_parts):
            result[key] = "[REDACTED]"
        elif isinstance(raw_value, (str, int, float, bool, type(None))):
            text = raw_value if not isinstance(raw_value, str) else raw_value[:500]
            result[key] = text
        else:
            result[key] = type(raw_value).__name__
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "NoOpToolHook",
    "POLICY_VERSION",
    "PolicyDecision",
    "PolicyHookDispatcher",
    "PolicyResult",
    "SQLitePolicyAuditStore",
    "ToolHook",
    "ToolPolicy",
    "ToolPolicyInput",
    "ToolRisk",
    "limited_outcome_metadata",
    "normalized_arguments_sha256",
    "sanitize_metadata",
    "side_effect_key",
]
