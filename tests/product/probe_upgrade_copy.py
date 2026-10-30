"""Actual full-workspace upgrade probe; no model HTTP sends and no source writes."""

import argparse
import json
from pathlib import Path
import shutil
import sqlite3

import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.workbench_app import create_workbench_app
from app.conversations import ConversationService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume-existing", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if args.resume_existing:
        assert (
            (root / "app.sqlite3").is_file()
            and (root / "documents").is_dir()
            and root != args.source.resolve()
        )
    else:
        assert not root.exists(), root
        root.mkdir(parents=True)
        for name in ("documents", "indexes", "cache"):
            if (args.source / name).exists():
                shutil.copytree(args.source / name, root / name)
        shutil.copy2(args.source / "workspace.json", root / "workspace.json")
        with (
            sqlite3.connect(args.database) as source,
            sqlite3.connect(root / "app.sqlite3") as target,
        ):
            source.backup(target)

    def external(request):
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        raise AssertionError("Upgrade program probe cannot send to models")

    counts = []
    migrations = []
    original = ConversationService._migrate_history

    def migration(self):
        migrations.append(str(self.workspace.root))
        return original(self)

    ConversationService._migrate_history = migration
    try:
        for start in range(2):
            app = create_workbench_app(
                Settings(workbench_enabled=True, data_dir=root, sqlite_path=root / "app.sqlite3"),
                model_transport=httpx.MockTransport(external),
            )
            with TestClient(app) as client:
                workspace = app.state.workspace
                with workspace.library.db() as db:
                    rows = db.execute(
                        "SELECT * FROM library_documents WHERE parsed IS NOT NULL"
                    ).fetchall()
                    checked = [
                        str(workspace.library.document_path(r).relative_to(root)) for r in rows
                    ]
                    counts.append(
                        {
                            name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                            for name in (
                                "conversations",
                                "conversation_turns",
                                "tickets",
                                "it_repair_tickets",
                                "model_calls",
                                "library_documents",
                            )
                        }
                    )
                for base in workspace.library.list()["bases"]:
                    try:
                        snapshot = workspace.library.snapshot(base["id"])
                    except FileNotFoundError:
                        continue  # Empty bases have no published index.
                    for document in snapshot.documents_by_id.values():
                        chunk = next(
                            c
                            for c in snapshot.all_chunks_by_id.values()
                            if c.doc_id == document.doc_id
                        )
                        result = workspace.library.excerpt(
                            document.doc_id,
                            snapshot.version.manifest.run_id,
                            "chunk",
                            chunk.chunk_id,
                        )
                        from app.retrieval.snapshot import V2IndexSnapshot

                        old = V2IndexSnapshot.load(
                            args.source / "indexes" / base["id"], snapshot.version.manifest.run_id
                        )
                        original_spans = [
                            s.model_dump(mode="json")
                            for s in old.all_chunks_by_id[chunk.chunk_id].source_spans
                        ]
                        assert result["text"] and result["source_spans"] == original_spans
                assert client.get("/api/product/tasks").status_code == 200
                assert client.get("/api/conversations").status_code == 200
        assert counts[0] == counts[1], counts
        assert len(migrations) <= 1, migrations
        record = {
            "kind": "PROGRAM_FULL_040_WORKSPACE_UPGRADE_NO_MODEL_SEND",
            "source": str(args.source.resolve()),
            "baseline_database": str(args.database.resolve()),
            "copy": str(root),
            "counts": counts,
            "migration_invocations": len(migrations),
            "original_documents_resolved_in_copy": checked,
            "old_absolute_paths_not_required": True,
            "passed": True,
        }
        (root.parent / "FULL_WORKSPACE_UPGRADE.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), "utf8"
        )
        print(json.dumps(record, ensure_ascii=False))
    finally:
        ConversationService._migrate_history = original


if __name__ == "__main__":
    main()
