"""One library instance with explicit responsibilities and lazy retrieval imports."""

import asyncio, sqlite3
from contextlib import contextmanager
from .catalog import CatalogOperations
from .jobs import JobsOperations
from .query import QueryOperations


class Library(CatalogOperations, JobsOperations, QueryOperations):
    def document_path(self, row):
        """Resolve immutable imports in this workspace, including moved 0.4 copies."""
        from pathlib import Path

        suffix = Path(row["path"]).suffix
        local = self.workspace.root / "documents" / row["kb_id"] / (row["id"] + suffix)
        if local.is_file():
            return local
        raise ValueError("IMPORTED_DOCUMENT_MISSING: restore the complete documents directory")

    def __init__(self, workspace):
        self.workspace = workspace
        self.running = set()
        self.closing = False
        self.lock = asyncio.Lock()
        self.snapshots = {}
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_bases(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS library_documents(id TEXT PRIMARY KEY,kb_id TEXT,name TEXT,
                    version INTEGER,sha256 TEXT,path TEXT,parsed TEXT,status TEXT,error TEXT,active INTEGER DEFAULT 1);
                CREATE TABLE IF NOT EXISTS library_jobs(id TEXT PRIMARY KEY,kb_id TEXT,status TEXT,error TEXT,
                    generation TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,kb_id TEXT);
                CREATE TABLE IF NOT EXISTS knowledge_answers(id TEXT PRIMARY KEY,conversation_id TEXT,kb_id TEXT,
                    question TEXT,result_json TEXT,generation TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS directory_sources(id TEXT PRIMARY KEY,kb_id TEXT,path TEXT,last_scan TEXT);
                CREATE TABLE IF NOT EXISTS directory_entries(source_id TEXT,relative_path TEXT,sha256 TEXT,doc_id TEXT,status TEXT,
                    PRIMARY KEY(source_id,relative_path));
                CREATE TABLE IF NOT EXISTS product_feedback(id TEXT PRIMARY KEY,target_kind TEXT,target_id TEXT,
                    category TEXT,message TEXT,snapshot TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """)
            if "metrics" not in {r[1] for r in db.execute("PRAGMA table_info(library_jobs)")}:
                db.execute("ALTER TABLE library_jobs ADD COLUMN metrics TEXT")
            if "source_key" not in {
                r[1] for r in db.execute("PRAGMA table_info(library_documents)")
            }:
                db.execute("ALTER TABLE library_documents ADD COLUMN source_key TEXT")
            if "context_answer_ids" not in {
                r[1] for r in db.execute("PRAGMA table_info(knowledge_answers)")
            }:
                db.execute(
                    "ALTER TABLE knowledge_answers ADD COLUMN context_answer_ids TEXT NOT NULL DEFAULT '[]'"
                )
            if "metadata" not in {r[1] for r in db.execute("PRAGMA table_info(library_documents)")}:
                db.execute(
                    "ALTER TABLE library_documents ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'"
                )
            if "withdrawn" not in {r[1] for r in db.execute("PRAGMA table_info(library_documents)")}:
                db.execute("ALTER TABLE library_documents ADD COLUMN withdrawn INTEGER NOT NULL DEFAULT 0")
                # Preserve old explicit disables; superseded immutable versions
                # are identifiable by a newer active version of the same source.
                db.execute("UPDATE library_documents SET withdrawn=1 WHERE active=0 AND NOT EXISTS (SELECT 1 FROM library_documents newer WHERE newer.kb_id=library_documents.kb_id AND newer.source_key=library_documents.source_key AND newer.active=1)")
            db.execute("UPDATE library_documents SET source_key=name WHERE source_key IS NULL")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.workspace.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
