"""Durable, bounded runs independent of the lifetime of a browser HTTP request."""
import asyncio
from contextvars import Context
import json
import sqlite3
import uuid

from app.runtime.request_context import bind_request_context, current_request_context, reset_request_context


class Runs:
    def __init__(self, workspace):
        self.workspace = workspace
        self.closing = False
        from app.runtime.run_lifecycle import RunLifecycle
        self.lifecycle=RunLifecycle(workspace)
        self.tasks = {};self.contexts = {}
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workbench_runs(id TEXT PRIMARY KEY,kind TEXT,target TEXT,status TEXT,
                    input_json TEXT,result_json TEXT,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS run_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,
                    kind TEXT,data TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')
            db.execute("UPDATE workbench_runs SET status='interrupted',error='Process restarted; continue from persisted facts' WHERE status IN ('queued','running')")

    def db(self):
        db=sqlite3.connect(self.workspace.db_path,timeout=10);db.row_factory=sqlite3.Row;return db

    def event(self,run_id,kind,data):
        with self.db() as db:
            db.execute('INSERT INTO run_events(run_id,kind,data) VALUES(?,?,?)',(run_id,kind,json.dumps(data,ensure_ascii=False)))

    def start(self,kind,payload):
        run_id=uuid.uuid4().hex
        target=payload.get('task_id') or payload.get('conversation_id') or payload.get('kb_id')
        with self.db() as db:
            if db.execute("SELECT 1 FROM workbench_runs WHERE target=? AND status IN ('queued','running')",(target,)).fetchone():
                raise ValueError('RUN_ALREADY_ACTIVE')
            db.execute("INSERT INTO workbench_runs(id,kind,target,status,input_json) VALUES(?,?,?,'queued',?)",
                       (run_id,kind,target,json.dumps(payload,ensure_ascii=False)))
        self.event(run_id,'queued',{'kind':kind})
        self.tasks[run_id]=asyncio.create_task(self.execute(run_id,kind,payload),context=Context())
        self.tasks[run_id].add_done_callback(lambda handle:self._before_start_cancel(run_id,kind,payload,handle))
        return self.get(run_id)

    def _before_start_cancel(self,run_id,kind,payload,handle):
        if handle.cancelled() and self.get(run_id)['status']=='queued':
            self._finish(run_id,kind,payload,'interrupted' if self.closing else 'cancelled',None,None)

    def _finish(self,run_id,kind,payload,status,result,error):
        self.lifecycle.finish(run_id,kind,payload,status,error)
        if status=='succeeded' and isinstance(result,dict) and result.get('task_id'):
            result=self.workspace.service.view(result['task_id'])
        with self.db() as db:
            db.execute('UPDATE workbench_runs SET status=?,result_json=?,error=? WHERE id=?',
                (status,json.dumps(result,ensure_ascii=False) if result is not None else None,error,run_id))
        self.event(run_id,'finished' if status=='succeeded' else status,result if status=='succeeded' else {'error':error})
        self.contexts.pop(run_id,None);self.tasks.pop(run_id,None)

    async def execute(self,run_id,kind,payload):
        token=bind_request_context(run_id,deadline_ms=240000)
        self.contexts[run_id]=current_request_context()
        status='failed';result=None;error=None
        try:
            with self.db() as db:db.execute("UPDATE workbench_runs SET status='running' WHERE id=?",(run_id,))
            self.event(run_id,'running',{})
            if kind=='knowledge':result=await self.workspace.library.answer(**payload)
            elif kind=='service':result=await self.workspace.service.run(payload['task_id'],run_id)
            elif kind=='message':result=await self.workspace.service.message(**payload)
            elif kind=='conversation':result=await self.workspace.conversations.turn(**payload)
            else:raise ValueError('Unknown run kind')
            if self.contexts[run_id].cancelled.is_set():raise asyncio.CancelledError()
            status='succeeded'
        except asyncio.CancelledError:
            status='interrupted' if self.closing else 'cancelled'
            error='Process stopping' if self.closing else None
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)
        finally:
            try:self._finish(run_id,kind,payload,status,result,error)
            finally:reset_request_context(token)

    def get(self,run_id):
        with self.db() as db:row=db.execute('SELECT * FROM workbench_runs WHERE id=?',(run_id,)).fetchone()
        if not row:raise ValueError('RUN_NOT_FOUND')
        return {**dict(row),'result':json.loads(row['result_json']) if row['result_json'] else None}

    def events(self,run_id,after=0):
        self.get(run_id)
        with self.db() as db:return [{**dict(row),'data':json.loads(row['data'])} for row in db.execute('SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq',(run_id,after))]

    async def close(self):
        self.closing=True
        for context in self.contexts.values():context.cancelled.set()
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

    def cancel(self,run_id):
        if run_id in self.contexts:self.contexts[run_id].cancelled.set()
        if run_id in self.tasks:self.tasks[run_id].cancel()
