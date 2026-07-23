from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from typing import Any, Literal

from app.config import get_settings


ContentDigest = Callable[[Literal["question", "answer"], str], str]

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HMAC_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_PSEUDONYM = "0" * 64
_LEGACY_CONTENT_DIGEST = "0" * 64
_VACUUM_MARKER = "feedback_vacuum_required"
_FINAL_COLUMNS = {
    "id",
    "request_id",
    "target_request_id",
    "actor_hmac_sha256",
    "question_hmac_sha256",
    "answer_hmac_sha256",
    "helpful",
    "binding_version",
    "legacy_feedback_id",
    "created_at",
}


def init_db(
    settings: Any | None = None,
    *,
    content_digest: ContentDigest | None = None,
) -> None:
    configured = settings or get_settings()
    database_path = Path(configured.sqlite_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(_connect(configured)) as connection:
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _create_metadata_table(connection)
            changed = _ensure_final_feedback_table(connection)
            changed = (
                _migrate_legacy_plaintext_feedback(connection, content_digest)
                or changed
            )
            _create_feedback_indexes(connection)
            if changed:
                connection.execute(
                    "INSERT INTO app_metadata(key, value) VALUES (?, '1') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (_VACUUM_MARKER,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        vacuum_required = _metadata_value(connection, _VACUUM_MARKER) == "1"

    if vacuum_required:
        _vacuum_database(configured)
        with closing(_connect(configured)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "DELETE FROM app_metadata WHERE key = ?",
                    (_VACUUM_MARKER,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def save_feedback(question: str, answer: str, helpful: bool) -> None:
    raise RuntimeError("trusted identity is required to save feedback")


def save_feedback_metadata(
    *,
    question_hmac_sha256: str,
    answer_hmac_sha256: str,
    helpful: bool,
    request_id: str,
    target_request_id: str,
    actor_pseudonym: str,
    settings: Any | None = None,
) -> None:
    _validate_request_id(request_id)
    _validate_request_id(target_request_id)
    _validate_digest(actor_pseudonym, "actor pseudonym")
    _validate_digest(question_hmac_sha256, "question HMAC")
    _validate_digest(answer_hmac_sha256, "answer HMAC")
    if not isinstance(helpful, bool):
        raise ValueError("feedback value must be boolean")
    configured = settings or get_settings()
    with closing(_connect(configured)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "INSERT INTO feedback_events "
                "(request_id, target_request_id, actor_hmac_sha256, "
                "question_hmac_sha256, answer_hmac_sha256, helpful, "
                "binding_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT("
                "actor_hmac_sha256, target_request_id, "
                "question_hmac_sha256, answer_hmac_sha256"
                ") WHERE binding_version = 'feedback-receipt-v1' "
                "DO UPDATE SET "
                "request_id = excluded.request_id, "
                "helpful = excluded.helpful, "
                "binding_version = excluded.binding_version, "
                "created_at = CURRENT_TIMESTAMP",
                (
                    request_id,
                    target_request_id,
                    actor_pseudonym,
                    question_hmac_sha256,
                    answer_hmac_sha256,
                    int(helpful),
                    "feedback-receipt-v1",
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def check_db(settings: Any | None = None) -> bool:
    configured = settings or get_settings()
    try:
        with closing(_connect_readonly(configured)) as connection:
            if connection.execute("SELECT 1").fetchone() != (1,):
                return False
            if not _table_exists(connection, "feedback_events"):
                return False
            if _feedback_columns(connection, "feedback_events") != _FINAL_COLUMNS:
                return False
            if _table_exists(connection, "feedback"):
                return False
            return _metadata_value(connection, _VACUUM_MARKER) is None
    except (OSError, ValueError, sqlite3.Error):
        return False


def _connect(settings: Any) -> sqlite3.Connection:
    connection = sqlite3.connect(
        settings.sqlite_path,
        timeout=float(settings.sqlite_timeout_seconds),
    )
    _configure_connection(connection, settings)
    return connection


def _connect_readonly(settings: Any) -> sqlite3.Connection:
    database_uri = (
        Path(settings.sqlite_path).absolute().as_uri() + "?mode=ro"
    )
    connection = sqlite3.connect(
        database_uri,
        timeout=float(settings.sqlite_timeout_seconds),
        uri=True,
    )
    _configure_connection(connection, settings)
    return connection


def _configure_connection(
    connection: sqlite3.Connection,
    settings: Any,
) -> None:
    connection.execute(
        f"PRAGMA busy_timeout = {max(1, int(float(settings.sqlite_timeout_seconds) * 1000))}"
    )
    connection.execute("PRAGMA foreign_keys = ON")


def _create_metadata_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS app_metadata ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _create_final_feedback_table(
    connection: sqlite3.Connection,
    *,
    name: str = "feedback_events",
) -> None:
    if not re.fullmatch(r"[a-z_]+", name):
        raise ValueError("feedback table name is invalid")
    connection.execute(
        f"CREATE TABLE {name} ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "request_id TEXT NOT NULL, "
        "target_request_id TEXT NOT NULL, "
        "actor_hmac_sha256 TEXT NOT NULL, "
        "question_hmac_sha256 TEXT NOT NULL, "
        "answer_hmac_sha256 TEXT NOT NULL, "
        "helpful INTEGER NOT NULL CHECK(helpful IN (0, 1)), "
        "binding_version TEXT NOT NULL, "
        "legacy_feedback_id INTEGER, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )


def _ensure_final_feedback_table(connection: sqlite3.Connection) -> bool:
    if not _table_exists(connection, "feedback_events"):
        _create_final_feedback_table(connection)
        return False
    columns = _feedback_columns(connection, "feedback_events")
    if columns == _FINAL_COLUMNS:
        return False

    legacy_name = "feedback_events_legacy_migration"
    if _table_exists(connection, legacy_name):
        raise RuntimeError("feedback migration staging table already exists")
    connection.execute(
        f"ALTER TABLE feedback_events RENAME TO {legacy_name}"
    )
    _create_final_feedback_table(connection)
    legacy_columns = _feedback_columns(connection, legacy_name)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        f"SELECT *, typeof(helpful) AS helpful_storage_type "
        f"FROM {legacy_name} ORDER BY id"
    ).fetchall()
    connection.row_factory = None
    for ordinal, row in enumerate(rows, start=1):
        old = dict(row)
        helpful = _strict_legacy_helpful(
            old.get("helpful"),
            old.get("helpful_storage_type"),
        )
        row_id = old.get("id")
        if not isinstance(row_id, int) or row_id < 1:
            row_id = ordinal
        request_id = _safe_legacy_request_id(
            old.get("request_id"),
            fallback=f"legacy-event-{row_id}",
        )
        target_request_id = _safe_legacy_request_id(
            old.get("target_request_id"),
            fallback="legacy-untracked",
        )
        actor = _safe_digest(old.get("actor_hmac_sha256"), _LEGACY_PSEUDONYM)
        has_keyed_content = {
            "question_hmac_sha256",
            "answer_hmac_sha256",
        }.issubset(legacy_columns)
        if has_keyed_content:
            question_digest = _safe_digest(
                old.get("question_hmac_sha256"),
                _LEGACY_CONTENT_DIGEST,
            )
            answer_digest = _safe_digest(
                old.get("answer_hmac_sha256"),
                _LEGACY_CONTENT_DIGEST,
            )
            binding_version = str(
                old.get("binding_version") or "legacy-keyed-content-v1"
            )
        else:
            question_digest = _LEGACY_CONTENT_DIGEST
            answer_digest = _LEGACY_CONTENT_DIGEST
            binding_version = "legacy-hash-unverifiable-v1"
        legacy_feedback_id = old.get("legacy_feedback_id")
        if not isinstance(legacy_feedback_id, int):
            legacy_feedback_id = None
        created_at = old.get("created_at")
        connection.execute(
            "INSERT INTO feedback_events "
            "(id, request_id, target_request_id, actor_hmac_sha256, "
            "question_hmac_sha256, answer_hmac_sha256, helpful, binding_version, "
            "legacy_feedback_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
            (
                row_id,
                request_id,
                target_request_id,
                actor,
                question_digest,
                answer_digest,
                helpful,
                binding_version[:100],
                legacy_feedback_id,
                created_at,
            ),
        )
    connection.execute(f"DROP TABLE {legacy_name}")
    return True


def _migrate_legacy_plaintext_feedback(
    connection: sqlite3.Connection,
    content_digest: ContentDigest | None,
) -> bool:
    if not _table_exists(connection, "feedback"):
        return False
    if content_digest is None:
        raise RuntimeError("legacy feedback migration requires a content digest provider")
    required = {"id", "question", "answer", "helpful", "created_at"}
    if not required.issubset(_feedback_columns(connection, "feedback")):
        raise RuntimeError("legacy feedback table schema is unsupported")

    rows = connection.execute(
        "SELECT id, question, answer, helpful, typeof(helpful), created_at "
        "FROM feedback ORDER BY id"
    ).fetchall()
    for (
        legacy_id,
        question,
        answer,
        helpful_value,
        helpful_storage_type,
        created_at,
    ) in rows:
        helpful = _strict_legacy_helpful(
            helpful_value,
            helpful_storage_type,
        )
        request_id = f"legacy-feedback-{legacy_id}"
        question_digest = content_digest("question", str(question))
        answer_digest = content_digest("answer", str(answer))
        _validate_digest(question_digest, "question HMAC")
        _validate_digest(answer_digest, "answer HMAC")
        connection.execute(
            "INSERT INTO feedback_events "
            "(request_id, target_request_id, actor_hmac_sha256, "
            "question_hmac_sha256, answer_hmac_sha256, helpful, binding_version, "
            "legacy_feedback_id, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP) "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM feedback_events WHERE legacy_feedback_id = ?)",
            (
                request_id,
                request_id,
                _LEGACY_PSEUDONYM,
                question_digest,
                answer_digest,
                helpful,
                "legacy-plaintext-migrated-v1",
                int(legacy_id),
                created_at,
                int(legacy_id),
            ),
        )
    connection.execute("DROP TABLE feedback")
    return True


def _strict_legacy_helpful(value: Any, storage_type: Any) -> int:
    if storage_type != "integer" or type(value) is not int or value not in (0, 1):
        raise RuntimeError(
            "legacy feedback helpful must be stored as SQLite INTEGER 0 or 1"
        )
    return value


def _create_feedback_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DROP INDEX IF EXISTS idx_feedback_actor_target_current"
    )
    connection.execute(
        "DELETE FROM feedback_events "
        "WHERE binding_version = 'feedback-receipt-v1' "
        "AND id NOT IN ("
        "SELECT MAX(id) FROM feedback_events "
        "WHERE binding_version = 'feedback-receipt-v1' "
        "GROUP BY actor_hmac_sha256, target_request_id, "
        "question_hmac_sha256, answer_hmac_sha256)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_target_request "
        "ON feedback_events(target_request_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_actor "
        "ON feedback_events(actor_hmac_sha256)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_feedback_actor_target_content_current "
        "ON feedback_events("
        "actor_hmac_sha256, target_request_id, "
        "question_hmac_sha256, answer_hmac_sha256"
        ") "
        "WHERE binding_version = 'feedback-receipt-v1'"
    )


def _vacuum_database(settings: Any) -> None:
    with closing(_connect(settings)) as connection:
        connection.execute("VACUUM")
        checkpoint = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        _require_complete_wal_checkpoint(checkpoint)


def _require_complete_wal_checkpoint(
    checkpoint: tuple[Any, ...] | None,
) -> None:
    if checkpoint is None or len(checkpoint) != 3:
        raise sqlite3.OperationalError("WAL checkpoint status is unavailable")
    busy, log_frames, checkpointed_frames = checkpoint
    if (
        not all(type(value) is int for value in checkpoint)
        or busy != 0
        or (
            log_frames >= 0
            and checkpointed_frames >= 0
            and checkpointed_frames < log_frames
        )
    ):
        raise sqlite3.OperationalError("WAL checkpoint did not complete")


def _metadata_value(connection: sqlite3.Connection, key: str) -> str | None:
    if not _table_exists(connection, "app_metadata"):
        return None
    row = connection.execute(
        "SELECT value FROM app_metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return str(row[0]) if row is not None else None


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def _feedback_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not re.fullmatch(r"[a-z_]+", table):
        raise ValueError("feedback table name is invalid")
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _safe_legacy_request_id(value: Any, *, fallback: str) -> str:
    return value if isinstance(value, str) and _REQUEST_ID_PATTERN.fullmatch(value) else fallback


def _safe_digest(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and _HMAC_SHA256_PATTERN.fullmatch(value) else fallback


def _validate_request_id(value: str) -> None:
    if not isinstance(value, str) or not _REQUEST_ID_PATTERN.fullmatch(value):
        raise ValueError("request ID is invalid")


def _validate_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not _HMAC_SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} is invalid")


__all__ = [
    "ContentDigest",
    "check_db",
    "init_db",
    "save_feedback",
    "save_feedback_metadata",
]
