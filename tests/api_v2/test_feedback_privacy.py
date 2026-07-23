from __future__ import annotations

import hashlib
import hmac
import sqlite3
from types import SimpleNamespace

import pytest

import app.db as db


_DIGEST_KEY = b"feedback-content-test-key-value"


def configure_temp_db(tmp_path):
    sqlite_path = tmp_path / "nested" / "feedback.db"
    settings = SimpleNamespace(
        sqlite_path=sqlite_path,
        sqlite_timeout_seconds=1.0,
    )
    return settings, sqlite_path


def content_digest(kind: str, value: str) -> str:
    return hmac.new(
        _DIGEST_KEY,
        f"{kind}\x00{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_legacy_feedback_database(
    sqlite_path,
    *,
    table_kind: str,
    helpful_sql: str,
) -> str:
    sqlite_path.parent.mkdir(parents=True)
    table_name = "feedback" if table_kind == "plaintext" else "feedback_events"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app_metadata VALUES ('feedback_vacuum_required', '1')"
        )
        if table_kind == "plaintext":
            connection.execute(
                "CREATE TABLE feedback ("
                "id INTEGER PRIMARY KEY, question TEXT, answer TEXT, helpful, "
                "created_at TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO feedback VALUES "
                f"(1, 'legacy-question', 'legacy-answer', {helpful_sql}, NULL)"
            )
        else:
            connection.execute(
                "CREATE TABLE feedback_events ("
                "id INTEGER PRIMARY KEY, request_id TEXT, "
                "question_sha256 TEXT, answer_sha256 TEXT, helpful, "
                "created_at TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO feedback_events VALUES "
                f"(1, 'legacy-request', 'question-hash', 'answer-hash', "
                f"{helpful_sql}, NULL)"
            )
    return table_name


def test_feedback_persists_keyed_digests_and_metadata_without_plaintext(
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    question = "PROJECT NIGHTFALL password=test-question-secret"
    answer = "D:/vault/private answer-secret"
    question_hmac = content_digest("question", question)
    answer_hmac = content_digest("answer", answer)

    db.init_db(settings, content_digest=content_digest)
    db.save_feedback_metadata(
        question_hmac_sha256=question_hmac,
        answer_hmac_sha256=answer_hmac,
        helpful=True,
        request_id="req-123",
        target_request_id="req-answer-456",
        actor_pseudonym="a" * 64,
        settings=settings,
    )

    with sqlite3.connect(sqlite_path) as connection:
        row = connection.execute(
            "SELECT request_id, target_request_id, actor_hmac_sha256, "
            "question_hmac_sha256, answer_hmac_sha256, helpful, binding_version "
            "FROM feedback_events"
        ).fetchone()
        columns = {
            str(item[1])
            for item in connection.execute("PRAGMA table_info(feedback_events)")
        }

    assert row == (
        "req-123",
        "req-answer-456",
        "a" * 64,
        question_hmac,
        answer_hmac,
        1,
        "feedback-receipt-v1",
    )
    assert "question_sha256" not in columns
    assert "answer_sha256" not in columns
    database_text = sqlite_path.read_bytes().decode("utf-8", errors="ignore")
    for secret in ["NIGHTFALL", "question-secret", "vault", "answer-secret"]:
        assert secret not in database_text
    assert db.check_db(settings) is True


def test_feedback_rejects_invalid_metadata_before_write(tmp_path) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    db.init_db(settings, content_digest=content_digest)

    with pytest.raises(ValueError):
        db.save_feedback_metadata(
            question_hmac_sha256="not-a-digest",
            answer_hmac_sha256="b" * 64,
            helpful=False,
            request_id="",
            target_request_id="../answer",
            actor_pseudonym="not-a-pseudonym",
            settings=settings,
        )

    with sqlite3.connect(sqlite_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM feedback_events").fetchone()[0]
    assert count == 0


def test_init_db_migrates_legacy_plaintext_with_keyed_digest_and_vacuums(
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    sqlite_path.parent.mkdir(parents=True)
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "CREATE TABLE feedback ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, "
            "answer TEXT NOT NULL, helpful INTEGER NOT NULL, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO feedback (question, answer, helpful) VALUES (?, ?, ?)",
            ("legacy-question-secret", "legacy-answer-secret", 1),
        )

    db.init_db(settings, content_digest=content_digest)
    db.init_db(settings, content_digest=content_digest)

    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(
            "SELECT request_id, target_request_id, actor_hmac_sha256, "
            "question_hmac_sha256, answer_hmac_sha256, helpful, binding_version "
            "FROM feedback_events"
        ).fetchall()
        legacy_table = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'feedback'"
        ).fetchone()[0]
        marker = connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'feedback_vacuum_required'"
        ).fetchone()

    assert rows == [
        (
            "legacy-feedback-1",
            "legacy-feedback-1",
            "0" * 64,
            content_digest("question", "legacy-question-secret"),
            content_digest("answer", "legacy-answer-secret"),
            1,
            "legacy-plaintext-migrated-v1",
        )
    ]
    assert legacy_table == 0
    assert marker is None
    database_text = sqlite_path.read_bytes().decode("utf-8", errors="ignore")
    assert "legacy-question-secret" not in database_text
    assert "legacy-answer-secret" not in database_text


def test_init_db_rebuilds_old_sha256_table_without_preserving_enumerable_hashes(
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    sqlite_path.parent.mkdir(parents=True)
    old_question_hash = hashlib.sha256(b"q").hexdigest()
    old_answer_hash = hashlib.sha256(b"a").hexdigest()
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "CREATE TABLE feedback_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, "
            "question_sha256 TEXT NOT NULL, answer_sha256 TEXT NOT NULL, "
            "helpful INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO feedback_events "
            "(request_id, question_sha256, answer_sha256, helpful) "
            "VALUES ('req-old', ?, ?, 1)",
            (old_question_hash, old_answer_hash),
        )

    db.init_db(settings, content_digest=content_digest)

    with sqlite3.connect(sqlite_path) as connection:
        row = connection.execute(
            "SELECT request_id, target_request_id, actor_hmac_sha256, "
            "question_hmac_sha256, answer_hmac_sha256, binding_version "
            "FROM feedback_events"
        ).fetchone()
        columns = {
            str(item[1])
            for item in connection.execute("PRAGMA table_info(feedback_events)")
        }

    assert row == (
        "req-old",
        "legacy-untracked",
        "0" * 64,
        "0" * 64,
        "0" * 64,
        "legacy-hash-unverifiable-v1",
    )
    assert "question_sha256" not in columns
    assert "answer_sha256" not in columns
    database_bytes = sqlite_path.read_bytes()
    assert old_question_hash.encode("ascii") not in database_bytes
    assert old_answer_hash.encode("ascii") not in database_bytes


@pytest.mark.parametrize("table_kind", ["plaintext", "event"])
@pytest.mark.parametrize(
    ("helpful_sql", "storage_type", "stored_value"),
    [
        ("NULL", "null", None),
        ("0.5", "real", 0.5),
        ("'0'", "text", "0"),
        ("'false'", "text", "false"),
        ("X'00FF'", "blob", b"\x00\xff"),
        ("2", "integer", 2),
        ("-1", "integer", -1),
    ],
    ids=["null", "real", "text-zero", "text-false", "blob", "two", "negative"],
)
def test_invalid_legacy_helpful_fails_closed_and_migration_remains_retryable(
    tmp_path,
    table_kind,
    helpful_sql,
    storage_type,
    stored_value,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    source_table = create_legacy_feedback_database(
        sqlite_path,
        table_kind=table_kind,
        helpful_sql=helpful_sql,
    )

    with pytest.raises(RuntimeError, match="legacy feedback helpful"):
        db.init_db(settings, content_digest=content_digest)

    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute(
            f"SELECT typeof(helpful), helpful FROM {source_table}"
        ).fetchone() == (storage_type, stored_value)
        assert connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'feedback_vacuum_required'"
        ).fetchone() == ("1",)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = ?",
            (source_table,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'feedback_events_legacy_migration'"
        ).fetchone() == (0,)
        if table_kind == "plaintext":
            assert connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'feedback_events'"
            ).fetchone() == (0,)
        else:
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(feedback_events)")
            }
            assert "question_sha256" in columns
            assert "actor_hmac_sha256" not in columns
        connection.execute(f"UPDATE {source_table} SET helpful = 0")

    db.init_db(settings, content_digest=content_digest)

    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute(
            "SELECT typeof(helpful), helpful FROM feedback_events"
        ).fetchone() == ("integer", 0)
        assert connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'feedback_vacuum_required'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'feedback'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'feedback_events_legacy_migration'"
        ).fetchone() == (0,)


@pytest.mark.parametrize("table_kind", ["plaintext", "event"])
@pytest.mark.parametrize("helpful", [0, 1])
def test_strict_integer_legacy_helpful_values_still_migrate(
    tmp_path,
    table_kind,
    helpful,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    create_legacy_feedback_database(
        sqlite_path,
        table_kind=table_kind,
        helpful_sql=str(helpful),
    )

    db.init_db(settings, content_digest=content_digest)

    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute(
            "SELECT typeof(helpful), helpful FROM feedback_events"
        ).fetchone() == ("integer", helpful)


def test_failed_legacy_helpful_migration_closes_connection(
    monkeypatch,
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    create_legacy_feedback_database(
        sqlite_path,
        table_kind="plaintext",
        helpful_sql="'false'",
    )
    opened: list[TrackingConnection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(
            *args,
            **kwargs,
            factory=TrackingConnection,
        )
        opened.append(connection)
        return connection

    monkeypatch.setattr(db.sqlite3, "connect", tracking_connect)

    with pytest.raises(RuntimeError, match="legacy feedback helpful"):
        db.init_db(settings, content_digest=content_digest)

    assert len(opened) == 1
    assert opened[0].was_closed is True


def test_failed_vacuum_leaves_durable_marker_and_next_init_retries(
    monkeypatch,
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    sqlite_path.parent.mkdir(parents=True)
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "CREATE TABLE feedback ("
            "id INTEGER PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, "
            "helpful INTEGER NOT NULL, created_at TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO feedback VALUES (1, 'secret-q', 'secret-a', 1, NULL)"
        )

    real_vacuum = db._vacuum_database
    monkeypatch.setattr(
        db,
        "_vacuum_database",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("full")),
    )
    with pytest.raises(sqlite3.OperationalError, match="full"):
        db.init_db(settings, content_digest=content_digest)

    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'feedback_vacuum_required'"
        ).fetchone() == ("1",)
        assert connection.execute(
            "SELECT COUNT(*) FROM feedback_events"
        ).fetchone() == (1,)

    monkeypatch.setattr(db, "_vacuum_database", real_vacuum)
    db.init_db(settings, content_digest=content_digest)
    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'feedback_vacuum_required'"
        ).fetchone() is None
    assert b"secret-q" not in sqlite_path.read_bytes()
    assert b"secret-a" not in sqlite_path.read_bytes()


def test_plaintext_migration_requires_keyed_digest_provider(tmp_path) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    sqlite_path.parent.mkdir(parents=True)
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "CREATE TABLE feedback ("
            "id INTEGER PRIMARY KEY, question TEXT, answer TEXT, helpful INTEGER, "
            "created_at TIMESTAMP)"
        )

    with pytest.raises(RuntimeError, match="content digest provider"):
        db.init_db(settings)

    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'feedback'"
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "checkpoint",
    [
        None,
        (1, 5, 2),
        (0, 5, 2),
        ("0", 0, 0),
        (False, 0, 0),
        (0, 0),
    ],
)
def test_incomplete_wal_checkpoint_is_never_treated_as_erased(
    checkpoint,
) -> None:
    with pytest.raises(sqlite3.OperationalError):
        db._require_complete_wal_checkpoint(checkpoint)


@pytest.mark.parametrize("checkpoint", [(0, 0, 0), (0, -1, -1), (0, 3, 3)])
def test_complete_or_non_wal_checkpoint_is_accepted(checkpoint) -> None:
    db._require_complete_wal_checkpoint(checkpoint)


def test_feedback_replay_is_an_idempotent_latest_rating_update(
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    db.init_db(settings, content_digest=content_digest)

    db.save_feedback_metadata(
        question_hmac_sha256="1" * 64,
        answer_hmac_sha256="2" * 64,
        helpful=True,
        request_id="feedback-first",
        target_request_id="answer-one",
        actor_pseudonym="3" * 64,
        settings=settings,
    )
    db.save_feedback_metadata(
        question_hmac_sha256="1" * 64,
        answer_hmac_sha256="2" * 64,
        helpful=False,
        request_id="feedback-second",
        target_request_id="answer-one",
        actor_pseudonym="3" * 64,
        settings=settings,
    )

    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(
            "SELECT request_id, question_hmac_sha256, answer_hmac_sha256, "
            "helpful FROM feedback_events"
        ).fetchall()

    assert rows == [("feedback-second", "1" * 64, "2" * 64, 0)]


def test_reused_request_id_does_not_overwrite_feedback_for_different_answers(
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    db.init_db(settings, content_digest=content_digest)

    for ordinal, question_digest, answer_digest in (
        (1, "1" * 64, "2" * 64),
        (2, "4" * 64, "5" * 64),
    ):
        db.save_feedback_metadata(
            question_hmac_sha256=question_digest,
            answer_hmac_sha256=answer_digest,
            helpful=ordinal == 1,
            request_id=f"feedback-{ordinal}",
            target_request_id="caller-reused-request-id",
            actor_pseudonym="3" * 64,
            settings=settings,
        )

    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(
            "SELECT request_id, question_hmac_sha256, answer_hmac_sha256, "
            "helpful FROM feedback_events ORDER BY id"
        ).fetchall()

    assert rows == [
        ("feedback-1", "1" * 64, "2" * 64, 1),
        ("feedback-2", "4" * 64, "5" * 64, 0),
    ]


def test_check_db_does_not_create_a_missing_database(tmp_path) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    sqlite_path.parent.mkdir(parents=True)

    assert sqlite_path.exists() is False
    assert db.check_db(settings) is False
    assert sqlite_path.exists() is False
    assert sqlite_path.parent.exists() is True


def test_database_operations_explicitly_close_connections(
    monkeypatch,
    tmp_path,
) -> None:
    settings, _ = configure_temp_db(tmp_path)
    db.init_db(settings, content_digest=content_digest)
    opened: list[TrackingConnection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(
            *args,
            **kwargs,
            factory=TrackingConnection,
        )
        opened.append(connection)
        return connection

    monkeypatch.setattr(db.sqlite3, "connect", tracking_connect)

    assert db.check_db(settings) is True
    db.save_feedback_metadata(
        question_hmac_sha256="1" * 64,
        answer_hmac_sha256="2" * 64,
        helpful=True,
        request_id="feedback-close",
        target_request_id="answer-close",
        actor_pseudonym="3" * 64,
        settings=settings,
    )

    assert len(opened) == 2
    assert all(connection.was_closed for connection in opened)


def test_busy_wal_keeps_erasure_marker_until_every_database_file_is_clean(
    tmp_path,
) -> None:
    settings, sqlite_path = configure_temp_db(tmp_path)
    sqlite_path.parent.mkdir(parents=True)
    secret_question = b"WAL-QUESTION-SECRET"
    secret_answer = b"WAL-ANSWER-SECRET"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "CREATE TABLE feedback ("
            "id INTEGER PRIMARY KEY, question TEXT, answer TEXT, helpful INTEGER, "
            "created_at TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO feedback VALUES (1, ?, ?, 1, NULL)",
            (secret_question.decode(), secret_answer.decode()),
        )

    reader = sqlite3.connect(sqlite_path)
    reader.execute("BEGIN")
    assert reader.execute("SELECT question FROM feedback").fetchone() == (
        secret_question.decode(),
    )
    try:
        with pytest.raises(
            sqlite3.OperationalError,
            match="checkpoint did not complete",
        ):
            db.init_db(settings, content_digest=content_digest)

        with sqlite3.connect(sqlite_path) as connection:
            assert connection.execute(
                "SELECT value FROM app_metadata "
                "WHERE key = 'feedback_vacuum_required'"
            ).fetchone() == ("1",)
            assert db.check_db(settings) is False
    finally:
        reader.close()

    db.init_db(settings, content_digest=content_digest)

    database_files = list(sqlite_path.parent.glob(f"{sqlite_path.name}*"))
    combined = b"".join(path.read_bytes() for path in database_files)
    assert secret_question not in combined
    assert secret_answer not in combined
    assert db.check_db(settings) is True


class TrackingConnection(sqlite3.Connection):
    was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()
