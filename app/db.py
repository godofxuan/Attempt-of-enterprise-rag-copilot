import hashlib
import re
import sqlite3

from app.config import get_settings


def init_db() -> None:
    settings = get_settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(
        settings.sqlite_path,
        timeout=settings.sqlite_timeout_seconds,
    ) as connection:
        connection.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            helpful INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        connection.execute("""
        CREATE TABLE IF NOT EXISTS feedback_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            question_sha256 TEXT NOT NULL,
            answer_sha256 TEXT NOT NULL,
            helpful INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)


def save_feedback(question: str, answer: str, helpful: bool) -> None:
    from app.runtime.request_context import current_request_id

    save_feedback_metadata(
        question=question,
        answer=answer,
        helpful=helpful,
        request_id=current_request_id() or "legacy-untracked",
    )


def save_feedback_metadata(
    *,
    question: str,
    answer: str,
    helpful: bool,
    request_id: str,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_id):
        raise ValueError("request ID is invalid")
    settings = get_settings()
    with sqlite3.connect(
        settings.sqlite_path,
        timeout=settings.sqlite_timeout_seconds,
    ) as connection:
        connection.execute(
            "INSERT INTO feedback_events "
            "(request_id, question_sha256, answer_sha256, helpful) "
            "VALUES (?, ?, ?, ?)",
            (
                request_id,
                hashlib.sha256(question.encode("utf-8")).hexdigest(),
                hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                int(helpful),
            ),
        )


def check_db() -> bool:
    settings = get_settings()
    with sqlite3.connect(
        settings.sqlite_path,
        timeout=settings.sqlite_timeout_seconds,
    ) as connection:
        return connection.execute("SELECT 1").fetchone() == (1,)
