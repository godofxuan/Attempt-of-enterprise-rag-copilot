import sqlite3

from app.config import get_settings


def init_db() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        helpful INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def save_feedback(question: str, answer: str, helpful: bool) -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO feedback (question, answer, helpful) VALUES (?, ?, ?)",
        (question, answer, int(helpful)),
    )

    conn.commit()
    conn.close()