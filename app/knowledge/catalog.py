from __future__ import annotations
import asyncio, json, hashlib, os
from pathlib import Path
from app.knowledge.common import identifier


class CatalogOperations:
    def list(self):
        with self.db() as db:
            return {
                "bases": [dict(r) for r in db.execute("SELECT * FROM knowledge_bases")],
                "documents": [
                    {**dict(r), "metadata": json.loads(r["metadata"])}
                    for r in db.execute(
                        "SELECT id,kb_id,name,source_key,version,status,error,active,metadata FROM library_documents"
                    )
                ],
                "jobs": [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM library_jobs ORDER BY created_at DESC LIMIT 30"
                    )
                ],
                "directory_sources": [
                    dict(r) for r in db.execute("SELECT * FROM directory_sources")
                ],
                "publications": {r[0]: self.publication_state(r[0]) for r in db.execute("SELECT id FROM knowledge_bases")},
            }

    def create(self, name):
        kb_id = identifier("kb")
        with self.db() as db:
            db.execute("INSERT INTO knowledge_bases VALUES(?,?)", (kb_id, name))
        return {"id": kb_id, "name": name}

    async def import_samples(self, kb_id):
        if not self.workspace.config.sample_data:
            raise ValueError("SYNTHETIC_SAMPLE_MODE_REQUIRED")
        from app.service_desk.rule_documents import sample_documents
        from app.workbench_service import local_actor

        documents = []
        for sample in sample_documents(self.workspace.service.store, local_actor()):
            doc = await self.upload(kb_id, sample["name"], sample["content"].encode("utf8"))
            if doc["status"] != "PARSED":
                raise ValueError("SAMPLE_PARSE_FAILED")
            metadata = {
                "source_type": "policy" if sample["rule_binding"] else "wiki",
                "service_tags": sample["service_tags"],
                "rule_binding": sample["rule_binding"],
                "effective_from": None,
            }
            with self.db() as db:
                db.execute(
                    "UPDATE library_documents SET metadata=? WHERE id=?",
                    (json.dumps(metadata), doc["id"]),
                )
            documents.append(doc)
        return {
            "documents": documents,
            "origin": "SYNTHETIC_RULE_BACKED_SAMPLE",
            "index_job": self.enqueue(kb_id, changed=True),
        }

    def require(self, kb_id):
        with self.db() as db:
            if not db.execute("SELECT 1 FROM knowledge_bases WHERE id=?", (kb_id,)).fetchone():
                raise ValueError("KNOWLEDGE_BASE_NOT_FOUND")

    async def upload(self, kb_id, name, content, *, source_key=None):
        from app.ingestion.parsers import build_default_registry

        self.require(kb_id)
        name = Path(name).name
        suffix = Path(name).suffix.lower()
        if suffix not in {".txt", ".md", ".pdf", ".docx"}:
            raise ValueError("UNSUPPORTED_DOCUMENT_TYPE")
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError("DOCUMENT_SIZE_LIMIT")
        digest = hashlib.sha256(content).hexdigest()
        with self.db() as db:
            old = db.execute(
                "SELECT * FROM library_documents WHERE kb_id=? AND COALESCE(source_key,name)=? AND active=1",
                (kb_id, source_key or name),
            ).fetchone()
            if old and old["sha256"] == digest and old["status"] != "FAILED":
                if old["status"] == "SOURCE_MISSING":
                    db.execute(
                        "UPDATE library_documents SET status='PARSED',error=NULL WHERE id=?",
                        (old["id"],),
                    )
                    return {**dict(old), "status": "PARSED", "error": None}
                return dict(old)
        doc_id = identifier("doc")
        folder = self.workspace.root / "documents" / kb_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (doc_id + suffix)
        path.write_bytes(content)
        error = None
        parsed = None
        try:
            parsed = await asyncio.to_thread(build_default_registry().parse, path)
            if not parsed.text.strip():
                raise ValueError("No readable text; OCR is not available")
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
        with self.db() as db:
            # Failed replacement does not retire the working document.
            if old and not error:
                db.execute("UPDATE library_documents SET active=0 WHERE id=?", (old["id"],))
            db.execute(
                "INSERT INTO library_documents(id,kb_id,name,version,sha256,path,parsed,status,error,active,source_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    kb_id,
                    name,
                    old["version"] + 1 if old else 1,
                    digest,
                    str(path),
                    parsed.model_dump_json() if parsed else None,
                    "FAILED" if error else "PARSED",
                    error,
                    0 if error else 1,
                    source_key or name,
                ),
            )
        return {
            "id": doc_id,
            "name": name,
            "status": "FAILED" if error else "PARSED",
            "error": error,
            "preview": parsed.text[:1200] if parsed else "",
        }

    def register_directory(self, kb_id, path):
        from app.ingestion.path_security import absolute_path_has_redirect

        self.require(kb_id)
        folder = Path(path).expanduser().absolute()
        if (
            folder.drive.startswith("\\\\")
            or not folder.is_dir()
            or folder == Path(folder.anchor)
            or absolute_path_has_redirect(folder)
        ):
            raise ValueError("SELECT_A_REAL_DOCUMENT_DIRECTORY_NOT_A_DRIVE_OR_REDIRECT")
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM directory_sources WHERE kb_id=? AND path=?", (kb_id, str(folder))
            ).fetchone()
            if row:
                return dict(row)
            source_id = identifier("directory")
            db.execute(
                "INSERT INTO directory_sources VALUES(?,?,?,NULL)", (source_id, kb_id, str(folder))
            )
        return {"id": source_id, "kb_id": kb_id, "path": str(folder), "last_scan": None}

    async def sync_directory(self, source_id):
        from app.ingestion.path_security import stat_is_redirect, absolute_path_has_redirect

        with self.db() as db:
            source = db.execute(
                "SELECT * FROM directory_sources WHERE id=?", (source_id,)
            ).fetchone()
            previous = {
                r["relative_path"]: dict(r)
                for r in db.execute(
                    "SELECT * FROM directory_entries WHERE source_id=?", (source_id,)
                )
            }
        if not source:
            raise ValueError("SOURCE_NOT_FOUND")
        folder = Path(source["path"])
        if not folder.is_dir() or absolute_path_has_redirect(folder):
            raise ValueError("SOURCE_DIRECTORY_UNAVAILABLE")

        def files():
            selected = []
            total = 0
            for parent, dirs, names in os.walk(folder, followlinks=False):
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith(".") and not stat_is_redirect((Path(parent) / d).lstat())
                ]
                for name in sorted(names):
                    p = Path(parent) / name
                    if p.suffix.lower() not in {".txt", ".md", ".pdf", ".docx"} or stat_is_redirect(
                        p.lstat()
                    ):
                        continue
                    if p.stat().st_size > 20 * 1024 * 1024:
                        raise ValueError("DOCUMENT_SIZE_LIMIT: " + name)
                    total += p.stat().st_size
                    if total > 64 * 1024 * 1024:
                        raise ValueError("DIRECTORY_TOTAL_LIMIT_64_MB")
                    selected.append((p.relative_to(folder).as_posix(), p.read_bytes()))
                    if len(selected) > 500:
                        raise ValueError("DIRECTORY_FILE_LIMIT_500")
            return selected

        selected = await asyncio.to_thread(files)
        report = {
            "source_id": source_id,
            "added": [],
            "replaced": [],
            "unchanged": [],
            "missing": [],
            "failed": [],
        }
        present = set()
        for relative, content in selected:
            present.add(relative)
            sha = hashlib.sha256(content).hexdigest()
            old = previous.get(relative)
            if old and old["sha256"] == sha and old["status"] == "PRESENT":
                report["unchanged"].append(relative)
                continue
            doc = await self.upload(
                source["kb_id"], Path(relative).name, content, source_key=source_id + "/" + relative
            )
            if doc["status"] == "FAILED":
                report["failed"].append({"path": relative, "error": doc["error"]})
                continue
            with self.db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO directory_entries VALUES(?,?,?,?,?)",
                    (source_id, relative, sha, doc["id"], "PRESENT"),
                )
            report["replaced" if old else "added"].append(relative)
        for relative, old in previous.items():
            if relative in present:
                continue
            report["missing"].append(relative)
            with self.db() as db:
                db.execute(
                    "UPDATE directory_entries SET status='MISSING' WHERE source_id=? AND relative_path=?",
                    (source_id, relative),
                )
                db.execute(
                    "UPDATE library_documents SET status='SOURCE_MISSING',error='Source file missing; last imported immutable version retained' WHERE id=?",
                    (old["doc_id"],),
                )
        with self.db() as db:
            db.execute(
                "UPDATE directory_sources SET last_scan=CURRENT_TIMESTAMP WHERE id=?", (source_id,)
            )
        if report["added"] or report["replaced"]:
            report["index_job"] = self.enqueue(source["kb_id"], changed=True)
        return report

    def update_document(self, doc_id, changes):
        if "active" in changes and changes["active"] is None:
            raise ValueError("ACTIVE_MUST_BE_BOOLEAN")
        with self.db() as db:
            row = db.execute("SELECT * FROM library_documents WHERE id=?", (doc_id,)).fetchone()
            if not row:
                raise ValueError("DOCUMENT_NOT_FOUND")
            if changes.get("active") and not row["parsed"]:
                raise ValueError("DOCUMENT_REQUIRES_SUCCESSFUL_PARSE")
            metadata = json.loads(row["metadata"])
            for key in ("source_type", "effective_from", "service_tags"):
                if key in changes:
                    metadata[key] = changes[key]
            if changes.get("active"):
                db.execute(
                    "UPDATE library_documents SET active=0 WHERE kb_id=? AND source_key=?",
                    (row["kb_id"], row["source_key"]),
                )
            if "active" in changes:
                db.execute("UPDATE library_documents SET withdrawn=? WHERE kb_id=? AND source_key=?", (int(not changes["active"]), row["kb_id"], row["source_key"]))
            db.execute(
                "UPDATE library_documents SET name=?,active=?,metadata=? WHERE id=?",
                (
                    changes.get("name") or row["name"],
                    int(changes.get("active", bool(row["active"]))),
                    json.dumps(metadata, ensure_ascii=False),
                    doc_id,
                ),
            )
        self.snapshots.pop(row["kb_id"], None)
        return {
            "id": doc_id,
            "kb_id": row["kb_id"],
            "name": changes.get("name") or row["name"],
            "active": changes.get("active", bool(row["active"])),
            "metadata": metadata,
            "index_update_required": bool(set(changes) - {"name"}),
        }

    async def retry_document(self, doc_id):
        from app.ingestion.parsers import build_default_registry

        with self.db() as db:
            row = db.execute("SELECT * FROM library_documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise ValueError("DOCUMENT_NOT_FOUND")
        path = self.document_path(row)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("IMMUTABLE_SOURCE_CHANGED")
        parsed = await asyncio.to_thread(build_default_registry().parse, path)
        if not parsed.text.strip():
            raise ValueError("NO_READABLE_TEXT_NO_OCR")
        with self.db() as db:
            db.execute(
                "UPDATE library_documents SET active=0 WHERE kb_id=? AND source_key=?",
                (row["kb_id"], row["source_key"]),
            )
            db.execute(
                "UPDATE library_documents SET parsed=?,status='PARSED',error=NULL,active=1 WHERE id=?",
                (parsed.model_dump_json(), doc_id),
            )
        self.snapshots.pop(row["kb_id"], None)
        return {
            "id": doc_id,
            "status": "PARSED",
            "index_job": self.enqueue(row["kb_id"], changed=True),
        }

    def feedback(self, target_kind, target_id, category, message):
        with self.db() as db:
            if target_kind == "answer":
                row = db.execute(
                    "SELECT * FROM knowledge_answers WHERE id=?", (target_id,)
                ).fetchone()
            elif target_kind == "task":
                row = db.execute(
                    "SELECT * FROM agent_tasks WHERE task_id=?", (target_id,)
                ).fetchone()
            else:
                raise ValueError("INVALID_FEEDBACK_TARGET")
            if not row:
                raise ValueError("FEEDBACK_TARGET_NOT_FOUND")
            feedback_id = identifier("feedback")
            db.execute(
                "INSERT INTO product_feedback(id,target_kind,target_id,category,message,snapshot) VALUES(?,?,?,?,?,?)",
                (
                    feedback_id,
                    target_kind,
                    target_id,
                    category,
                    message,
                    json.dumps(dict(row), ensure_ascii=False),
                ),
            )
        return {
            "id": feedback_id,
            "status": "RECORDED",
            "message": "已保存复现上下文；不会自动运行模型或声称问题已修复",
        }

    def feedbacks(self):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,target_kind,target_id,category,message,created_at FROM product_feedback ORDER BY rowid DESC LIMIT 30"
                )
            ]

    def feedback_case(self, feedback_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM product_feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            raise ValueError("FEEDBACK_NOT_FOUND")
        snapshot = json.loads(row["snapshot"])
        if row["target_kind"] == "answer":
            input = {
                "question": snapshot["question"],
                "kb_id": snapshot["kb_id"],
                "generation": snapshot["generation"],
                "conversation_id": snapshot["conversation_id"],
            }
            observed = json.loads(snapshot["result_json"])
        else:
            task = json.loads(snapshot["payload"])
            input = {
                key: task.get(key)
                for key in ("guided_request", "facts", "messages", "user_execution_ceiling")
            }
            observed = {
                key: task.get(key)
                for key in ("observations", "outcome", "receipt", "last_error", "status")
            }
        return {
            "id": row["id"],
            "kind": "UNREVIEWED_REGRESSION_CANDIDATE_NOT_AN_EXPECTED_ANSWER",
            "category": row["category"],
            "report": row["message"],
            "input": input,
            "observed": observed,
            "expected": None,
            "required_review": "根据原始用户要求、当时来源或实际业务库人工制定expected；未审，不自动启动模型或提交。",
        }
