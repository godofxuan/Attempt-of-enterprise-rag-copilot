"""One persistent user timeline linking knowledge, tasks and real business objects."""

import json
import sqlite3
from contextlib import contextmanager
import uuid
import base64
from datetime import datetime, timezone

from app.service_desk.store import ServiceError, encoded


class ConversationService:
    def __init__(self, workspace):
        self.workspace = workspace
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,kb_id TEXT)")
            fields = {r[1] for r in db.execute("PRAGMA table_info(conversations)")}
            for name in ("title", "task_id", "updated_at"):
                if name not in fields:
                    db.execute("ALTER TABLE conversations ADD COLUMN " + name + " TEXT")
            if "archived" not in fields:
                db.execute(
                    "ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                )
            db.execute(
                "CREATE INDEX IF NOT EXISTS conversation_order ON conversations(updated_at DESC,id DESC)"
            )
            db.execute("""CREATE TABLE IF NOT EXISTS turn_commands(
                turn_id TEXT, revision INTEGER, conversation_id TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(turn_id,revision))""")
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_turns(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,
                role TEXT,kind TEXT,text TEXT,payload TEXT,run_id TEXT,status TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS conversation_tasks(conversation_id TEXT,task_id TEXT UNIQUE,PRIMARY KEY(conversation_id,task_id))"
            )
        with self.db() as db:
            migrated = db.execute(
                "SELECT value FROM workspace_meta WHERE key='conversation_history_v2'"
            ).fetchone()
        if not migrated:
            self._migrate_history()
            with self.db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO workspace_meta VALUES('conversation_history_v2','1')"
                )
        from app.runtime.turn_coordinator import TurnCoordinator

        self.coordinator = TurnCoordinator(self)

    def _migrate_history(self):
        with self.db() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            answers = (
                [dict(r) for r in db.execute("SELECT * FROM knowledge_answers ORDER BY rowid")]
                if "knowledge_answers" in tables
                else []
            )
            tasks = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM agent_tasks WHERE tenant='local' AND owner='local-owner'"
                )
            ]
        for answer in answers:
            cid = answer["conversation_id"]
            tool_origin = any(
                (task.get("knowledge_result") or {}).get("id") == answer["id"]
                or any(
                    isinstance(o.get("result", {}).get("data"), dict)
                    and o["result"]["data"].get("id") == answer["id"]
                    for o in task.get("observations", [])
                    if o.get("tool") == "knowledge_answer"
                )
                for task in tasks
            )
            with self.db() as db:
                if tool_origin:
                    # Correct only the derived timeline attribution. Raw answer,
                    # model requests and original user message remain unchanged.
                    db.execute(
                        "UPDATE conversation_turns SET role='tool',kind='knowledge_query' WHERE id=? AND kind='historical_question'",
                        (answer["id"] + "-question",),
                    )
                represented = db.execute(
                    "SELECT 1 FROM conversation_turns WHERE json_extract(payload,'$.id')=? OR json_extract(payload,'$.knowledge.id')=?",
                    (answer["id"], answer["id"]),
                ).fetchone()
            if represented:
                continue
            self.append(
                cid,
                "tool" if tool_origin else "user",
                "knowledge_query" if tool_origin else "historical_question",
                answer["question"],
                turn_id=answer["id"] + "-question",
            )
            self.append(
                cid,
                "assistant",
                "historical_answer",
                json.loads(answer["result_json"])["answer"],
                {"id": answer["id"], "result": json.loads(answer["result_json"])},
                turn_id=answer["id"] + "-answer",
            )
            with self.db() as db:
                db.execute(
                    "UPDATE conversations SET title=COALESCE(title,?) WHERE id=?",
                    ("知识：" + answer["question"][:50], cid),
                )
        for task in tasks:
            if task.get("product_runtime") and not task.get("conversation_id"):
                self.bind(task["task_id"])

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.workspace.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, kb_id=None, title="新会话"):
        cid = "conversation_" + uuid.uuid4().hex[:16]
        with self.db() as db:
            db.execute(
                "INSERT INTO conversations(id,kb_id,title,updated_at) VALUES(?,?,?,?)",
                (cid, kb_id, title, datetime.now(timezone.utc).isoformat()),
            )
        return self.get(cid)

    def get(self, cid):
        with self.db() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not row:
            raise ServiceError("CONVERSATION_NOT_FOUND")
        history = [r[0] for r in self._task_ids(cid)]
        active = row["task_id"]
        if active:
            task = self.workspace.service.view(active)
            if not self.workspace.service.is_active(task):
                active = None
        return {
            **dict(row),
            "active_task_id": active,
            "task_history": history,
            "turns": self.turns(cid),
        }

    def _task_ids(self, cid):
        with self.db() as db:
            return db.execute(
                "SELECT task_id FROM conversation_tasks WHERE conversation_id=? ORDER BY rowid DESC",
                (cid,),
            ).fetchall()

    def list(self):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM conversations ORDER BY updated_at DESC,rowid DESC LIMIT 100"
                )
            ]

    def page(self, *, limit=30, cursor=None, q="", archived=False):
        clauses, values = ["archived=?"], [int(archived)]
        if q:
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM conversation_turns t WHERE t.conversation_id=conversations.id AND t.text LIKE ? ESCAPE '\\'))"
            )
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            values.extend([pattern, pattern])
        if cursor:
            try:
                stamp, cid = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if not isinstance(stamp, str) or not isinstance(cid, str):
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError) as exc:
                raise ServiceError("INVALID_HISTORY_CURSOR") from exc
            clauses.append("(COALESCE(updated_at,'') < ? OR (COALESCE(updated_at,'')=? AND id<?))")
            values.extend([stamp, stamp, cid])
        with self.db() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM conversations WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY COALESCE(updated_at,'') DESC,id DESC LIMIT ?",
                    [*values, limit + 1],
                )
            ]
        items = rows[:limit]
        last = items[-1] if len(rows) > limit else None
        following = (
            base64.urlsafe_b64encode(
                json.dumps([last["updated_at"] or "", last["id"]]).encode()
            ).decode()
            if last
            else None
        )
        return {"items": items, "next_cursor": following}

    def update(self, cid, changes):
        self.get(cid)  # Keep the existing not-found check.
        if "kb_id" in changes:
            if changes["kb_id"]:
                self.workspace.library.require(changes["kb_id"])
            with self.workspace.runs.db() as db:
                if db.execute(
                    "SELECT 1 FROM workbench_runs WHERE status IN ('queued','running') AND (target=? OR json_extract(input_json,'$.conversation_id')=?)",
                    (cid, cid),
                ).fetchone():
                    raise ServiceError("CONVERSATION_RUNNING")
        with self.db() as db:
            for field in ("kb_id", "title", "archived"):
                if field in changes:
                    db.execute(
                        "UPDATE conversations SET " + field + "=? WHERE id=?", (changes[field], cid)
                    )
            if changes.get("kb_id"):
                # Complete only originally missing scope on unfinished turns; this also
                # recovers rc4 turns stranded after the conversation selected a KB.
                # Each command with a nonempty historical scope remains untouched.
                rows = db.execute(
                    "SELECT c.* FROM turn_commands c JOIN conversation_turns t ON t.id=c.turn_id WHERE c.conversation_id=? AND t.status IN ('FAILED','CANCELLED','INTERRUPTED','PARTIAL','WAITING_USER') AND c.revision=(SELECT MAX(revision) FROM turn_commands WHERE turn_id=c.turn_id)",
                    (cid,),
                ).fetchall()
                for row in rows:
                    command = json.loads(row["payload"])
                    if command["kb_id"] is None:
                        command["kb_id"] = changes["kb_id"]
                        db.execute(
                            "INSERT INTO turn_commands(turn_id,revision,conversation_id,payload) VALUES(?,?,?,?)",
                            (row["turn_id"], row["revision"] + 1, cid, encoded(command)),
                        )
        return self.get(cid)

    def command(self, payload):
        """Freeze intent once; attempts read current business facts separately."""
        cid, turn_id = payload["conversation_id"], payload["message_id"]
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM turn_commands WHERE turn_id=? ORDER BY revision DESC LIMIT 1",
                (turn_id,),
            ).fetchone()
            if row:
                command = json.loads(row["payload"])
                if command["conversation_id"] != cid or command["text"] != payload["text"]:
                    raise ServiceError("MESSAGE_ID_CONFLICT")
                return command
            # Migration of a failed pre-0.6.1 turn uses its saved original run, not current UI state.
            previous = db.execute(
                "SELECT input_json FROM workbench_runs WHERE json_extract(input_json,'$.message_id')=? ORDER BY rowid LIMIT 1",
                (turn_id,),
            ).fetchone()
        original = json.loads(previous[0]) if previous else payload
        conversation = self.get(cid)
        command = {
            "conversation_id": cid,
            "text": original["text"],
            "message_id": turn_id,
            "detailed": bool(original.get("detailed", False)),
            "task_id": original.get(
                "task_id", conversation["active_task_id"] if not previous else None
            ),
            "kb_id": original.get("kb_id", conversation["kb_id"]),
        }
        if command["task_id"]:
            command["accepted_facts_revision"] = original.get(
                "accepted_facts_revision", original.get("expected_facts_revision")
            )
            if command["accepted_facts_revision"] is None and not previous:
                command["accepted_facts_revision"] = self.workspace.service.view(
                    command["task_id"]
                )["facts_revision"]
        with self.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO turn_commands(turn_id,revision,conversation_id,payload) VALUES(?,0,?,?)",
                (turn_id, cid, encoded(command)),
            )
            stored = json.loads(db.execute(
                "SELECT payload FROM turn_commands WHERE turn_id=? ORDER BY revision DESC LIMIT 1", (turn_id,)
            ).fetchone()[0])
        if stored["conversation_id"] != cid or stored["text"] != payload["text"]:
            raise ServiceError("MESSAGE_ID_CONFLICT")
        return stored

    def turns(self, cid):
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM conversation_turns WHERE conversation_id=? ORDER BY rowid", (cid,)
            ).fetchall()
        return [
            {**dict(r), "payload": json.loads(r["payload"]) if r["payload"] else None} for r in rows
        ]

    def bind(self, task_id, cid=None):
        from app.workbench_service import local_actor

        store = self.workspace.service.store
        task = store.get_task(local_actor(), task_id)
        cid = (
            cid
            or task.get("conversation_id")
            or self.create(task.get("kb_id"), task["goal"][:60] or "服务事项")["id"]
        )
        self.get(cid)
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO conversation_tasks VALUES(?,?)", (cid, task_id))
            db.execute(
                "UPDATE conversations SET task_id=?,kb_id=COALESCE(kb_id,?),updated_at=? WHERE id=?",
                (task_id, task.get("kb_id"), datetime.now(timezone.utc).isoformat(), cid),
            )
        with store.transaction() as db:
            current = store._task(db, local_actor(), task_id)
            if current.get("conversation_id") != cid:
                current["conversation_id"] = cid
                store._save(db, current)
        return cid

    def append(
        self, cid, role, kind, text, payload=None, *, turn_id=None, run_id=None, status="DONE"
    ):
        turn_id = turn_id or uuid.uuid4().hex
        with self.db() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO conversation_turns(id,conversation_id,role,kind,text,payload,run_id,status) VALUES(?,?,?,?,?,?,?,?)",
                (
                    turn_id,
                    cid,
                    role,
                    kind,
                    text,
                    encoded(payload) if payload is not None else None,
                    run_id,
                    status,
                ),
            )
            if inserted.rowcount:
                db.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), cid),
                )
        return turn_id

    async def task_turn(
        self, task_id, text, message_id, expected_facts_revision, detailed=False, kb_id=None, retry_pending=False
    ):
        from app.workbench_service import local_actor
        from app.agent_runtime.workbench_agent import build_service_agent

        service = self.workspace.service
        task = service.store.get_task(local_actor(), task_id)
        previous_delivery = self.coordinator.result(message_id, task)
        retry_knowledge = retry_pending and "knowledge" in previous_delivery["pending"]
        if retry_knowledge and task.get("pending_user_update") == message_id:
            # Only a prior successful host attempt proves that the original
            # input was consumed. An unresolved first attempt still needs review.
            if not any(a["status"] == "succeeded" for a in self.coordinator.attempts(message_id)):
                raise ServiceError("USER_UPDATE_PENDING")
        if task["status"] == "CANCELLED" and not retry_knowledge:
            raise ServiceError("CANCELLED")
        cid = self.bind(task_id)
        command = self.command(
            {
                "conversation_id": cid,
                "text": text,
                "message_id": message_id,
                "detailed": detailed,
                "task_id": task_id,
                "kb_id": kb_id if kb_id is not None else task.get("kb_id"),
            }
        )
        async with self.coordinator.attempt(cid, text, message_id, task_id=task_id, retry=retry_pending) as attempt:
            if attempt["cached"] is not None:
                if attempt["cached"].get("task_id") != task_id:
                    raise ServiceError("MESSAGE_ID_CONFLICT")
                return service.view(task_id)
            if task["facts_revision"] != expected_facts_revision:
                raise ServiceError("TASK_CHANGED")
            if task.get("pending_user_update") and task["pending_user_update"] != message_id:
                raise ServiceError("USER_UPDATE_PENDING")
            with service.store.transaction() as db:
                current = service.store._task(db, local_actor(), task_id)
                if retry_knowledge:
                    # This attempt only recovers a known delivery. Its original
                    # input was already handled; a read failure is not an
                    # unresolved change of business parameters or authority.
                    if current.get("pending_user_update") == message_id:
                        current.pop("pending_user_update")
                elif current["status"] != "CANCELLED":
                    current["pending_user_update"] = message_id
                service.store._save(db, current)
                db.execute(
                    "INSERT INTO workbench_messages VALUES(?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET status=excluded.status,result=NULL",
                    (message_id, task_id, text, "APPLIED" if retry_knowledge else "PENDING"),
                )
            turn = {
                "id": message_id,
                "text": text,
                "conversation_id": cid,
                "detailed": command["detailed"],
                "kb_id": command["kb_id"],
                "preserve_latest_parameters": len(self.coordinator.attempts(message_id)) > 1
                and (previous_delivery.get("input_applied") or command.get("accepted_facts_revision") != task["facts_revision"]),
            }
            if task["guided_request"]["kind"] == "knowledge":
                self.coordinator.accept_request(message_id, {"preview": False, "knowledge_quote": text})
            if retry_knowledge:
                quote = previous_delivery["requested"].get("knowledge_quote") or text
                try:
                    answer = await self.workspace.library.answer(command["kb_id"], quote,
                        conversation_id=cid, detailed=command["detailed"],
                        context_scope=task["guided_request"]["kind"] if task["guided_request"]["kind"] in {"loan","repair"} else None)
                except Exception as exc:
                    self.coordinator.observe(message_id, "knowledge_answer",
                        {"status": "error", "code": getattr(exc, "code", type(exc).__name__)}, task)
                    raise
                with service.store.transaction() as db:
                    latest = service.store._task(db, local_actor(), task_id)
                    latest["knowledge_result"] = answer
                    service.store._save(db, latest)
                self.coordinator.observe(message_id, "knowledge_answer", {"status": "ok", "data": answer}, task)
                self.workspace.runs.event(attempt["run_id"], "tool_result", {"tool": "knowledge_answer", "origin": "USER_RETRY_PENDING_DELIVERY", "result": {"status":"ok", "data": answer}})
                if task["status"] != "CANCELLED":
                    service.finish_turn(task_id, "", {"knowledge_answer"})
            else:
                await build_service_agent(service).run(task_id, attempt["run_id"], turn=turn)
            with service.store.transaction() as db:
                current = service.store._task(db, local_actor(), task_id)
                if current.get("pending_user_update") == message_id:
                    current.pop("pending_user_update")
                service.store._save(db, current)
                db.execute(
                    "UPDATE workbench_messages SET status='APPLIED',result=? WHERE id=?",
                    (encoded({"conversation_id": cid}), message_id),
                )
            result = service.view(task_id)
            result["turn_delivery"] = self.coordinator.result(message_id, result)
            if result["turn_delivery"]["status"] == "complete" and result["status"] != "CANCELLED":
                service.complete_readonly_turn(task_id, (task.get("knowledge_result") or {}).get("id"))
            self.append(
                cid,
                "assistant",
                "result",
                result.get("assistant_text") or result.get("question") or result["next_step"],
                {
                    "task_id": task_id,
                    "knowledge": result.get("knowledge_result")
                    if (result.get("knowledge_result") or {}).get("id")
                    != (task.get("knowledge_result") or {}).get("id")
                    else None,
                    "preview": result.get("preview"),
                    "receipt": result.get("receipt"),
                    "facts": result["facts"],
                    "turn_delivery": result["turn_delivery"],
                },
                run_id=attempt["run_id"],
            )
            attempt["result"] = result
        return {**service.view(task_id), "turn_delivery": self.coordinator.result(message_id, service.view(task_id))}

    def _done(self, message_id):
        with self.db() as db:
            row = db.execute(
                "SELECT status FROM conversation_turns WHERE id=?", (message_id,)
            ).fetchone()
        return bool(row and row["status"] == "DONE")

    async def turn(self, conversation_id, text, message_id, detailed=False, **scope):
        retry_pending = scope.pop("retry_pending", False)
        self.get(conversation_id)
        command = self.command(
            {
                "conversation_id": conversation_id,
                "text": text,
                "message_id": message_id,
                "detailed": detailed,
                **scope,
            }
        )
        task_id, kb_id, detailed = command["task_id"], command["kb_id"], command["detailed"]
        if task_id:
            task = self.workspace.service.view(task_id)
            return await self.task_turn(
                task["task_id"],
                text,
                message_id,
                task["facts_revision"],
                detailed=detailed,
                kb_id=kb_id,
                retry_pending=retry_pending,
            )
        async with self.coordinator.attempt(conversation_id, text, message_id) as attempt:
            if attempt["cached"] is not None:
                return attempt["cached"]
            if not kb_id:
                raise ServiceError("KNOWLEDGE_BASE_REQUIRED")
            answer = await self.workspace.library.answer(
                kb_id, text, conversation_id=conversation_id, detailed=detailed
            )
            self.append(
                conversation_id,
                "assistant",
                "knowledge",
                answer["result"]["answer"],
                answer,
                run_id=attempt["run_id"],
            )
            attempt["result"] = answer
            return answer
