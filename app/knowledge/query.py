from __future__ import annotations
import asyncio, json
from app.knowledge.common import identifier, named_source_scope


class QueryOperations:
    def snapshot(self, kb_id):
        from app.indexing.store import load_active_pointer
        from app.retrieval.snapshot import V2IndexSnapshot

        self.require(kb_id)
        root = self.workspace.root / "indexes" / kb_id
        pointer = load_active_pointer(root)
        cached = self.snapshots.get(kb_id)
        if not cached or cached.version.manifest.run_id != pointer.run_id:
            cached = V2IndexSnapshot.load(root, pointer.run_id)
            self.snapshots[kb_id] = cached
        if cached.version.manifest.embedding.model.removesuffix(
            ":latest"
        ) != self.workspace.config.embedding_model.removesuffix(":latest"):
            raise ValueError(
                "INDEX_EMBEDDING_MODEL_CHANGED: 查询模型与索引不匹配，请用当前嵌入模型更新索引"
            )
        with self.db() as db:
            current = {
                r[0]
                for r in db.execute(
                    "SELECT id FROM library_documents WHERE kb_id=? AND active=1 AND parsed IS NOT NULL",
                    (kb_id,),
                )
            }
            job = db.execute(
                "SELECT status,metrics FROM library_jobs WHERE id=?", (pointer.run_id,)
            ).fetchone()
            metadata_now = {
                r["id"]: json.loads(r["metadata"])
                for r in db.execute(
                    "SELECT id,metadata FROM library_documents WHERE kb_id=? AND active=1 AND parsed IS NOT NULL",
                    (kb_id,),
                )
            }
        if job:
            if job["status"] != "SUCCEEDED":
                raise ValueError("INDEX_NOT_READY: 当前索引发布尚未完成，请稍后重试")
            old_metadata = json.loads(job["metrics"] or "{}").get("document_metadata")
            if old_metadata is not None and old_metadata != metadata_now:
                raise ValueError("INDEX_OUTDATED: 资料元数据已变化，请更新索引")
        if current != set(cached.documents_by_id):
            raise ValueError("INDEX_OUTDATED: 资料已变化，请更新索引后再提问；历史答案和版本仍保留")
        return cached

    def excerpt(self, doc_id, index_run_id, target_type, target_id):
        from app.retrieval.snapshot import V2IndexSnapshot

        with self.db() as db:
            row = db.execute("SELECT * FROM library_documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise ValueError("DOCUMENT_NOT_FOUND")
        snapshot = self.snapshots.get(row["kb_id"])
        if not snapshot or snapshot.version.manifest.run_id != index_run_id:
            snapshot = V2IndexSnapshot.load(
                self.workspace.root / "indexes" / row["kb_id"], index_run_id
            )
        if target_type == "document":
            resource = snapshot.documents_by_id.get(doc_id) if target_id == doc_id else None
        else:
            resource = snapshot.all_chunks_by_id.get(target_id)
            if resource and target_type == "parent" and resource.kind != "parent":
                resource = None
        if not resource or resource.doc_id != doc_id:
            raise ValueError("SOURCE_LOCATION_NOT_BOUND")
        spans = [s.model_dump(mode="json") for s in getattr(resource, "source_spans", [])]
        return {
            "document_id": doc_id,
            "name": row["name"],
            "version": row["version"],
            "active": bool(row["active"]),
            "text": resource.text[:12000],
            "truncated": len(resource.text) > 12000,
            "source_spans": spans,
            "location_basis": "original_parser" if spans else "legacy_index_location_only",
            "index_metadata": {
                "format": snapshot.documents_by_id[doc_id].format,
                "source_type": snapshot.documents_by_id[doc_id].source_type,
            },
            "current_metadata": json.loads(row["metadata"]),
        }

    def source_notices(self, result):
        notices = []
        with self.db() as db:
            for source in result.get("sources", []):
                row = db.execute(
                    "SELECT name,version,status,active FROM library_documents WHERE id=?",
                    (source["doc_id"],),
                ).fetchone()
                if row and not row["active"]:
                    notices.append(
                        f"{row['name']} v{row['version']}为回答当时的历史版本；当前资料已更新。"
                    )
                elif row and row["status"] == "SOURCE_MISSING":
                    notices.append(
                        f"{row['name']}源文件缺失，依据最后导入的v{row['version']}；未从缺失文件重新读取。"
                    )
        return list(dict.fromkeys(notices))

    def conversation_context(self, kb_id, conversation_id, current_question=""):
        if not conversation_id:
            return []
        with self.db() as db:
            conversation = db.execute(
                "SELECT kb_id FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not conversation:
                raise ValueError("CONVERSATION_NOT_FOUND")
            if conversation["kb_id"] != kb_id:
                raise ValueError("CONVERSATION_KNOWLEDGE_BASE_MISMATCH")
            rows = db.execute(
                "SELECT id,question FROM knowledge_answers WHERE conversation_id=? ORDER BY rowid DESC LIMIT 4",
                (conversation_id,),
            ).fetchall()
        from app.runtime.context_window import recent_questions

        return recent_questions(rows, current_question)

    async def answer(self, kb_id, question, *, conversation_id=None, detailed=False):
        from app.domain.agent import AgentBudget
        from app.domain.queries import UserContext
        from app.retrieval.pipeline import HybridRetrievalPipeline
        from app.retrieval.navigation import DocumentNavigator
        from app.agent.tools_v2 import V2ToolRegistry
        from app.agent.runner_v2 import V2AgentRunner
        from app.agent.generation_v2 import GenerationV2ResponseBuilder

        context = self.conversation_context(kb_id, conversation_id, question)
        search = "\n".join([question] + [row["question"] for row in context])

        loop = asyncio.get_running_loop()
        snapshot = await asyncio.to_thread(self.snapshot, kb_id)
        named_policies = named_source_scope(question, snapshot)
        deep_plan = None
        if detailed:
            from app.agent.deep_knowledge import plan_deep
            from app.agent.query_analysis import RuleFirstQueryAnalyzer

            check = RuleFirstQueryAnalyzer().analyze(
                question,
                UserContext(
                    user_id="local-owner", tenant_id="local", region="local", groups=["local-owner"]
                ),
            )
            if check.intent != "unsafe":
                catalog = [
                    {
                        "policy_id": doc.policy_id,
                        "title": next(
                            (
                                chunk.section_path[0]
                                for chunk in snapshot.all_chunks_by_id.values()
                                if chunk.doc_id == doc.doc_id and chunk.section_path
                            ),
                            doc.title,
                        ),
                    }
                    for doc in snapshot.documents_by_id.values()
                ]
                deep_plan = await plan_deep(
                    self.workspace.models, question, context, catalog if len(catalog) <= 20 else ()
                )

        def generate():
            from app.agent.controller_v2 import V2AgentController
            from app.agent.query_analysis import RuleFirstQueryAnalyzer

            class ConversationAnalyzer:
                def analyze(self, original, user):
                    from app.runtime.context_window import retrieval_windows

                    analysis = RuleFirstQueryAnalyzer().analyze(original, user)
                    if analysis.intent != "unsafe":
                        analysis = analysis.model_copy(
                            update={
                                "prior_user_questions": [row["question"] for row in context],
                                "search_queries": retrieval_windows(search),
                            }
                        )
                    if named_policies and analysis.intent != "unsafe":
                        current = set(analysis.filters.policy_ids)
                        policies = (
                            sorted(current.intersection(named_policies))
                            if current
                            else named_policies
                        )
                        if not policies:
                            raise ValueError("CONTRADICTORY_SOURCE_SCOPE")
                        analysis = analysis.model_copy(
                            update={
                                "filters": analysis.filters.model_copy(
                                    update={"policy_ids": policies}
                                )
                            }
                        )
                    if deep_plan and analysis.intent != "unsafe":
                        labels = [q.question for q in deep_plan.subquestions]
                        return analysis.model_copy(
                            update={
                                "intent": "comparison" if len(labels) > 1 else "fact",
                                "entities": labels if len(labels) > 1 else [],
                                "required_aspects": labels,
                                "search_queries": [q.query for q in deep_plan.subquestions],
                                "source": "model",
                            }
                        )
                    if not context or analysis.intent == "unsafe":
                        return analysis
                    # Search may carry prior user referents. Obligations remain
                    # the current original question, never the old answer as fact.
                    return analysis

            pipeline = HybridRetrievalPipeline(
                snapshot, embed_text=self.workspace.models.sync_embed(loop)
            )
            from app.agent.deep_knowledge import DeepController

            # A local model may load during embedding. Keep the existing run
            # deadline, but honor the configured transport timeout inside search.
            search_timeout_ms = min(
                120000, int(self.workspace.config.request_timeout_seconds * 1000)
            )
            controller = (
                DeepController(deep_plan, search_timeout_ms=search_timeout_ms)
                if deep_plan
                else V2AgentController(semantic_question=True, search_timeout_ms=search_timeout_ms)
            )
            runner = V2AgentRunner(
                registry=V2ToolRegistry(DocumentNavigator(snapshot, pipeline=pipeline)),
                controller=controller,
                analyzer=ConversationAnalyzer(),
                response_builder=GenerationV2ResponseBuilder(
                    model=self.workspace.config.chat_model,
                    chat_fn=self.workspace.models.sync_chat(loop),
                    max_attempts=1,
                    primary_read_anchors_only=bool(deep_plan),
                    need_first_wire=True,
                ),
                budget=AgentBudget(
                    deadline_ms=240000,
                    max_search_calls=6 if deep_plan else 2,
                    max_find_calls=4 if deep_plan else 2,
                    max_open_calls=4 if deep_plan else 2,
                    max_steps=18 if deep_plan else 12,
                ),
            )
            user = UserContext(
                user_id="local-owner", tenant_id="local", region="local", groups=["local-owner"]
            )
            # Whole historical questions already travel in QueryAnalysis. They
            # are not replies to a clarification and must not enter that wire.
            result = runner.run(question, user, top_k=6)
            return result.model_copy(
                update={
                    "trace": {
                        **result.trace,
                        "named_source_policy_ids": named_policies,
                        "knowledge_strategy": controller.report()
                        if deep_plan
                        else {"strategy": "fast_shared_runner"},
                    }
                }
            )

        result = await asyncio.to_thread(generate)
        with self.db() as db:
            names = {
                r["id"]: r["name"]
                for r in db.execute("SELECT id,name FROM library_documents WHERE kb_id=?", (kb_id,))
            }
        result = result.model_copy(
            update={
                "sources": [
                    source.model_copy(
                        update={
                            "title": names.get(source.doc_id),
                            "format": snapshot.documents_by_id[source.doc_id].format,
                            "source_type": snapshot.documents_by_id[source.doc_id].source_type,
                        }
                    )
                    for source in result.sources
                ]
            }
        )
        answer_id = identifier("answer")
        conversation_id = conversation_id or identifier("conversation")
        with self.db() as db:
            if db.execute(
                "SELECT 1 FROM conversations WHERE id=? AND kb_id!=?", (conversation_id, kb_id)
            ).fetchone():
                raise ValueError("CONVERSATION_KNOWLEDGE_BASE_MISMATCH")
            db.execute(
                "INSERT OR IGNORE INTO conversations(id,kb_id) VALUES(?,?)",
                (conversation_id, kb_id),
            )
            db.execute(
                "INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation,context_answer_ids) VALUES(?,?,?,?,?,?,?)",
                (
                    answer_id,
                    conversation_id,
                    kb_id,
                    question,
                    result.model_dump_json(),
                    snapshot.version.manifest.run_id,
                    json.dumps([r["id"] for r in context]),
                ),
            )
        value = result.model_dump(mode="json")
        if result.mode in {"system", "budget"}:
            # Retain the original failed answer/trace above. Product runs must
            # surface execution failure and a retry, not a successful empty turn.
            raise RuntimeError(f"KNOWLEDGE_{result.mode.upper()}:{answer_id}")
        return {
            "id": answer_id,
            "conversation_id": conversation_id,
            "kb_id": kb_id,
            "question": question,
            "source_notices": self.source_notices(value),
            "result": value,
            "service_options": self.service_options(value),
        }

    def service_options(self, result):
        ids = {s["doc_id"] for s in result.get("sources", [])}
        if not ids:
            return []
        with self.db() as db:
            rows = db.execute(
                "SELECT metadata FROM library_documents WHERE id IN ("
                + ",".join("?" for _ in ids)
                + ")",
                tuple(ids),
            ).fetchall()
        tags = {
            tag for row in rows for tag in (json.loads(row["metadata"]).get("service_tags") or [])
        }
        from app.service_desk.catalog import SERVICES

        return [
            {"key": key, "title": SERVICES[key].title} for key in sorted(tags) if key in SERVICES
        ]

    def answers(self):
        with self.db() as db:
            rows = [
                dict(r)
                for r in db.execute("SELECT * FROM knowledge_answers ORDER BY rowid DESC LIMIT 50")
            ]
        return [
            {
                **{k: r[k] for k in r if k != "result_json"},
                "result": json.loads(r["result_json"]),
                "source_notices": self.source_notices(json.loads(r["result_json"])),
                "service_options": self.service_options(json.loads(r["result_json"])),
            }
            for r in rows
        ]

    def valid_answer(self, answer_id, kb_id):
        if not answer_id:
            return None
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM knowledge_answers WHERE id=? AND kb_id=?", (answer_id, kb_id)
            ).fetchone()
        if not row:
            return None
        try:
            snapshot = self.snapshot(kb_id)
        except (ValueError, FileNotFoundError):
            return None
        if row["generation"] != snapshot.version.manifest.run_id:
            return None
        value = json.loads(row["result_json"])
        return {
            "id": row["id"],
            "question": row["question"],
            "conversation_id": row["conversation_id"],
            "kb_id": kb_id,
            "result": value,
            "source_notices": self.source_notices(value),
        }
