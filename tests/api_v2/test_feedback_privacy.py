from __future__ import annotations

import hashlib
import sqlite3
from types import SimpleNamespace

import pytest

import app.db as db


def configure_temp_db(monkeypatch, tmp_path):
    sqlite_path = tmp_path / "nested" / "feedback.db"
    monkeypatch.setattr(
        db,
        "get_settings",
        lambda: SimpleNamespace(
            sqlite_path=sqlite_path,
            sqlite_timeout_seconds=1.0,
        ),
    )
    return sqlite_path


def test_feedback_persists_hashes_and_request_metadata_without_plaintext(
    monkeypatch,
    tmp_path,
) -> None:
    sqlite_path = configure_temp_db(monkeypatch, tmp_path)
    question = "PROJECT NIGHTFALL password=question-secret"
    answer = "D:/vault/private answer-secret"

    db.init_db()
    db.save_feedback_metadata(
        question=question,
        answer=answer,
        helpful=True,
        request_id="req-123",
    )

    with sqlite3.connect(sqlite_path) as connection:
        row = connection.execute(
            "SELECT request_id, question_sha256, answer_sha256, helpful "
            "FROM feedback_events"
        ).fetchone()
        old_rows = connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    assert row == (
        "req-123",
        hashlib.sha256(question.encode("utf-8")).hexdigest(),
        hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        1,
    )
    assert old_rows == 0
    database_text = sqlite_path.read_bytes().decode("utf-8", errors="ignore")
    for secret in ["NIGHTFALL", "question-secret", "vault", "answer-secret"]:
        assert secret not in database_text
    assert db.check_db() is True


def test_feedback_rejects_invalid_request_id_before_write(monkeypatch, tmp_path) -> None:
    sqlite_path = configure_temp_db(monkeypatch, tmp_path)
    db.init_db()

    with pytest.raises(ValueError, match="request ID"):
        db.save_feedback_metadata(
            question="q",
            answer="a",
            helpful=False,
            request_id="",
        )

    with sqlite3.connect(sqlite_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM feedback_events").fetchone()[0]
    assert count == 0
