from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.side_effects import (
    AccessRequestDraft,
    AccessRequestDraftArguments,
    create_access_request_draft_in_transaction,
    initialize_side_effect_schema,
)
from app.agent_runtime.tool_policy import ToolPolicyInput

ApprovalStatus = Literal[
    "PENDING",
    "RESUMING",
    "COMPLETED",
    "REJECTED",
    "EXPIRED",
    "FAILED_RECOVERABLE",
]
ApprovalDecision = Literal["approve", "reject"]
StartStatus = Literal["STARTING", "READY", "FAILED_RECOVERABLE"]
CheckpointStatus = Literal["NOT_STARTED", "IN_PROGRESS", "READY"]
StartCrashPoint = Literal[
    "before_approval_insert",
    "after_approval_insert_before_checkpoint",
    "during_checkpoint",
    "after_checkpoint_before_ready",
    "after_ready_before_trajectory",
    "after_trajectory_before_response",
    "during_response",
]
IntegrityCrashPoint = Literal[
    "before_effect_commit",
    "after_effect_before_completion",
    "after_completion_before_approval",
    "after_approval_before_commit",
    "after_commit_before_response",
    "before_commit",
    "after_commit",
]


class ResumeOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    RECOVERED = "RECOVERED"
    ALREADY_RESUMING = "ALREADY_RESUMING"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class StartOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    RECOVERED = "RECOVERED"
    ALREADY_STARTING = "ALREADY_STARTING"
    READY = "READY"
    TERMINAL = "TERMINAL"


class DurableStoreConflict(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class InjectedIntegrityCrash(RuntimeError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ApprovalRecord(_FrozenModel):
    approval_id: str
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    thread_id: str
    request_json: str
    tool_call_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_expires_at_ms: float
    status: ApprovalStatus
    continuation_trace_json: str
    result_json: str | None = None
    owner_token_sha256: str | None = None
    lease_expires_at_ms: float | None = None
    version: int = Field(ge=0)
    attempt: int = Field(ge=0)
    resumed_by_sha256: str | None = None
    resumed_at_ms: float | None = None
    decision: ApprovalDecision | None = None
    failure_code: str | None = None
    start_scope_sha256: str | None = None
    generation_scope_sha256: str | None = None
    request_binding_sha256: str | None = None
    start_key_sha256: str | None = None
    approval_generation: int = Field(default=1, ge=1)
    client_handle_id: str | None = None
    trajectory_session_id: str | None = None
    start_status: StartStatus = "READY"
    checkpoint_status: CheckpointStatus = "READY"
    start_owner_token_sha256: str | None = None
    start_lease_expires_at_ms: float | None = None
    start_version: int = Field(default=0, ge=0)
    start_attempt: int = Field(default=0, ge=0)
    start_started_at_ms: float | None = None
    start_result_json: str | None = None
    start_trajectory_delivered_at_ms: float | None = None
    start_response_issued_at_ms: float | None = None
    client_acknowledged_at_ms: float | None = None


class ResumeClaim(_FrozenModel):
    outcome: ResumeOutcome
    record: ApprovalRecord
    owner_token: str | None = Field(default=None, repr=False)


class StartClaim(_FrozenModel):
    outcome: StartOutcome
    record: ApprovalRecord
    owner_token: str | None = Field(default=None, repr=False)


class CompletionEnvelope(_FrozenModel):
    schema_version: Literal["durable-completion-outbox/1.0"] = "durable-completion-outbox/1.0"
    approval_id: str
    session_id: str
    trace_id: str
    decision: ApprovalDecision
    result_status: str
    terminal_state: str
    reviewer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SQLiteDurableWorkflowStore:
    """CAS, draft effect, completion outbox, and approval state in one DB."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._initialize(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        existing = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'durable_approvals'"
        ).fetchone()
        if existing is not None and "RESUMING" not in str(existing["sql"]):
            self._migrate_v1_approval_table(connection)
        self._create_approval_table(connection)
        self._migrate_start_lifecycle_columns(connection)
        initialize_side_effect_schema(connection)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS durable_completion_outbox (
                completion_key TEXT PRIMARY KEY,
                approval_id TEXT NOT NULL UNIQUE,
                envelope_json TEXT NOT NULL,
                FOREIGN KEY (approval_id) REFERENCES durable_approvals(approval_id)
            );
            CREATE TABLE IF NOT EXISTS durable_completion_deliveries (
                completion_key TEXT PRIMARY KEY,
                delivered_at_ms REAL NOT NULL,
                FOREIGN KEY (completion_key)
                    REFERENCES durable_completion_outbox(completion_key)
            );
            CREATE TRIGGER IF NOT EXISTS durable_completion_outbox_no_update
            BEFORE UPDATE ON durable_completion_outbox BEGIN
                SELECT RAISE(ABORT, 'completion outbox is immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS durable_completion_outbox_no_delete
            BEFORE DELETE ON durable_completion_outbox BEGIN
                SELECT RAISE(ABORT, 'completion outbox is immutable');
            END;
            """
        )

    @staticmethod
    def _create_approval_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS durable_approvals (
                approval_id TEXT PRIMARY KEY,
                token_sha256 TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL UNIQUE,
                request_json TEXT NOT NULL,
                tool_call_sha256 TEXT NOT NULL,
                approval_expires_at_ms REAL NOT NULL,
                status TEXT NOT NULL CHECK (status IN (
                    'PENDING','RESUMING','COMPLETED','REJECTED','EXPIRED',
                    'FAILED_RECOVERABLE'
                )),
                continuation_trace_json TEXT NOT NULL,
                result_json TEXT,
                owner_token_sha256 TEXT,
                lease_expires_at_ms REAL,
                version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
                attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
                resumed_by_sha256 TEXT,
                resumed_at_ms REAL,
                decision TEXT CHECK (decision IN ('approve','reject')),
                failure_code TEXT
            )
            """
        )

    @staticmethod
    def _migrate_start_lifecycle_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(durable_approvals)").fetchall()
        }
        additions = {
            "start_scope_sha256": "TEXT",
            "generation_scope_sha256": "TEXT",
            "request_binding_sha256": "TEXT",
            "start_key_sha256": "TEXT",
            "approval_generation": "INTEGER NOT NULL DEFAULT 1 CHECK (approval_generation >= 1)",
            "client_handle_id": "TEXT",
            "trajectory_session_id": "TEXT",
            "start_status": (
                "TEXT NOT NULL DEFAULT 'READY' CHECK "
                "(start_status IN ('STARTING','READY','FAILED_RECOVERABLE'))"
            ),
            "checkpoint_status": (
                "TEXT NOT NULL DEFAULT 'READY' CHECK "
                "(checkpoint_status IN ('NOT_STARTED','IN_PROGRESS','READY'))"
            ),
            "start_owner_token_sha256": "TEXT",
            "start_lease_expires_at_ms": "REAL",
            "start_version": "INTEGER NOT NULL DEFAULT 0 CHECK (start_version >= 0)",
            "start_attempt": "INTEGER NOT NULL DEFAULT 0 CHECK (start_attempt >= 0)",
            "start_started_at_ms": "REAL",
            "start_result_json": "TEXT",
            "start_trajectory_delivered_at_ms": "REAL",
            "start_response_issued_at_ms": "REAL",
            "client_acknowledged_at_ms": "REAL",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE durable_approvals ADD COLUMN {name} {definition}")
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS durable_start_scope_unique
            ON durable_approvals(start_scope_sha256)
            WHERE start_scope_sha256 IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS durable_client_handle_unique
            ON durable_approvals(client_handle_id)
            WHERE client_handle_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS durable_generation_unique
            ON durable_approvals(generation_scope_sha256, approval_generation)
            WHERE generation_scope_sha256 IS NOT NULL;
            """
        )

    def _migrate_v1_approval_table(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM durable_approvals").fetchall()
        connection.execute("ALTER TABLE durable_approvals RENAME TO durable_approvals_v1")
        self._create_approval_table(connection)
        for row in rows:
            request = json.loads(row["request_json"])
            connection.execute(
                """
                INSERT INTO durable_approvals (
                    approval_id, token_sha256, thread_id, request_json,
                    tool_call_sha256, approval_expires_at_ms, status,
                    continuation_trace_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["approval_id"],
                    row["token_sha256"],
                    row["thread_id"],
                    row["request_json"],
                    row["tool_call_sha256"],
                    float(request["approval_expires_at_ms"]),
                    row["status"],
                    row["continuation_trace_json"],
                    row["result_json"],
                ),
            )
        connection.execute("DROP TABLE durable_approvals_v1")

    def create(
        self,
        *,
        request_json: str,
        approval_expires_at_ms: float,
        thread_id: str,
        tool_call_sha256: str,
        continuation_trace_json: str,
    ) -> tuple[ApprovalRecord, str]:
        token = secrets.token_urlsafe(32)
        approval_id = f"approval-{secrets.token_hex(12)}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO durable_approvals (
                    approval_id, token_sha256, thread_id, request_json,
                    tool_call_sha256, approval_expires_at_ms, status,
                    continuation_trace_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, NULL)
                """,
                (
                    approval_id,
                    _sha256(token),
                    thread_id,
                    request_json,
                    tool_call_sha256,
                    approval_expires_at_ms,
                    continuation_trace_json,
                ),
            )
        return self.by_token(token), token

    def begin_start(
        self,
        *,
        request_json: str,
        approval_expires_at_ms: float,
        start_scope_sha256: str,
        generation_scope_sha256: str,
        request_binding_sha256: str,
        start_key_sha256: str,
        tool_call_sha256: str,
        continuation_trace_json: str,
        base_session_id: str,
        now_ms: float,
        lease_ms: float,
    ) -> StartClaim:
        """Get or create one approval generation and acquire fenced Start ownership."""
        owner_token = secrets.token_urlsafe(32)
        owner_sha256 = _sha256(owner_token)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE start_scope_sha256 = ?",
                (start_scope_sha256,),
            ).fetchone()
            if row is None:
                generation_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(approval_generation), 0) + 1 AS generation
                    FROM durable_approvals WHERE generation_scope_sha256 = ?
                    """,
                    (generation_scope_sha256,),
                ).fetchone()
                generation = int(generation_row["generation"])
                approval_id = f"approval-{secrets.token_hex(12)}"
                client_handle_id = f"handle-{secrets.token_urlsafe(24)}"
                thread_id = _stable_thread_id(generation_scope_sha256, generation, approval_id)
                trajectory_session_id = (
                    base_session_id
                    if generation == 1
                    else _generation_session_id(base_session_id, generation, approval_id)
                )
                connection.execute(
                    """
                    INSERT INTO durable_approvals (
                        approval_id, token_sha256, thread_id, request_json,
                        tool_call_sha256, approval_expires_at_ms, status,
                        continuation_trace_json, result_json,
                        start_scope_sha256, generation_scope_sha256,
                        request_binding_sha256, start_key_sha256,
                        approval_generation, client_handle_id,
                        trajectory_session_id, start_status, checkpoint_status,
                        start_owner_token_sha256, start_lease_expires_at_ms,
                        start_version, start_attempt, start_started_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, NULL,
                              ?, ?, ?, ?, ?, ?, ?, 'STARTING', 'NOT_STARTED',
                              ?, ?, 1, 1, ?)
                    """,
                    (
                        approval_id,
                        _sha256(client_handle_id),
                        thread_id,
                        request_json,
                        tool_call_sha256,
                        approval_expires_at_ms,
                        continuation_trace_json,
                        start_scope_sha256,
                        generation_scope_sha256,
                        request_binding_sha256,
                        start_key_sha256,
                        generation,
                        client_handle_id,
                        trajectory_session_id,
                        owner_sha256,
                        now_ms + lease_ms,
                        now_ms,
                    ),
                )
                connection.commit()
                return StartClaim(
                    outcome=StartOutcome.ACQUIRED,
                    record=self.by_handle(client_handle_id),
                    owner_token=owner_token,
                )

            record = _record(row)
            if record.request_binding_sha256 != request_binding_sha256:
                raise DurableStoreConflict("START_IDEMPOTENCY_CONFLICT")
            if record.start_status == "READY":
                return StartClaim(
                    outcome=(
                        StartOutcome.TERMINAL
                        if record.status in {"COMPLETED", "REJECTED", "EXPIRED"}
                        else StartOutcome.READY
                    ),
                    record=record,
                )
            if (
                record.start_status == "STARTING"
                and record.start_lease_expires_at_ms is not None
                and record.start_lease_expires_at_ms > now_ms
            ):
                return StartClaim(outcome=StartOutcome.ALREADY_STARTING, record=record)
            recover = record.start_status in {"STARTING", "FAILED_RECOVERABLE"}
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET start_status = 'STARTING', start_owner_token_sha256 = ?,
                    start_lease_expires_at_ms = ?, start_version = start_version + 1,
                    start_attempt = start_attempt + 1, start_started_at_ms = ?,
                    failure_code = NULL
                WHERE approval_id = ? AND start_version = ?
                  AND (start_status = 'FAILED_RECOVERABLE'
                       OR (start_status = 'STARTING'
                           AND start_lease_expires_at_ms <= ?))
                """,
                (
                    owner_sha256,
                    now_ms + lease_ms,
                    now_ms,
                    record.approval_id,
                    record.start_version,
                    now_ms,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("START_CAS_CONFLICT")
            connection.commit()
        return StartClaim(
            outcome=StartOutcome.RECOVERED if recover else StartOutcome.ACQUIRED,
            record=self.by_handle(record.client_handle_id or ""),
            owner_token=owner_token,
        )

    def by_handle(self, approval_handle_id: str) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE client_handle_id = ?",
                (approval_handle_id,),
            ).fetchone()
        if row is None:
            raise ValueError("approval handle is invalid")
        return _record(row)

    def by_resume_locator(self, approval_handle_id: str) -> ApprovalRecord:
        """Resolve a current Handle or a hash-only locator from a migrated record."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM durable_approvals
                WHERE client_handle_id = ?
                   OR (client_handle_id IS NULL AND token_sha256 = ?)
                """,
                (approval_handle_id, _sha256(approval_handle_id)),
            ).fetchone()
        if row is None:
            raise ValueError("approval handle is invalid")
        return _record(row)

    def by_token(self, token: str) -> ApprovalRecord:
        """Legacy hashed-token lookup retained for pre-migration approvals."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE token_sha256 = ?",
                (_sha256(token),),
            ).fetchone()
        if row is None:
            raise ValueError("approval token is invalid")
        return _record(row)

    def mark_checkpoint_in_progress(
        self,
        *,
        approval_id: str,
        owner_token: str,
        start_version: int,
        now_ms: float,
    ) -> ApprovalRecord:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET checkpoint_status = 'IN_PROGRESS'
                WHERE approval_id = ? AND start_status = 'STARTING'
                  AND start_owner_token_sha256 = ? AND start_version = ?
                  AND start_lease_expires_at_ms > ?
                  AND checkpoint_status IN ('NOT_STARTED','IN_PROGRESS')
                """,
                (approval_id, _sha256(owner_token), start_version, now_ms),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("START_FENCING_CONFLICT")
        return self.by_approval_id(approval_id)

    def mark_checkpoint_ready(
        self,
        *,
        approval_id: str,
        owner_token: str,
        start_version: int,
        now_ms: float,
    ) -> ApprovalRecord:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET checkpoint_status = 'READY'
                WHERE approval_id = ? AND start_status = 'STARTING'
                  AND start_owner_token_sha256 = ? AND start_version = ?
                  AND start_lease_expires_at_ms > ?
                  AND checkpoint_status = 'IN_PROGRESS'
                """,
                (approval_id, _sha256(owner_token), start_version, now_ms),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("START_FENCING_CONFLICT")
        return self.by_approval_id(approval_id)

    def finalize_start(
        self,
        *,
        approval_id: str,
        owner_token: str,
        start_version: int,
        now_ms: float,
        result: Mapping[str, Any],
    ) -> ApprovalRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET start_status = 'READY', start_result_json = ?,
                    start_response_issued_at_ms = ?,
                    start_owner_token_sha256 = NULL,
                    start_lease_expires_at_ms = NULL, failure_code = NULL
                WHERE approval_id = ? AND start_status = 'STARTING'
                  AND checkpoint_status = 'READY'
                  AND start_owner_token_sha256 = ? AND start_version = ?
                  AND start_lease_expires_at_ms > ?
                """,
                (
                    _canonical_json(result),
                    now_ms,
                    approval_id,
                    _sha256(owner_token),
                    start_version,
                    now_ms,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("START_FENCING_CONFLICT")
            connection.commit()
        return self.by_approval_id(approval_id)

    def mark_start_trajectory_delivered(self, approval_id: str, *, delivered_at_ms: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE durable_approvals
                SET start_trajectory_delivered_at_ms = COALESCE(
                    start_trajectory_delivered_at_ms, ?
                )
                WHERE approval_id = ? AND start_status = 'READY'
                """,
                (delivered_at_ms, approval_id),
            )

    def mark_start_failed_recoverable(
        self,
        *,
        approval_id: str,
        owner_token: str,
        start_version: int,
        now_ms: float,
        failure_code: str,
    ) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET start_status = 'FAILED_RECOVERABLE',
                    start_owner_token_sha256 = NULL,
                    start_lease_expires_at_ms = NULL, failure_code = ?
                WHERE approval_id = ? AND start_status = 'STARTING'
                  AND start_owner_token_sha256 = ? AND start_version = ?
                  AND start_lease_expires_at_ms > ?
                """,
                (
                    failure_code[:100],
                    approval_id,
                    _sha256(owner_token),
                    start_version,
                    now_ms,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("START_FENCING_CONFLICT")

    def reap_expired_start_owners(self, *, now_ms: float) -> int:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET start_status = 'FAILED_RECOVERABLE',
                    start_owner_token_sha256 = NULL,
                    start_lease_expires_at_ms = NULL,
                    failure_code = 'start_owner_lease_expired'
                WHERE start_status = 'STARTING'
                  AND start_lease_expires_at_ms <= ?
                """,
                (now_ms,),
            )
        return int(changed.rowcount)

    def acknowledge_start(
        self,
        approval_handle_id: str,
        *,
        tenant_id: str,
        user_id: str,
        acknowledged_at_ms: float,
    ) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE client_handle_id = ?",
                (approval_handle_id,),
            ).fetchone()
            if row is None:
                raise ValueError("approval handle is invalid")
            request = json.loads(row["request_json"])
            if request["tenant_id"] != tenant_id or request["user_id"] != user_id:
                raise PermissionError("requester identity does not own this approval")
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET client_acknowledged_at_ms = COALESCE(client_acknowledged_at_ms, ?)
                WHERE approval_id = ? AND start_status = 'READY'
                """,
                (acknowledged_at_ms, row["approval_id"]),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("START_NOT_READY")
        return self.by_handle(approval_handle_id)

    def reissue_handle(
        self,
        approval_handle_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> ApprovalRecord:
        new_handle = f"handle-{secrets.token_urlsafe(24)}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE client_handle_id = ?",
                (approval_handle_id,),
            ).fetchone()
            if row is None:
                raise ValueError("approval handle is invalid")
            request = json.loads(row["request_json"])
            if request["tenant_id"] != tenant_id or request["user_id"] != user_id:
                raise PermissionError("requester identity does not own this approval")
            result = json.loads(row["start_result_json"]) if row["start_result_json"] else None
            if result is not None and result.get("approval"):
                result["approval"]["approval_handle_id"] = new_handle
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET client_handle_id = ?, token_sha256 = ?, start_result_json = ?
                WHERE approval_id = ? AND client_handle_id = ?
                """,
                (
                    new_handle,
                    _sha256(new_handle),
                    _canonical_json(result) if result is not None else None,
                    row["approval_id"],
                    approval_handle_id,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("HANDLE_REISSUE_CONFLICT")
            connection.commit()
        return self.by_handle(new_handle)

    def by_approval_id(self, approval_id: str) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            raise ValueError("approval is invalid")
        return _record(row)

    def approval_count(self) -> int:
        return self._count("durable_approvals")

    def expire_pending_approval(self, approval_id: str, *, now_ms: float) -> ApprovalRecord:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE durable_approvals
                SET status = 'EXPIRED', version = version + 1,
                    failure_code = 'approval_expired'
                WHERE approval_id = ? AND status = 'PENDING'
                  AND start_status = 'READY' AND approval_expires_at_ms <= ?
                """,
                (approval_id, now_ms),
            )
        return self.by_approval_id(approval_id)

    def claim_resume(
        self,
        *,
        approval_id: str,
        approval_handle_id: str | None = None,
        approval_token: str | None = None,
        decision: ApprovalDecision,
        resumed_by: str,
        now_ms: float,
        lease_ms: float,
    ) -> ResumeClaim:
        approval_handle_id = approval_handle_id or approval_token
        if approval_handle_id is None:
            raise ValueError("approval handle is required")
        owner_token = secrets.token_urlsafe(32)
        owner_sha256 = _sha256(owner_token)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM durable_approvals
                WHERE approval_id = ?
                  AND (client_handle_id = ?
                       OR (client_handle_id IS NULL AND token_sha256 = ?))
                """,
                (approval_id, approval_handle_id, _sha256(approval_handle_id)),
            ).fetchone()
            if row is None:
                raise ValueError("approval handle is invalid")
            record = _record(row)
            if record.start_status != "READY" or record.checkpoint_status != "READY":
                raise DurableStoreConflict("START_NOT_READY")
            terminal = _terminal_outcome(record.status)
            if terminal is not None:
                return ResumeClaim(outcome=terminal, record=record)
            if record.decision is not None and record.decision != decision:
                raise ValueError("approval decision was already checkpointed")
            if record.status == "RESUMING" and (
                record.lease_expires_at_ms is None or record.lease_expires_at_ms > now_ms
            ):
                return ResumeClaim(
                    outcome=ResumeOutcome.ALREADY_RESUMING,
                    record=record,
                )
            if now_ms >= record.approval_expires_at_ms:
                changed = connection.execute(
                    """
                    UPDATE durable_approvals
                    SET status = 'EXPIRED', version = version + 1,
                        owner_token_sha256 = NULL, lease_expires_at_ms = NULL,
                        failure_code = 'approval_expired'
                    WHERE approval_id = ?
                      AND (client_handle_id = ?
                           OR (client_handle_id IS NULL AND token_sha256 = ?))
                      AND version = ? AND status IN ('PENDING','FAILED_RECOVERABLE')
                    """,
                    (
                        approval_id,
                        approval_handle_id,
                        _sha256(approval_handle_id),
                        record.version,
                    ),
                )
                if changed.rowcount == 0 and record.status == "RESUMING":
                    changed = connection.execute(
                        """
                        UPDATE durable_approvals
                        SET status = 'EXPIRED', version = version + 1,
                            owner_token_sha256 = NULL, lease_expires_at_ms = NULL,
                            failure_code = 'approval_expired'
                          WHERE approval_id = ?
                            AND (client_handle_id = ?
                                 OR (client_handle_id IS NULL AND token_sha256 = ?))
                          AND version = ? AND status = 'RESUMING'
                          AND lease_expires_at_ms <= ?
                        """,
                        (
                            approval_id,
                            approval_handle_id,
                            _sha256(approval_handle_id),
                            record.version,
                            now_ms,
                        ),
                    )
                if changed.rowcount == 0:
                    raise DurableStoreConflict("EXPIRY_CAS_CONFLICT")
                connection.commit()
                return ResumeClaim(
                    outcome=ResumeOutcome.EXPIRED,
                    record=self.by_resume_locator(approval_handle_id),
                )
            recover = record.status in {"RESUMING", "FAILED_RECOVERABLE"}
            where = "status = ?"
            parameters: list[Any] = [record.status]
            if record.status == "RESUMING":
                where += " AND lease_expires_at_ms <= ?"
                parameters.append(now_ms)
            changed = connection.execute(
                f"""
                UPDATE durable_approvals
                SET status = 'RESUMING', owner_token_sha256 = ?,
                    lease_expires_at_ms = ?, version = version + 1,
                    attempt = attempt + 1, resumed_by_sha256 = ?,
                    resumed_at_ms = ?, decision = ?, failure_code = NULL
                WHERE approval_id = ? AND version = ?
                  AND (client_handle_id = ?
                       OR (client_handle_id IS NULL AND token_sha256 = ?))
                  AND {where}
                """,
                (
                    owner_sha256,
                    now_ms + lease_ms,
                    _sha256(resumed_by),
                    now_ms,
                    decision,
                    approval_id,
                    record.version,
                    approval_handle_id,
                    _sha256(approval_handle_id),
                    *parameters,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("CAS_CONFLICT")
            connection.commit()
        return ResumeClaim(
            outcome=ResumeOutcome.RECOVERED if recover else ResumeOutcome.ACQUIRED,
            record=self.by_resume_locator(approval_handle_id),
            owner_token=owner_token,
        )

    def finalize_approved(
        self,
        *,
        approval_id: str,
        owner_token: str,
        version: int,
        now_ms: float,
        policy_input: ToolPolicyInput,
        arguments: AccessRequestDraftArguments,
        result_factory: Callable[[AccessRequestDraft], Mapping[str, Any]],
        completion_factory: Callable[[Mapping[str, Any]], CompletionEnvelope],
        crash_point: IntegrityCrashPoint | None = None,
    ) -> tuple[AccessRequestDraft, dict[str, Any]]:
        crash_point = _normalize_crash_point(crash_point)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, approval_id, owner_token, version, now_ms=now_ms)
            if crash_point == "before_effect_commit":
                raise InjectedIntegrityCrash("injected crash before effect commit")
            draft = create_access_request_draft_in_transaction(
                connection,
                policy_input,
                arguments,
            )
            if crash_point == "after_effect_before_completion":
                raise InjectedIntegrityCrash("injected crash after effect before completion")
            result = dict(result_factory(draft))
            envelope = completion_factory(result)
            self._insert_completion(connection, approval_id, envelope)
            if crash_point == "after_completion_before_approval":
                raise InjectedIntegrityCrash("injected crash after completion before approval")
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET status = 'COMPLETED', result_json = ?,
                    owner_token_sha256 = NULL, lease_expires_at_ms = NULL,
                    failure_code = NULL
                WHERE approval_id = ? AND status = 'RESUMING'
                  AND owner_token_sha256 = ? AND version = ?
                """,
                (
                    _canonical_json(result),
                    approval_id,
                    _sha256(owner_token),
                    version,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("FENCING_CONFLICT")
            if crash_point == "after_approval_before_commit":
                raise InjectedIntegrityCrash(
                    "injected crash after approval before transaction commit"
                )
            connection.commit()
        if crash_point == "after_commit_before_response":
            raise InjectedIntegrityCrash("injected crash after commit before response")
        return draft, result

    def finalize_rejected(
        self,
        *,
        approval_id: str,
        owner_token: str,
        version: int,
        now_ms: float,
        result: Mapping[str, Any],
        completion: CompletionEnvelope,
    ) -> dict[str, Any]:
        result_dict = dict(result)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_fence(connection, approval_id, owner_token, version, now_ms=now_ms)
            self._insert_completion(connection, approval_id, completion)
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET status = 'REJECTED', result_json = ?,
                    owner_token_sha256 = NULL, lease_expires_at_ms = NULL,
                    failure_code = NULL
                WHERE approval_id = ? AND status = 'RESUMING'
                  AND owner_token_sha256 = ? AND version = ?
                """,
                (
                    _canonical_json(result_dict),
                    approval_id,
                    _sha256(owner_token),
                    version,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("FENCING_CONFLICT")
            connection.commit()
        return result_dict

    def mark_failed_recoverable(
        self,
        *,
        approval_id: str,
        owner_token: str,
        version: int,
        now_ms: float,
        failure_code: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE durable_approvals
                SET status = 'FAILED_RECOVERABLE', owner_token_sha256 = NULL,
                    lease_expires_at_ms = NULL, failure_code = ?
                WHERE approval_id = ? AND status = 'RESUMING'
                  AND owner_token_sha256 = ? AND version = ?
                  AND lease_expires_at_ms > ?
                """,
                (
                    failure_code[:100],
                    approval_id,
                    _sha256(owner_token),
                    version,
                    now_ms,
                ),
            )
            if changed.rowcount != 1:
                raise DurableStoreConflict("FENCING_CONFLICT")
            connection.commit()

    def completion(self, approval_id: str) -> CompletionEnvelope | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT envelope_json FROM durable_completion_outbox WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return (
            CompletionEnvelope.model_validate_json(row["envelope_json"])
            if row is not None
            else None
        )

    def mark_completion_delivered(self, approval_id: str, *, delivered_at_ms: float) -> None:
        key = _completion_key(approval_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO durable_completion_deliveries
                    (completion_key, delivered_at_ms)
                VALUES (?, ?)
                """,
                (key, delivered_at_ms),
            )

    def completion_count(self) -> int:
        return self._count("durable_completion_outbox")

    def completion_delivery_count(self) -> int:
        return self._count("durable_completion_deliveries")

    def committed_count(self) -> int:
        return self._count("side_effect_commands")

    def draft_count(self) -> int:
        return self._count("access_request_drafts")

    def _count(self, table: str) -> int:
        allowed = {
            "durable_approvals",
            "durable_completion_outbox",
            "durable_completion_deliveries",
            "side_effect_commands",
            "access_request_drafts",
        }
        if table not in allowed:
            raise ValueError("count table is not allowed")
        with self._connect() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])

    @staticmethod
    def _assert_fence(
        connection: sqlite3.Connection,
        approval_id: str,
        owner_token: str,
        version: int,
        *,
        now_ms: float,
    ) -> None:
        row = connection.execute(
            """
            SELECT 1 FROM durable_approvals
            WHERE approval_id = ? AND status = 'RESUMING'
              AND owner_token_sha256 = ? AND version = ?
              AND lease_expires_at_ms > ?
            """,
            (approval_id, _sha256(owner_token), version, now_ms),
        ).fetchone()
        if row is None:
            raise DurableStoreConflict("FENCING_CONFLICT")

    @staticmethod
    def _insert_completion(
        connection: sqlite3.Connection,
        approval_id: str,
        completion: CompletionEnvelope,
    ) -> None:
        serialized = completion.model_dump_json()
        key = _completion_key(approval_id)
        connection.execute(
            """
            INSERT OR IGNORE INTO durable_completion_outbox
                (completion_key, approval_id, envelope_json)
            VALUES (?, ?, ?)
            """,
            (key, approval_id, serialized),
        )
        existing = connection.execute(
            "SELECT envelope_json FROM durable_completion_outbox WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if existing is None or existing["envelope_json"] != serialized:
            raise DurableStoreConflict("COMPLETION_IDEMPOTENCY_CONFLICT")


def _record(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(**dict(row))


def _terminal_outcome(status: ApprovalStatus) -> ResumeOutcome | None:
    return {
        "COMPLETED": ResumeOutcome.ALREADY_COMPLETED,
        "REJECTED": ResumeOutcome.REJECTED,
        "EXPIRED": ResumeOutcome.EXPIRED,
    }.get(status)


def _normalize_crash_point(
    crash_point: IntegrityCrashPoint | None,
) -> IntegrityCrashPoint | None:
    if crash_point == "before_commit":
        return "before_effect_commit"
    if crash_point == "after_commit":
        return "after_commit_before_response"
    return crash_point


def _completion_key(approval_id: str) -> str:
    return _sha256(f"{approval_id}:completion")


def _stable_thread_id(generation_scope_sha256: str, generation: int, approval_id: str) -> str:
    digest = _sha256(f"{generation_scope_sha256}:{generation}:{approval_id}")
    return f"durable-{generation}-{digest[:40]}"


def _generation_session_id(base_session_id: str, generation: int, approval_id: str) -> str:
    digest = _sha256(f"{base_session_id}:{generation}:{approval_id}")
    return f"approval-{generation}-{digest[:32]}"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


__all__ = [
    "ApprovalRecord",
    "ApprovalStatus",
    "CompletionEnvelope",
    "DurableStoreConflict",
    "InjectedIntegrityCrash",
    "IntegrityCrashPoint",
    "ResumeClaim",
    "ResumeOutcome",
    "StartClaim",
    "StartCrashPoint",
    "StartOutcome",
    "StartStatus",
    "SQLiteDurableWorkflowStore",
]
