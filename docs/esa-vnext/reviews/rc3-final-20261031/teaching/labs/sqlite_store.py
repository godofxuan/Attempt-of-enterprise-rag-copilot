"""Temporary teaching store: optimistic edits + idempotent commands.
Sequential stale clients model the conflict; this is not a concurrency stress test.
"""
import json
import sqlite3

class Conflict(Exception):
    pass

class DemoStore:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE task(id INTEGER PRIMARY KEY, revision INTEGER, value TEXT)")
        self.db.execute("INSERT INTO task VALUES(1,1,'initial')")
        self.db.execute("CREATE TABLE ticket(id INTEGER PRIMARY KEY, command TEXT UNIQUE, payload TEXT)")
        self.db.commit()

    def edit(self, value: str, expected_revision: int) -> int:
        with self.db:
            cursor = self.db.execute(
                "UPDATE task SET value=?,revision=revision+1 WHERE id=1 AND revision=?",
                (value, expected_revision),
            )
            if cursor.rowcount != 1:
                raise Conflict("stale revision")
            return self.db.execute("SELECT revision FROM task WHERE id=1").fetchone()[0]

    def submit(self, command: str, payload: dict) -> int:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.db:
            previous = self.db.execute("SELECT id,payload FROM ticket WHERE command=?", (command,)).fetchone()
            if previous:
                if previous[1] != body:
                    raise Conflict("same command, different request")
                return previous[0]
            return self.db.execute("INSERT INTO ticket(command,payload) VALUES(?,?)", (command, body)).lastrowid

    def close(self) -> None:
        self.db.close()

if __name__ == "__main__":
    s = DemoStore()
    try:
        print("new revision", s.edit("new purpose", 1))
        print("ticket", s.submit("command-1", {"purpose": "study"}))
        print("same ticket", s.submit("command-1", {"purpose": "study"}))
    finally:
        s.close()
