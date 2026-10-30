"""One persistent user timeline linking knowledge, tasks and real business objects."""
import json
import sqlite3
import uuid
from datetime import datetime,timezone

from app.service_desk.store import ServiceError,encoded


class ConversationService:
    def __init__(self,workspace):
        self.workspace=workspace
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,kb_id TEXT)')
            fields={r[1] for r in db.execute('PRAGMA table_info(conversations)')}
            for name in ('title','task_id','updated_at'):
                if name not in fields:db.execute('ALTER TABLE conversations ADD COLUMN '+name+' TEXT')
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_turns(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,
                role TEXT,kind TEXT,text TEXT,payload TEXT,run_id TEXT,status TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
            db.execute('CREATE TABLE IF NOT EXISTS conversation_tasks(conversation_id TEXT,task_id TEXT UNIQUE,PRIMARY KEY(conversation_id,task_id))')
        self._migrate_history()

    def _migrate_history(self):
        with self.db() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            answers=[dict(r) for r in db.execute('SELECT * FROM knowledge_answers ORDER BY rowid')] if 'knowledge_answers' in tables else []
            tasks=[json.loads(r[0]) for r in db.execute("SELECT payload FROM agent_tasks WHERE tenant='local' AND owner='local-owner'")]
        for answer in answers:
            cid=answer['conversation_id']
            tool_origin=any((task.get('knowledge_result') or {}).get('id')==answer['id'] or any(
                isinstance(o.get('result',{}).get('data'),dict) and o['result']['data'].get('id')==answer['id']
                for o in task.get('observations',[]) if o.get('tool')=='knowledge_answer') for task in tasks)
            with self.db() as db:
                if tool_origin:
                    # Correct only the derived timeline attribution. Raw answer,
                    # model requests and original user message remain unchanged.
                    db.execute("UPDATE conversation_turns SET role='tool',kind='knowledge_query' WHERE id=? AND kind='historical_question'",(answer['id']+'-question',))
                represented=db.execute("SELECT 1 FROM conversation_turns WHERE json_extract(payload,'$.id')=? OR json_extract(payload,'$.knowledge.id')=?",
                    (answer['id'],answer['id'])).fetchone()
            if represented:continue
            self.append(cid,'tool' if tool_origin else 'user','knowledge_query' if tool_origin else 'historical_question',answer['question'],turn_id=answer['id']+'-question')
            self.append(cid,'assistant','historical_answer',json.loads(answer['result_json'])['answer'],
                {'id':answer['id'],'result':json.loads(answer['result_json'])},turn_id=answer['id']+'-answer')
            with self.db() as db:db.execute('UPDATE conversations SET title=COALESCE(title,?) WHERE id=?',('知识：'+answer['question'][:50],cid))
        for task in tasks:
            if task.get('product_runtime') and not task.get('conversation_id'):self.bind(task['task_id'])

    def db(self):
        db=sqlite3.connect(self.workspace.db_path,timeout=10);db.row_factory=sqlite3.Row;return db

    def create(self,kb_id=None,title='新会话'):
        cid='conversation_'+uuid.uuid4().hex[:16]
        with self.db() as db:db.execute('INSERT INTO conversations(id,kb_id,title,updated_at) VALUES(?,?,?,?)',
            (cid,kb_id,title,datetime.now(timezone.utc).isoformat()))
        return self.get(cid)

    def get(self,cid):
        with self.db() as db:row=db.execute('SELECT * FROM conversations WHERE id=?',(cid,)).fetchone()
        if not row:raise ServiceError('CONVERSATION_NOT_FOUND')
        return {**dict(row),'turns':self.turns(cid)}

    def list(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM conversations ORDER BY COALESCE(updated_at,id) DESC LIMIT 100')]

    def turns(self,cid):
        with self.db() as db:rows=db.execute('SELECT * FROM conversation_turns WHERE conversation_id=? ORDER BY rowid',(cid,)).fetchall()
        return [{**dict(r),'payload':json.loads(r['payload']) if r['payload'] else None} for r in rows]

    def bind(self,task_id,cid=None):
        from app.workbench_service import local_actor
        store=self.workspace.service.store;task=store.get_task(local_actor(),task_id)
        cid=cid or task.get('conversation_id') or self.create(task.get('kb_id'),task['goal'][:60] or '服务事项')['id']
        self.get(cid)
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO conversation_tasks VALUES(?,?)',(cid,task_id))
            db.execute('UPDATE conversations SET task_id=?,kb_id=COALESCE(kb_id,?),updated_at=? WHERE id=?',
                (task_id,task.get('kb_id'),datetime.now(timezone.utc).isoformat(),cid))
        with store.transaction() as db:
            current=store._task(db,local_actor(),task_id)
            if current.get('conversation_id')!=cid:
                current['conversation_id']=cid;store._save(db,current)
        return cid

    def append(self,cid,role,kind,text,payload=None,*,turn_id=None,run_id=None,status='DONE'):
        turn_id=turn_id or uuid.uuid4().hex
        with self.db() as db:
            inserted=db.execute('INSERT OR IGNORE INTO conversation_turns(id,conversation_id,role,kind,text,payload,run_id,status) VALUES(?,?,?,?,?,?,?,?)',
                (turn_id,cid,role,kind,text,encoded(payload) if payload is not None else None,run_id,status))
            if inserted.rowcount:db.execute('UPDATE conversations SET updated_at=? WHERE id=?',(datetime.now(timezone.utc).isoformat(),cid))
        return turn_id

    async def task_turn(self,task_id,text,message_id,expected_facts_revision,detailed=False):
        from app.runtime.request_context import current_request_id
        from app.workbench_service import local_actor
        service=self.workspace.service;task=service.store.get_task(local_actor(),task_id)
        cid=self.bind(task_id)
        with self.db() as db:known=db.execute('SELECT * FROM conversation_turns WHERE id=?',(message_id,)).fetchone()
        if known:
            if known['conversation_id']!=cid or known['text']!=text:raise ServiceError('MESSAGE_ID_CONFLICT')
            if known['status']=='DONE':return service.view(task_id)
            raise ServiceError('MESSAGE_NOT_APPLIED')
        if task['facts_revision']!=expected_facts_revision:raise ServiceError('TASK_CHANGED')
        if task.get('pending_user_update'):raise ServiceError('USER_UPDATE_PENDING')
        run_id=current_request_id() or 'inline-'+message_id
        self.append(cid,'user','message',text,turn_id=message_id,run_id=run_id,status='PENDING')
        with service.store.transaction() as db:
            current=service.store._task(db,local_actor(),task_id)
            current['pending_user_update']=message_id
            service.store._save(db,current)
            db.execute('INSERT INTO workbench_messages VALUES(?,?,?,?,?)',(message_id,task_id,text,'PENDING',None))
        # Pending input protects concurrent confirmation, but this run is its consumer.
        turn={'id':message_id,'text':text,'conversation_id':cid,'detailed':detailed}
        from app.agent_runtime.workbench_agent import build_service_agent
        terminal='failed'
        try:
            result=await build_service_agent(service).run(task_id,run_id,turn=turn)
            with service.store.transaction() as db:
                current=service.store._task(db,local_actor(),task_id)
                if current.get('pending_user_update')==message_id:current.pop('pending_user_update')
                service.store._save(db,current)
                db.execute("UPDATE workbench_messages SET status='APPLIED',result=? WHERE id=?",(encoded({'conversation_id':cid}),message_id))
            service.workspace.runs.lifecycle.finish(run_id,'turn',{},'succeeded',None)
            result=service.view(task_id)
            self.append(cid,'assistant','result',result.get('assistant_text') or result.get('question') or result['next_step'],
                        {'task_id':task_id,'knowledge':result.get('knowledge_result'),'preview':result.get('preview'),
                         'receipt':result.get('receipt'),'facts':result['facts']},run_id=run_id)
            with self.db() as db:db.execute("UPDATE conversation_turns SET status='DONE' WHERE id=?",(message_id,))
            terminal='succeeded'
            return result
        except BaseException:
            import asyncio
            import sys
            cancelled=isinstance(sys.exception(),asyncio.CancelledError)
            terminal='cancelled' if cancelled else 'failed'
            if cancelled:service.message_cancelled(task_id,message_id)
            else:service.message_failed(task_id,message_id,'Turn failed; raw input retained')
            with self.db() as db:db.execute('UPDATE conversation_turns SET status=? WHERE id=?',('CANCELLED' if cancelled else 'FAILED',message_id))
            raise
        finally:
            service.workspace.runs.lifecycle.finish(run_id,'turn',{},terminal,None)

    def _done(self,message_id):
        with self.db() as db:row=db.execute('SELECT status FROM conversation_turns WHERE id=?',(message_id,)).fetchone()
        return bool(row and row['status']=='DONE')

    async def turn(self,conversation_id,text,message_id,detailed=False):
        conversation=self.get(conversation_id)
        with self.db() as db:known=db.execute('SELECT * FROM conversation_turns WHERE id=?',(message_id,)).fetchone()
        if known:
            if known['conversation_id']!=conversation_id or known['text']!=text:raise ServiceError('MESSAGE_ID_CONFLICT')
            if known['status']=='DONE' and known['payload']:return json.loads(known['payload'])
            raise ServiceError('MESSAGE_NOT_APPLIED')
        if conversation['task_id']:
            task=self.workspace.service.view(conversation['task_id'])
            return await self.task_turn(task['task_id'],text,message_id,task['facts_revision'],detailed=detailed)
        if not conversation['kb_id']:raise ServiceError('KNOWLEDGE_BASE_REQUIRED')
        self.append(conversation_id,'user','message',text,turn_id=message_id,status='PENDING')
        answer=await self.workspace.library.answer(conversation['kb_id'],text,conversation_id=conversation_id,detailed=detailed)
        self.append(conversation_id,'assistant','knowledge',answer['result']['answer'],answer)
        with self.db() as db:db.execute("UPDATE conversation_turns SET status='DONE',payload=? WHERE id=?",(encoded(answer),message_id))
        return answer
