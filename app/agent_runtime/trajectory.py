from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


AgentEventType = Literal[
    "session.started",
    "user.message",
    "step.started",
    "model.requested",
    "model.responded",
    "tool.requested",
    "tool.completed",
    "tool.failed",
    "retrieval.completed",
    "evidence.admitted",
    "evidence.rejected",
    "claim.proposed",
    "claim.accepted",
    "claim.rejected",
    "citation.checked",
    "budget.updated",
    "human_review.requested",
    "human_review.completed",
    "terminal.reached",
    "session.completed",
]

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SECRET_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "session_handle",
    "access_token",
    "refresh_token",
)
_RAW_CONTENT_KEYS = {"raw_content", "context_text", "matched_text"}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/-]+=*"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)
_MAX_PAYLOAD_BYTES = 64 * 1024


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AgentEvent(_FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    event_type: AgentEventType
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = Field(default=None, max_length=128)
    tool_name: Literal["search", "find", "open"] | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    terminal_reason: str | None = Field(default=None, max_length=64)
    previous_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentEventDraft(_FrozenModel):
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    event_type: AgentEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = Field(default=None, max_length=128)
    tool_name: Literal["search", "find", "open"] | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    terminal_reason: str | None = Field(default=None, max_length=64)


class SQLiteTrajectoryStore:
    def __init__(self, path: Path, *, now=None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS agent_events (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence > 0),
                    event_id TEXT NOT NULL UNIQUE,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    previous_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE,
                    PRIMARY KEY (session_id, sequence)
                );
                CREATE TRIGGER IF NOT EXISTS agent_events_no_update
                BEFORE UPDATE ON agent_events
                BEGIN
                    SELECT RAISE(ABORT, 'agent trajectory is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS agent_events_no_delete
                BEFORE DELETE ON agent_events
                BEGIN
                    SELECT RAISE(ABORT, 'agent trajectory is append-only');
                END;
                """
            )

    def append(self, draft: AgentEventDraft) -> AgentEvent:
        if not isinstance(draft, AgentEventDraft):
            raise TypeError("trajectory append requires AgentEventDraft")
        _validate_identifier(draft.session_id, "session ID")
        _validate_identifier(draft.trace_id, "trace ID")
        payload = redact_trajectory_payload(draft.payload)
        serialized_payload = _canonical_json(payload)
        if len(serialized_payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("trajectory payload exceeds the 64 KiB limit")

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT sequence, trace_id, event_type, event_hash
                FROM agent_events WHERE session_id = ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (draft.session_id,),
            ).fetchone()
            if previous is None:
                if draft.event_type != "session.started":
                    raise ValueError("first trajectory event must be session.started")
                sequence = 1
                previous_hash = None
            else:
                if draft.event_type == "session.started":
                    raise ValueError("agent session already exists")
                if previous["event_type"] == "session.completed":
                    raise ValueError("completed agent session is immutable")
                if previous["trace_id"] != draft.trace_id:
                    raise ValueError("trace ID cannot change within a session")
                sequence = int(previous["sequence"]) + 1
                previous_hash = str(previous["event_hash"])

            timestamp = self._now()
            if timestamp.tzinfo is None:
                raise ValueError("trajectory timestamp must be timezone-aware")
            timestamp = timestamp.astimezone(timezone.utc)
            event_id = uuid4().hex
            values = {
                "schema_version": "1.0",
                "event_id": event_id,
                "session_id": draft.session_id,
                "trace_id": draft.trace_id,
                "sequence": sequence,
                "event_type": draft.event_type,
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "payload": payload,
                "step_id": draft.step_id,
                "tool_name": draft.tool_name,
                "latency_ms": draft.latency_ms,
                "token_usage": draft.token_usage,
                "cost_usd": draft.cost_usd,
                "error_code": draft.error_code,
                "terminal_reason": draft.terminal_reason,
                "previous_hash": previous_hash,
            }
            event_hash = hashlib.sha256(
                _canonical_json(values).encode("utf-8")
            ).hexdigest()
            event = AgentEvent(**values, event_hash=event_hash)
            connection.execute(
                """
                INSERT INTO agent_events (
                    session_id, sequence, event_id, trace_id, event_type,
                    timestamp, event_json, previous_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.session_id,
                    event.sequence,
                    event.event_id,
                    event.trace_id,
                    event.event_type,
                    event.timestamp.isoformat(),
                    event.model_dump_json(),
                    event.previous_hash,
                    event.event_hash,
                ),
            )
            connection.commit()
            return event

    def load(self, session_id: str) -> list[AgentEvent]:
        _validate_identifier(session_id, "session ID")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM agent_events
                WHERE session_id = ? ORDER BY sequence
                """,
                (session_id,),
            ).fetchall()
        return [AgentEvent.model_validate_json(row["event_json"]) for row in rows]

    def verify(self, session_id: str) -> bool:
        events = self.load(session_id)
        previous_hash = None
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                return False
            values = event.model_dump(mode="json", exclude={"event_hash"})
            expected_hash = hashlib.sha256(
                _canonical_json(values).encode("utf-8")
            ).hexdigest()
            if event.event_hash != expected_hash:
                return False
            previous_hash = event.event_hash
        return bool(events)


class TrajectoryRecorder:
    def __init__(
        self,
        store: SQLiteTrajectoryStore,
        *,
        session_id: str,
        trace_id: str,
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.trace_id = trace_id

    def record(self, event_type: AgentEventType, **kwargs) -> AgentEvent:
        return self.store.append(
            AgentEventDraft(
                session_id=self.session_id,
                trace_id=self.trace_id,
                event_type=event_type,
                **kwargs,
            )
        )


def redact_trajectory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("trajectory payload must be a dictionary")
    return _redact_value(payload, depth=0)


def _redact_value(value: Any, *, depth: int) -> Any:
    if depth > 16:
        return "[REDACTED_DEPTH]"
    if isinstance(value, dict):
        result = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if lowered in _RAW_CONTENT_KEYS or any(
                part in lowered for part in _SECRET_KEY_PARTS
            ):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            return "[REDACTED]"
        return value[:20_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _validate_identifier(value: str, label: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} contains unsafe characters")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "AgentEvent",
    "AgentEventDraft",
    "AgentEventType",
    "SQLiteTrajectoryStore",
    "TrajectoryRecorder",
    "redact_trajectory_payload",
]
