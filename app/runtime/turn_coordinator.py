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
            db.execute('CREATE INDEX IF NOT EXISTS turns_status ON conversation_turns(status)')
            # Startup occurs under the exclusive workspace lease. Old pending
            # turns belong to an interrupted process, not a currently live run.
            db.execute("UPDATE conversation_turns SET status='INTERRUPTED' WHERE status='PENDING'")
            db.execute("UPDATE turn_attempts SET status='interrupted' WHERE status='running'")

    def attempts(self, turn_id):
        with self.conversations.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM turn_attempts WHERE turn_id=? ORDER BY rowid', (turn_id,))]

    @asynccontextmanager
    async def attempt(self, cid, text, message_id, *, task_id=None):
        run_id = current_request_id() or 'inline-' + uuid.uuid4().hex
        with self.conversations.db() as db:
            known = db.execute('SELECT * FROM conversation_turns WHERE id=?', (message_id,)).fetchone()
            if known and (known['conversation_id'] != cid or known['text'] != text):
                raise ServiceError('MESSAGE_ID_CONFLICT')
            if known and known['status'] == 'PENDING':
                raise ServiceError('TURN_ALREADY_RUNNING')
            cached = json.loads(known['payload']) if known and known['status'] == 'DONE' and known['payload'] else None
            if cached is None:
                if known:
                    db.execute("UPDATE conversation_turns SET status='PENDING',run_id=?,payload=NULL WHERE id=?", (run_id, message_id))
                else:
                    db.execute("INSERT INTO conversation_turns(id,conversation_id,role,kind,text,run_id,status) VALUES(?,?,'user','message',?,?,'PENDING')", (message_id, cid, text, run_id))
                attempt_id = uuid.uuid4().hex
                db.execute("INSERT INTO turn_attempts(id,turn_id,run_id,status) VALUES(?,?,?,'running')", (attempt_id, message_id, run_id))
        value = {'run_id': run_id, 'cached': cached, 'result': None}
        if cached is not None:
            yield value
            return
        self.pending[run_id] = {'turn_id': message_id, 'task_id': task_id, 'attempt_id': attempt_id, 'value': value}
        # Direct service calls share the same code without manufacturing a run.
        with self.conversations.db() as db:
            durable = db.execute('SELECT 1 FROM workbench_runs WHERE id=?', (run_id,)).fetchone() is not None
        status, error = 'succeeded', None
        try:
            yield value
        except BaseException as exc:
            status = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed'
            error = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            if not durable:
                self.workspace.runs.lifecycle.finish(run_id, 'turn', {}, status, error)

    def finish(self, run_id, status, error):
        owned = self.pending.pop(run_id, None)
        if owned is None:
            return
        task_id, message_id = owned['task_id'], owned['turn_id']
        if task_id and status != 'succeeded':
            if status in {'cancelled', 'interrupted'}:
                self.workspace.service.message_cancelled(task_id, message_id)
            else:
                self.workspace.service.message_failed(task_id, message_id, error)
        result = self.workspace.service.view(task_id) if task_id and status == 'succeeded' else owned['value']['result']
        with self.conversations.db() as db:
            db.execute('UPDATE conversation_turns SET status=?,payload=? WHERE id=?',
                       ('DONE' if status == 'succeeded' else status.upper(), encoded(result) if result is not None else encoded({'error': error, 'retryable': True}), message_id))
            db.execute('UPDATE turn_attempts SET status=?,result=?,error=? WHERE id=?',
                       (status, encoded(result) if result is not None else None, error, owned['attempt_id']))

