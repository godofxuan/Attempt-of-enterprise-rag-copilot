"""Ordinary product paths through real service/run/store code; no model HTTP."""
import asyncio
from types import SimpleNamespace
from datetime import timedelta

from app.workspace import initialize, WorkspaceConfig
from app.workbench_service import TaskService
from app.runtime.workbench_runs import Runs


def workspace(root):
    initialize(root, sample=True)
    w = SimpleNamespace(root=root, db_path=root/'app.sqlite3', config=WorkspaceConfig(sample_data=True))
    w.service = TaskService(w)
    w.runs = Runs(w)
    return w


class AskModel:
    async def chat(self, *args, **kwargs):
        return {'content':'', 'tool_calls':[{'function':{'name':'ask_user','arguments':{}}}]}


def test_empty_repair_asks_from_the_same_service_field_schema(tmp_path):
    async def check():
        w=workspace(tmp_path);w.models=AskModel()
        task=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True})
        run=w.runs.start('service',{'task_id':task['task_id']});await w.runs.tasks[run['id']]
        done=w.runs.get(run['id']);view=w.service.view(task['task_id'])
        assert done['status']=='succeeded',done['error']
        assert view['status']=='WAITING_USER' and not view['active_run_id']
        from app.service_desk.catalog import REPAIR
        assert set(view['missing_fields'])=={name for name,_,_ in REPAIR.fields}
        assert all(label in view['question'] for _,label,_ in REPAIR.fields)
        await w.runs.close()
    asyncio.run(check())


def test_cancel_message_keeps_raw_input_but_releases_pending_gate(tmp_path):
    class WaitingModel:
        def __init__(self):self.entered=asyncio.Event()
        async def chat(self,*args,**kwargs):self.entered.set();await asyncio.Event().wait()
    async def check():
        w=workspace(tmp_path);w.models=WaitingModel()
        task=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True})
        run=w.runs.start('message',{'task_id':task['task_id'],'text':'屏幕闪烁','message_id':'cancelled-message','expected_facts_revision':task['facts_revision']})
        handle=w.runs.tasks[run['id']];await asyncio.wait_for(w.models.entered.wait(),5)
        w.runs.cancel(run['id']);await handle
        view=w.service.view(task['task_id'])
        assert not view['pending_update'] and view['facts']=={}
        with w.service.store.transaction() as db:
            row=db.execute("SELECT text,status FROM workbench_messages WHERE id='cancelled-message'").fetchone()
        assert row['text']=='屏幕闪烁' and row['status']=='CANCELLED'
        await w.runs.close()
    asyncio.run(check())


def test_lifecycle_does_not_clear_a_newer_task_owner(tmp_path):
    w=workspace(tmp_path)
    task=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True})
    from app.workbench_service import local_actor
    started=w.service.store.begin_run(local_actor(),task['task_id'])
    w.runs.lifecycle.own_task('old-run',started)
    with w.service.store.transaction() as db:
        current=w.service.store._task(db,local_actor(),task['task_id'])
        current.update(active_run_id='new-owner',run_fence=current['run_fence']+1)
        w.service.store._save(db,current)
    w.runs.lifecycle.finish('old-run','service',{'task_id':task['task_id']},'cancelled',None)
    assert w.service.view(task['task_id'])['active_run_id']=='new-owner'


def test_knowledge_message_is_a_followup_not_a_pending_facts_update(tmp_path):
    async def check():
        w=workspace(tmp_path);calls=[]
        async def answer(kb_id, question, **kwargs):
            calls.append((kb_id,question,kwargs))
            return {'id':'test-saved-result','conversation_id':'test-conversation','result':{'mode':'partial','answer':'测试来源不足','sources':[]}}
        w.library=SimpleNamespace(answer=answer)
        class KnowledgeModel:
            def __init__(self):self.n=0
            async def chat(self,*args,**kwargs):
                self.n+=1
                return {'content':'','tool_calls':[{'function':{'name':'knowledge_answer' if self.n==1 else 'finish',
                    'arguments':{'question':'为什么有这个期限？'} if self.n==1 else {}}}]}
        w.models=KnowledgeModel()
        task=w.service.create({'kind':'knowledge','question':'电脑最长借多久？','execution_ceiling':'READ_ONLY','confirmed':True},kb_id='selected-kb')
        run=w.runs.start('message',{'task_id':task['task_id'],'text':'为什么有这个期限？','message_id':'followup-1','expected_facts_revision':task['facts_revision']})
        await w.runs.tasks[run['id']]
        done=w.runs.get(run['id']);view=w.service.view(task['task_id'])
        assert done['status']=='succeeded',done['error']
        assert calls and calls[0][0]=='selected-kb' and '为什么有这个期限' in calls[0][1]
        assert view['facts']=={} and not view['pending_update']
        assert view['knowledge_result']['id']=='test-saved-result'
        await w.runs.close()
    asyncio.run(check())


def test_cancel_run_releases_only_its_task_and_can_continue_without_restart(tmp_path):
    class WaitingModel:
        def __init__(self):self.entered=asyncio.Event()
        async def chat(self,*args,**kwargs):
            self.entered.set();await asyncio.Event().wait()
    async def check():
        w=workspace(tmp_path);w.models=WaitingModel();today=w.service.store.today()
        task=w.service.create({'kind':'loan','execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','confirmed':True,
            'facts':{'loan_start':str(today+timedelta(days=1)),'loan_end':str(today+timedelta(days=2)),'purpose':'生命周期测试'}})
        run=w.runs.start('service',{'task_id':task['task_id']});handle=w.runs.tasks[run['id']]
        await asyncio.wait_for(w.models.entered.wait(),5)
        w.runs.cancel(run['id']);await handle
        view=w.service.view(task['task_id'])
        assert w.runs.get(run['id'])['status']=='cancelled'
        assert not view['active_run_id'] and view['status']!='RUNNING'
        assert view['facts']==task['facts'] and not view['receipt']
        w.models=AskModel();retry=w.runs.start('service',{'task_id':task['task_id']});await w.runs.tasks[retry['id']]
        assert w.runs.get(retry['id'])['status']=='succeeded'
        await w.runs.close()
    asyncio.run(check())
