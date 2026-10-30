from __future__ import annotations
import asyncio, json, hashlib, os, re, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from app.knowledge.common import identifier, named_source_scope


class JobsOperations:
    async def start(self):
        with self.db() as db:
            db.execute(
                "UPDATE library_jobs SET status='INTERRUPTED',error='Process stopped before completion; retry required' WHERE status='RUNNING'"
            )
            pending = db.execute(
                "SELECT id,kb_id FROM library_jobs WHERE status='QUEUED'"
            ).fetchall()
        for job in pending:
            self.schedule(job["id"], job["kb_id"])

    async def close(self):
        self.closing = True
        for task in self.running:
            task.cancel()
        await asyncio.gather(*self.running, return_exceptions=True)

    def enqueue(self, kb_id, *, changed=False):
        self.require(kb_id)
        with self.db() as db:
            old = db.execute(
                "SELECT id,status FROM library_jobs WHERE kb_id=? AND status IN ('QUEUED','RUNNING') ORDER BY CASE status WHEN 'QUEUED' THEN 0 ELSE 1 END",
                (kb_id,),
            ).fetchone()
            if old and (old["status"] == "QUEUED" or not changed):
                return {"id": old["id"], "status": old["status"]}
            job_id = identifier("job")
            db.execute(
                "INSERT INTO library_jobs(id,kb_id,status) VALUES(?,?,'QUEUED')", (job_id, kb_id)
            )
        self.schedule(job_id, kb_id)
        return {"id": job_id, "status": "QUEUED"}

    def schedule(self, job_id, kb_id):
        task = asyncio.create_task(self.build(job_id, kb_id))
        self.running.add(task)
        task.add_done_callback(self.running.discard)

    async def build(self, job_id, kb_id):
        async with self.lock:
            with self.db() as db:
                db.execute("UPDATE library_jobs SET status='RUNNING' WHERE id=?", (job_id,))
            try:
                loop = asyncio.get_running_loop()
                with self.db() as db:
                    if not db.execute(
                        "SELECT 1 FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",
                        (kb_id,),
                    ).fetchone():
                        raise ValueError("NO_PARSED_DOCUMENTS")
                model_digest = await self.workspace.models.embedding_identity()
                result, document_ids, metrics = await asyncio.to_thread(
                    self._build,
                    job_id,
                    kb_id,
                    self.workspace.models.sync_embed(loop, purpose="index_embedding"),
                    model_digest,
                )
                if self.closing:
                    raise asyncio.CancelledError()
                with self.db() as db:
                    current = {
                        r[0]
                        for r in db.execute(
                            "SELECT id FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",
                            (kb_id,),
                        )
                    }
                    metadata_now = {
                        r["id"]: json.loads(r["metadata"])
                        for r in db.execute(
                            "SELECT id,metadata FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",
                            (kb_id,),
                        )
                    }
                if current != set(document_ids) or metadata_now != metrics["document_metadata"]:
                    raise ValueError("LIBRARY_CHANGED_RETRY")
                from app.indexing.store import activate_version

                await asyncio.to_thread(
                    activate_version, self.workspace.root / "indexes" / kb_id, result.run_id
                )
                with self.db() as db:
                    db.execute(
                        "UPDATE library_jobs SET status='SUCCEEDED',generation=?,metrics=? WHERE id=?",
                        (result.run_id, json.dumps(metrics), job_id),
                    )
                self.snapshots.pop(kb_id, None)
            except BaseException as exc:
                with self.db() as db:
                    db.execute(
                        "UPDATE library_jobs SET status=?,error=? WHERE id=?",
                        (
                            "INTERRUPTED" if isinstance(exc, asyncio.CancelledError) else "FAILED",
                            type(exc).__name__ + ": " + str(exc),
                            job_id,
                        ),
                    )
                if isinstance(exc, asyncio.CancelledError):
                    raise

    def _build(self, job_id, kb_id, embed, model_digest):
        from app.ingestion.chunking import ChunkerConfig
        from app.indexing.store import build_index_version

        with self.db() as db:
            documents = db.execute(
                "SELECT * FROM library_documents WHERE kb_id=? AND active=1 AND status!='FAILED'",
                (kb_id,),
            ).fetchall()
        if not documents:
            raise ValueError("NO_PARSED_DOCUMENTS")
        source = self.workspace.root / "documents" / kb_id / "builds" / job_id
        source.mkdir(parents=True, exist_ok=False)
        manifest_docs = []
        parses = {}
        for doc in documents:
            # Feed the original parse to the existing publisher. Re-parsing an
            # artificial Markdown wrapper destroyed PDF/Word source locations.
            path = self.document_path(doc)
            content = path.read_bytes()
            kind = path.suffix.lstrip(".")
            relative = doc["id"] + "." + kind
            (source / relative).write_bytes(content)
            parses[relative] = json.loads(doc["parsed"])
            details = json.loads(doc["metadata"])
            metadata = {
                "policy_id": hashlib.sha256(
                    (doc["source_key"] or doc["name"]).encode()
                ).hexdigest()[:20],
                "version_id": doc["id"],
                "version": str(doc["version"]),
                "status": "active",
                "effective_from": details.get("effective_from")
                or datetime.now(timezone.utc).date().isoformat(),
                "authority": 100,
                "actual_department": "local",
                "filed_department": "local",
                "tenant": "local",
                "region": "local",
                "acl_groups": ["local-owner"],
                "variant": "authoritative",
            }
            manifest_docs.append(
                {
                    "doc_id": doc["id"],
                    "path": relative,
                    "sha256": doc["sha256"],
                    "byte_count": len(content),
                    "format": kind,
                    "source_type": details.get("source_type") or "wiki",
                    "variant": "authoritative",
                    "metadata": metadata,
                    "fact_ids": [],
                }
            )
        manifest = {
            "schema_version": "enterprise_corpus_manifest_v1",
            "producer": "enterprise_agentic_rag_v2",
            "generator_version": "workbench-1",
            "profile_id": kb_id,
            "seed": 0,
            "facts_sha256": "0" * 64,
            "profile_sha256": "0" * 64,
            "document_count": len(documents),
            "counts_by_format": dict(Counter(d["format"] for d in manifest_docs)),
            "counts_by_source_type": dict(Counter(d["source_type"] for d in manifest_docs)),
            "counts_by_variant": {"authoritative": len(documents)},
            "documents": manifest_docs,
        }
        (source / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf8"
        )
        from app.indexing.workbench_cache import CachedChunkEmbeddings

        chunker = ChunkerConfig(mode="heading", chunk_size=1000, overlap=100)
        embeddings = CachedChunkEmbeddings(self.workspace, model_digest, embed, chunker)
        from app.ingestion.saved_parses import SavedParseRegistry

        result = build_index_version(
            root=self.workspace.root / "indexes" / kb_id,
            input_dir=source,
            run_id=job_id,
            chunker_config=chunker,
            embedding_model=self.workspace.config.embedding_model,
            embed_chunks=embeddings,
            activate=False,
            registry=SavedParseRegistry(parses),
        )
        return (
            result,
            [d["id"] for d in documents],
            {
                "embedding_hits": embeddings.hits,
                "embedding_misses": embeddings.misses,
                "canonical_documents": len(documents),
                "chunks": result.indexed_chunk_count,
                "document_metadata": {d["id"]: json.loads(d["metadata"]) for d in documents},
            },
        )
