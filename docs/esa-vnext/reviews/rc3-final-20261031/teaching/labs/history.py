"""Detail lookup is independent from recent-list windows. Synthetic in-memory DB."""
import sqlite3

class History:
    def __init__(self, count: int = 55) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE answer(id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        self.db.executemany("INSERT INTO answer VALUES(?,?)", ((i, f"answer {i}") for i in range(1, count + 1)))
        self.db.commit()

    def detail(self, identifier: int):
        return self.db.execute("SELECT id,title FROM answer WHERE id=?", (identifier,)).fetchone()

    def page(self, *, before: int | None = None, limit: int = 20, search: str = ""):
        return self.db.execute(
            "SELECT id,title FROM answer WHERE (? IS NULL OR id<?) AND title LIKE ? ORDER BY id DESC LIMIT ?",
            (before, before, "%" + search + "%", limit),
        ).fetchall()

    def close(self):
        self.db.close()

if __name__ == "__main__":
    h = History()
    try:
        print("recent count:", len(h.page(limit=50)))
        print("old detail:", h.detail(1))
        cursor = None
        while rows := h.page(before=cursor):
            print("page ids:", [x[0] for x in rows])
            cursor = rows[-1][0]
    finally:
        h.close()
