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
        run_id = pointer.run_id
        with self.db() as db:
            publishing = db.execute(
                "SELECT status FROM library_jobs WHERE id=?", (run_id,)
            ).fetchone()
            if publishing and publishing[0] != "SUCCEEDED":
                previous = db.execute(
                    "SELECT generation FROM library_jobs WHERE kb_id=? AND status='SUCCEEDED' ORDER BY rowid DESC LIMIT 1",
                    (kb_id,),
                ).fetchone()
                if not previous:
                    raise ValueError("INDEX_NOT_READY: 首次发布尚未完成")
                run_id = previous[0]
        cached = self.snapshots.get(kb_id)
        if not cached or cached.version.manifest.run_id != run_id:
            cached = V2IndexSnapshot.load(root, run_id)
            self.snapshots[kb_id] = cached
        if cached.version.manifest.embedding.model.removesuffix(
            ":latest"
        ) != self.workspace.config.embedding_model.removesuffix(":latest"):
            raise ValueError(
                "INDEX_EMBEDDING_MODEL_CHANGED: 查询模型与索引不匹配，请用当前嵌入模型更新索引"
            )
        # Pending catalog changes do not invalidate the whole published index.
        # Per-document visibility is intersected with the original ACL below.
        return cached

    def published_scope(self, snapshot):
        with self.db() as db:
            job = db.execute(
                "SELECT metrics FROM library_jobs WHERE id=?", (snapshot.version.manifest.run_id,)
            ).fetchone()
            published = json.loads(job[0] or "{}").get("document_metadata", {}) if job else {}
            rows = db.execute("SELECT id,metadata,withdrawn FROM library_documents").fetchall()
        return {
            r["id"]
            for r in rows
            if r["id"] in snapshot.documents_by_id
            and not r["withdrawn"]
            and (r["id"] not in published or published[r["id"]] == json.loads(r["metadata"]))
        }

    def publication_state(self, kb_id):
        from app.indexing.store import load_active_pointer

        try:
            pointer = load_active_pointer(self.workspace.root / "indexes" / kb_id)
        except (ValueError, FileNotFoundError):
            return {"published_run_id": None, "update_state": "INDEX_REQUIRED"}
        with self.db() as db:
            latest = db.execute(
                "SELECT status,error FROM library_jobs WHERE kb_id=? ORDER BY rowid DESC LIMIT 1",
                (kb_id,),
            ).fetchone()
        return {
            "published_run_id": pointer.run_id,
            "update_state": latest["status"] if latest else "PUBLISHED",
            "update_error": latest["error"] if latest else None,
            "notice": "查询使用已发布版本；新变更成功后切换，主动停用立即排除。",
        }

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

    def conversation_context(self, kb_id, conversation_id, current_question="", context_scope=None):
        if not conversation_id:
            return []
        with self.db() as db:
            conversation = db.execute(
                "SELECT kb_id FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not conversation:
                raise ValueError("CONVERSATION_NOT_FOUND")
            if conversation["kb_id"] != kb_id:
                bound = db.execute(
                    "SELECT 1 FROM turn_commands WHERE conversation_id=? AND json_extract(payload,'$.kb_id')=? LIMIT 1",
                    (conversation_id, kb_id),
                ).fetchone()
                if not bound:
                    raise ValueError("CONVERSATION_KNOWLEDGE_BASE_MISMATCH")
            rows = db.execute(
                "SELECT id,question FROM knowledge_answers WHERE conversation_id=? AND kb_id=? AND (? IS NULL OR context_scope=?) ORDER BY rowid DESC LIMIT 4",
                (conversation_id, kb_id, context_scope, context_scope),
            ).fetchall()
        from app.runtime.context_window import recent_questions

        return recent_questions(rows, current_question)

    async def answer(
        self, kb_id, question, *, conversation_id=None, detailed=False, context_scope=None
    ):
        from app.domain.agent import AgentBudget
        from app.domain.queries import UserContext
        from app.retrieval.pipeline import HybridRetrievalPipeline
        from app.retrieval.navigation import DocumentNavigator
        from app.agent.tools_v2 import V2ToolRegistry
        from app.agent.runner_v2 import V2AgentRunner
        from app.agent.generation_v2 import GenerationV2ResponseBuilder

        if context_scope not in {None, "loan", "repair"}:
            raise ValueError("INVALID_CONTEXT_SCOPE")
        context = self.conversation_context(kb_id, conversation_id, question, context_scope)
        search = "\n".join([question] + [row["question"] for row in context])

        loop = asyncio.get_running_loop()
        snapshot = await asyncio.to_thread(self.snapshot, kb_id)
        allowed_documents = self.published_scope(snapshot)
        with self.db() as db:
            topics_by_doc = {
                row["id"]: json.loads(row["metadata"]).get("service_tags")
                for row in db.execute(
                    "SELECT id,metadata FROM library_documents WHERE kb_id=?", (kb_id,)
                )
                if row["id"] in allowed_documents
            }
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

            from app.security.access import AccessPolicy, AccessDecision

            class PublishedAccess(AccessPolicy):
                def evaluate(self, user, resource):
                    decision = super().evaluate(user, resource)
                    if decision.allowed and resource.doc_id not in allowed_documents:
                        return AccessDecision(allowed=False, code="group_mismatch")
                    return decision

            published_access = PublishedAccess()
            pipeline = HybridRetrievalPipeline(
                snapshot,
                embed_text=self.workspace.models.sync_embed(loop),
                access_policy=published_access,
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
                registry=V2ToolRegistry(
                    DocumentNavigator(snapshot, pipeline=pipeline, access_policy=published_access)
                ),
                controller=controller,
                analyzer=ConversationAnalyzer(),
                response_builder=GenerationV2ResponseBuilder(
                    model=self.workspace.config.chat_model,
                    chat_fn=self.workspace.models.sync_chat(loop),
                    max_attempts=1,
                    primary_read_anchors_only=bool(deep_plan),
                    need_first_wire=True,
                    explanatory=self.workspace.config.experimental_grounded_expression,
                    topics_by_doc=topics_by_doc,
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
                        "answer_style": "experimental_grounded_expression"
                        if self.workspace.config.experimental_grounded_expression
                        else "verified_source_units",
                        "knowledge_strategy": controller.report()
                        if deep_plan
                        else {"strategy": "fast_shared_runner"},
                    }
                }
            )

        result = await asyncio.to_thread(generate)
        if any(source.doc_id not in self.published_scope(snapshot) for source in result.sources):
            raise ValueError("SOURCE_WITHDRAWN_DURING_RUN: 资料在运行中停用或改变，未发布旧结果")
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
            db.execute(
                "INSERT OR IGNORE INTO conversations(id,kb_id) VALUES(?,?)",
                (conversation_id, kb_id),
            )
            db.execute(
                "INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation,context_answer_ids,context_scope) VALUES(?,?,?,?,?,?,?,?)",
                (
                    answer_id,
                    conversation_id,
                    kb_id,
                    question,
                    result.model_dump_json(),
                    snapshot.version.manifest.run_id,
                    json.dumps([r["id"] for r in context]),
                    context_scope,
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
            "context_scope": context_scope,
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
        return [self._answer_record(r) for r in rows]

    def answer_by_id(self, answer_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM knowledge_answers WHERE id=?", (answer_id,)).fetchone()
        if row is None:
            from app.service_desk.store import ServiceError

            raise ServiceError("ANSWER_NOT_FOUND")
        return self._answer_record(dict(row))

    def _answer_record(self, r):
        return {
            **{k: r[k] for k in r if k != "result_json"},
            "result": json.loads(r["result_json"]),
            "source_notices": self.source_notices(json.loads(r["result_json"])),
            "service_options": self.service_options(json.loads(r["result_json"])),
        }

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
        if any(s["doc_id"] not in self.published_scope(snapshot) for s in value.get("sources", [])):
            return None
        return {
            "id": row["id"],
            "question": row["question"],
            "context_scope": row["context_scope"],
            "conversation_id": row["conversation_id"],
            "kb_id": kb_id,
            "result": value,
            "source_notices": self.source_notices(value),
        }
