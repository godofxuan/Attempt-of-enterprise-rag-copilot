from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.tool_policy import ToolPolicyInput, side_effect_key


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AccessRequestDraftArguments(_FrozenModel):
    resource_id: str = Field(min_length=1, max_length=300)
    requested_group: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)


class AccessRequestDraft(_FrozenModel):
    draft_id: str = Field(pattern=r"^draft-[0-9a-f]{24}$")
    tenant_id_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requester_id_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_id_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_id_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_group: str
    status: Literal["DRAFT"] = "DRAFT"
    acl_changed: Literal[False] = False


class SQLiteSideEffectStore:
    """Transactional outbox for the one supported draft-only side effect."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS side_effect_commands (
                    idempotency_key TEXT PRIMARY KEY,
                    tenant_hash TEXT NOT NULL,
                    user_hash TEXT NOT NULL,
                    run_hash TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('COMMITTED')),
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_request_drafts (
                    draft_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    draft_json TEXT NOT NULL,
                    FOREIGN KEY (idempotency_key)
                        REFERENCES side_effect_commands(idempotency_key)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def create_access_request_draft(
        self,
        policy_input: ToolPolicyInput,
        arguments: AccessRequestDraftArguments,
        *,
        crash_point: Literal["before_commit", "after_commit"] | None = None,
    ) -> AccessRequestDraft:
        if policy_input.tool_name != "create_access_request_draft":
            raise ValueError("side-effect store only supports access request drafts")
        key = side_effect_key(policy_input)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT result_json FROM side_effect_commands WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                return AccessRequestDraft.model_validate_json(existing["result_json"])

            if crash_point == "before_commit":
                raise RuntimeError("injected crash before side-effect commit")
            digest = _sha256(key)
            draft = AccessRequestDraft(
                draft_id=f"draft-{digest[:24]}",
                tenant_id_hash=_sha256(policy_input.tenant_id),
                requester_id_hash=_sha256(policy_input.user_id),
                session_id_hash=_sha256(policy_input.session_id),
                resource_id_hash=_sha256(arguments.resource_id),
                requested_group=arguments.requested_group,
            )
            result_json = draft.model_dump_json()
            connection.execute(
                """
                INSERT INTO side_effect_commands (
                    idempotency_key, tenant_hash, user_hash, run_hash,
                    tool_name, arguments_sha256, status, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'COMMITTED', ?)
                """,
                (
                    key,
                    _sha256(policy_input.tenant_id),
                    _sha256(policy_input.user_id),
                    _sha256(policy_input.run_id),
                    policy_input.tool_name,
                    policy_input.normalized_arguments_sha256,
                    result_json,
                ),
            )
            connection.execute(
                "INSERT INTO access_request_drafts VALUES (?, ?, ?)",
                (draft.draft_id, key, result_json),
            )
            connection.commit()
        if crash_point == "after_commit":
            raise RuntimeError("injected crash after side-effect commit")
        return draft

    def committed_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM side_effect_commands"
            ).fetchone()
        return int(row["count"])

    def draft_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM access_request_drafts"
            ).fetchone()
        return int(row["count"])


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AccessRequestDraft",
    "AccessRequestDraftArguments",
    "SQLiteSideEffectStore",
]
