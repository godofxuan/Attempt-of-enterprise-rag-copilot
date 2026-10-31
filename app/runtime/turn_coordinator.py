"""One user input, multiple attempts, and one terminal owner per run.

Only short SQLite transactions surround network work. Runs owns terminal state
for durable runs; inline callers use the identical finalizer on context exit.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import uuid

from app.runtime.request_context import current_request_id
from app.service_desk.store import ServiceError, encoded


class TurnCoordinator:
    def __init__(self, conversations):
        self.conversations = conversations
        self.workspace = conversations.workspace
        self.pending = {}
        with conversations.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS turn_attempts(
                id TEXT PRIMARY KEY,turn_id TEXT NOT NULL,run_id TEXT NOT NULL,
                status TEXT NOT NULL,result TEXT,error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("CREATE INDEX IF NOT EXISTS turns_status ON conversation_turns(status)")
            # Startup occurs under the exclusive workspace lease. Old pending
            # turns belong to an interrupted process, not a currently live run.
            db.execute("UPDATE conversation_turns SET status='INTERRUPTED' WHERE status='PENDING'")
            db.execute("UPDATE turn_attempts SET status='interrupted' WHERE status='running'")

    def attempts(self, turn_id):
        with self.conversations.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM turn_attempts WHERE turn_id=? ORDER BY rowid", (turn_id,)
                )
            ]

    def delivery(self, turn_id):
        with self.conversations.db() as db:
            row = db.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            command = db.execute("SELECT payload FROM turn_commands WHERE turn_id=?", (turn_id,)).fetchone()
        state = (json.loads(row[0] or "{}") if row else {}).get("turn_delivery", {
            "accepted": False, "requested": {}, "items": {}, "input_applied": False,
            "turn_id": turn_id, "status": "partial", "pending": ["request_brief"],
            "retryable": True, "next_action": "继续处理未完成请求",
        })
        task_id = json.loads(command[0]).get("task_id") if command else None
        if task_id and state.get("accepted") and state.get("requested", {}).get("preview"):
            from app.workbench_service import local_actor
            task = self.workspace.service.store.get_task(local_actor(), task_id)
            if task["user_execution_ceiling"] == "READ_ONLY":
                # Re-evaluate persisted model metadata against current user authority.
                # Keep the old proposal as evidence, never revive a forbidden action.
                state = {**state, "accepted":False, "rejected_prior_request":state["requested"],
                         "requested":{}, "items":{k:v for k,v in state["items"].items() if k != "preview"}}
        return state

    def save_delivery(self, turn_id, delivery):
        with self.conversations.db() as db:
            row = db.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServiceError("TURN_NOT_FOUND")
            payload = json.loads(row[0] or "{}")
            payload["turn_delivery"] = delivery
            db.execute("UPDATE conversation_turns SET payload=? WHERE id=?", (encoded(payload), turn_id))

    def accept_request(self, turn_id, request):
        """A brief from the SAME native model response, never user consent."""
        if not isinstance(request, dict) or set(request) != {"preview", "knowledge_quote"}:
            raise ServiceError("INVALID_TURN_REQUEST")
        if type(request["preview"]) is not bool or not isinstance(request["knowledge_quote"], str):
            raise ServiceError("INVALID_TURN_REQUEST")
        with self.conversations.db() as db:
            text = db.execute("SELECT text FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()[0]
            command = db.execute("SELECT payload FROM turn_commands WHERE turn_id=?", (turn_id,)).fetchone()
        task_id = json.loads(command[0]).get("task_id") if command else None
        if task_id and request["preview"]:
            from app.workbench_service import local_actor
            task = self.workspace.service.store.get_task(local_actor(), task_id)
            if task["user_execution_ceiling"] == "READ_ONLY":
                raise ServiceError("EXECUTION_CEILING", data={"operation":"preview", "ceiling":"READ_ONLY"})
        if request["knowledge_quote"] and request["knowledge_quote"] not in text:
            raise ServiceError("TURN_QUOTE_NOT_IN_INPUT")
        state = self.delivery(turn_id)
        if state["accepted"] and state["requested"] != request:
            raise ServiceError("TURN_REQUEST_CONFLICT")
        state.update(accepted=True, requested=request, authority="MAIN_MODEL_BRIEF_NOT_PERMISSION_OR_TRUTH")
        self.save_delivery(turn_id, state)

    def observe(self, turn_id, name, result, task):
        state = self.delivery(turn_id)
        if name == "update_parameters" and result["status"] == "ok":
            state["input_applied"] = True
        if name in {"prepare_preview", "knowledge_answer"}:
            kind = "preview" if name == "prepare_preview" else "knowledge"
            data = result.get("data") or {}
            state["items"][kind] = {
                "status": "ready" if result["status"] == "ok" else "retryable_error",
                "ref": data.get("proposal_id") if kind == "preview" else data.get("id"),
                "facts_revision": task["facts_revision"], "expires_at": data.get("expires_at"),
                "error_code": result.get("code"),
            }
        self.save_delivery(turn_id, state)

    def result(self, turn_id, task):
        state = self.delivery(turn_id)
        requested = state["requested"]
        items = {k: dict(v) for k, v in state["items"].items()}
        for key, needed in (("preview", requested.get("preview")), ("knowledge", bool(requested.get("knowledge_quote")))):
            if needed and key not in items:
                items[key] = {"status": "pending"}
        preview = items.get("preview")
        if preview and preview["status"] == "ready" and not task.get("receipt") and (
            task.get("pending_proposal_id") != preview.get("ref")
            or task["facts_revision"] != preview.get("facts_revision")
            or (preview.get("expires_at") and self.workspace.service.store.clock() >= preview["expires_at"])
        ):
            preview.update(status="pending", error_code="PREVIEW_CHANGED")
        if task["status"] == "CANCELLED" and "preview" in items:
            items["preview"]["status"] = "cancelled"
        pending = [kind for kind, item in items.items() if item["status"] not in {"ready", "cancelled"}]
        if not state["accepted"]:
            pending.append("request_brief")
        return {**state, "items": items, "pending": pending,
                "status": "partial" if pending else "complete", "retryable": bool(pending),
                "next_action": "重试解释" if "knowledge" in pending else "生成当前预览" if pending == ["preview"] else "继续处理未完成请求" if pending else None,
                "turn_id": turn_id}

    def for_task(self, task):
        with self.conversations.db() as db:
            row = db.execute("SELECT t.id FROM conversation_turns t JOIN turn_commands c ON c.turn_id=t.id WHERE json_extract(c.payload,'$.task_id')=? AND t.role='user' AND json_type(t.payload,'$.turn_delivery')='object' ORDER BY t.rowid DESC LIMIT 1", (task["task_id"],)).fetchone()
        return self.result(row[0], task) if row else None

    def prepared_by_user(self, task, proposal):
        delivery = self.for_task(task)
        if delivery and "preview" in delivery["pending"]:
            self.observe(delivery["turn_id"], "prepare_preview", {"status":"ok", "data":proposal}, task)
            delivery = self.result(delivery["turn_id"], task)
            self.save_delivery(delivery["turn_id"], delivery)
            with self.conversations.db() as db:
                db.execute("UPDATE conversation_turns SET status=? WHERE id=?", (
                    "DONE" if delivery["status"] == "complete" else "PARTIAL", delivery["turn_id"]))

    @asynccontextmanager
    async def attempt(self, cid, text, message_id, *, task_id=None, retry=False):
        run_id = current_request_id() or "inline-" + uuid.uuid4().hex
        with self.conversations.db() as db:
            known = db.execute(
                "SELECT * FROM conversation_turns WHERE id=?", (message_id,)
            ).fetchone()
            if known and (known["conversation_id"] != cid or known["text"] != text):
                raise ServiceError("MESSAGE_ID_CONFLICT")
            if known and known["status"] == "PENDING":
                raise ServiceError("TURN_ALREADY_RUNNING")
            cached = (
                json.loads(known["payload"])
                if known and (known["status"] == "DONE" or known["status"] == "PARTIAL" and not retry) and known["payload"]
                else None
            )
            if cached is None:
                if known:
                    db.execute(
                        "UPDATE conversation_turns SET status='PENDING',run_id=? WHERE id=?",
                        (run_id, message_id),
                    )
                else:
                    db.execute(
                        "INSERT INTO conversation_turns(id,conversation_id,role,kind,text,run_id,status) VALUES(?,?,'user','message',?,?,'PENDING')",
                        (message_id, cid, text, run_id),
                    )
                attempt_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO turn_attempts(id,turn_id,run_id,status) VALUES(?,?,?,'running')",
                    (attempt_id, message_id, run_id),
                )
        value = {"run_id": run_id, "cached": cached, "result": None}
        if cached is not None:
            yield value
            return
        self.pending[run_id] = {
            "turn_id": message_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "value": value,
        }
        # Direct service calls share the same code without manufacturing a run.
        with self.conversations.db() as db:
            durable = (
                db.execute("SELECT 1 FROM workbench_runs WHERE id=?", (run_id,)).fetchone()
                is not None
            )
        status, error = "succeeded", None
        try:
            yield value
        except BaseException as exc:
            status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            error = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            if not durable:
                self.workspace.runs.lifecycle.finish(run_id, "turn", {}, status, error)

    def finish(self, run_id, status, error):
        owned = self.pending.pop(run_id, None)
        if owned is None:
            return
        task_id, message_id = owned["task_id"], owned["turn_id"]
        if task_id and status != "succeeded":
            if status in {"cancelled", "interrupted"}:
                self.workspace.service.message_cancelled(task_id, message_id)
            else:
                self.workspace.service.message_failed(task_id, message_id, error)
        result = (
            self.workspace.service.view(task_id)
            if task_id and status == "succeeded"
            else owned["value"]["result"]
        )
        delivery = self.result(message_id, result) if result and task_id else None
        if delivery:
            result = {**result, "turn_delivery": delivery}
            if delivery["status"] == "partial" and not result.get("receipt") and result["status"] != "CANCELLED":
                from app.workbench_service import local_actor
                with self.workspace.service.store.transaction() as db:
                    task = self.workspace.service.store._task(db, local_actor(), task_id)
                    task.update(status="BLOCKED", assistant_text=(task.get("assistant_text") or "") + "\n" + delivery["next_action"])
                    self.workspace.service.store._save(db, task)
        failure_payload = {"error": error, "retryable": True}
        if task_id:
            failure_payload["turn_delivery"] = self.delivery(message_id)
        turn_status = "PARTIAL" if status == "succeeded" and delivery and delivery["status"] == "partial" else "DONE" if status == "succeeded" else status.upper()
        with self.conversations.db() as db:
            db.execute(
                "UPDATE conversation_turns SET status=?,payload=? WHERE id=?",
                (
                    turn_status,
                    encoded(result)
                    if result is not None
                    else encoded(failure_payload),
                    message_id,
                ),
            )
            db.execute("UPDATE conversation_turns SET status=? WHERE run_id=? AND role='assistant'", (turn_status, run_id))
            db.execute(
                "UPDATE turn_attempts SET status=?,result=?,error=? WHERE id=?",
                (
                    status,
                    encoded(result) if result is not None else None,
                    error,
                    owned["attempt_id"],
                ),
            )
