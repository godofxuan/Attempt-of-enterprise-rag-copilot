"""Conversation routing with scripted choices through actual tools/store/SQLite."""
import asyncio
from types import SimpleNamespace
from datetime import timedelta
import pytest

from tests.vnext.test_upgrade_paths import workspace
from app.workbench_service import local_actor
from app.service_desk.store import ServiceError
from app.conversations import ConversationService


class SequenceModel:
    def __init__(self,*batches):self.batches=list(batches);self.calls=[]
    async def chat(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        batch=self.batches.pop(0)
        return {'content':'当前回合已处理','tool_calls':[{'function':{'name':name,'arguments':arguments}} for name,arguments in batch]}


def test_one_turn_normalizes_date_and_queries_policy_without_expanding_scope(tmp_path):
    async def check():
        w=workspace(tmp_path);w.conversations=ConversationService(w);today=w.service.store.today()
        task=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True,
            'facts':{'loan_start':str(today+timedelta(days=1)),'loan_end':str(today+timedelta(days=2)),'purpose':'本来用途'}},kb_id='explicit-kb')
        changed=str(today+timedelta(days=4));calls=[]
        async def answer(kb_id,question,**kwargs):
            calls.append((kb_id,question));return {'id':'synthetic-saved-knowledge','conversation_id':'knowledge-cid',
                'result':{'mode':'partial','answer':'夹具：当前资料未规定押金','sources':[]}}
        w.library=SimpleNamespace(answer=answer)
        w.models=SequenceModel([('update_parameters',{'changes':{'loan_end':changed}}),('knowledge_answer',{'question':'是否需要押金？'})],[('finish',{})])
        text='结束日期延后两天，再告诉我是不是要交押金？'
        result=await w.service.message(task['task_id'],text,'mixed-turn',task['facts_revision'])
        assert result['facts']['loan_end']==changed and result['facts']['purpose']=='本来用途'
        assert result['user_execution_ceiling']=='PREVIEW_ONLY' and calls==[('explicit-kb','是否需要押金？')]
        assert result['knowledge_result']['result']['answer']=='夹具：当前资料未规定押金'
        assert not result['pending_update'] and not result['active_run_id']
        request=w.models.calls[0][0][0]
        assert [r['role'] for r in request]==['system','user']
        assert request[1]['content']==text and text not in request[0]['content']
        timeline=w.conversations.get(result['conversation_id'])['turns']
        assert [r['role'] for r in timeline]==['user','assistant'] and timeline[0]['text']==text
        again=await w.service.message(task['task_id'],text,'mixed-turn',task['facts_revision'])
        assert again['facts']==result['facts'] and len(w.models.calls)==2
        with w.service.store.transaction() as db:assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==0
        await w.runs.close()
    asyncio.run(check())


def test_why_is_not_a_field_and_unknown_permission_tool_is_rejected(tmp_path):
    async def check():
        w=workspace(tmp_path);w.conversations=ConversationService(w)
        task=w.service.create({'kind':'repair','execution_ceiling':'READ_ONLY','confirmed':True})
        w.models=SequenceModel([('finish',{})])
        result=await w.service.message(task['task_id'],'为什么需要设备编号？','why',task['facts_revision'])
        assert result['facts']=={} and result['user_execution_ceiling']=='READ_ONLY'
        w.models=SequenceModel([('set_execution_ceiling',{'value':'SUBMIT_AFTER_CONFIRMATION'})])
        with pytest.raises(ServiceError,match='INVALID_TOOL_ARGUMENTS'):
            await w.service.message(task['task_id'],'继续','no-permission-tool',result['facts_revision'])
        latest=w.service.view(task['task_id'])
        assert latest['user_execution_ceiling']=='READ_ONLY' and not latest['receipt']
        await w.runs.close()
    asyncio.run(check())


def test_submission_does_not_end_conversation_or_rewrite_original_receipt(tmp_path):
    from tests.vnext.test_service_lifecycle import create,preview
    async def check():
        w=workspace(tmp_path);w.conversations=ConversationService(w)
        task=create(w.service);p=preview(w.service,task)
        submitted=w.service.submit(task['task_id'],{'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})
        original=submitted['receipt']
        w.models=SequenceModel([('tickets_list_mine',{})],[('finish',{})])
        result=await w.service.message(task['task_id'],'申请现在什么状态？','after-submit',submitted['facts_revision'])
        assert result['receipt']==original
        tools=w.models.calls[0][1]['tools'];names={t['function']['name'] for t in tools}
        assert 'prepare_preview' not in names and 'update_parameters' not in names
        context=w.models.calls[0][0][0][0]['content']
        assert 'PENDING_APPROVAL' in context
        with w.service.store.transaction() as db:assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==1
        await w.runs.close()
    asyncio.run(check())

def test_unexecuted_prose_gets_one_protocol_observation_and_same_runner_continues(tmp_path):
    from tests.vnext.test_service_lifecycle import create
    async def check():
        w=workspace(tmp_path);w.conversations=ConversationService(w);task=create(w.service)
        w.models=SequenceModel([('loan_policy',{}),('assets_search',{}),('tickets_list_mine',{})],
            [],[('prepare_preview',{'asset_id':'loan-laptop-1'})])
        run=w.runs.start('service',{'task_id':task['task_id']});await w.runs.tasks[run['id']]
        result=w.service.view(task['task_id'])
        assert result['preview'] and not result['receipt'] and len(w.models.calls)==3
        assert any(e['kind']=='protocol_feedback' for e in result['events'])
        request=w.models.calls[-1][0][0]
        assert any(m.get('role')=='system' and 'MODEL_ACTION_REQUIRED' in m['content'] for m in request)
        with w.service.store.transaction() as db:assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==0
        await w.runs.close()
    asyncio.run(check())

def test_prepare_in_user_turn_consumes_typed_fields_through_same_update_path(tmp_path):
    async def check():
        w=workspace(tmp_path);w.conversations=ConversationService(w)
        task=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True})
        fields={'asset_id':'employee-laptop-1','description':'程序测试故障描述','impact':'high'}
        w.models=SequenceModel([('repair_policy',{}),('assets_search',{}),('tickets_list_mine',{})],
            [('prepare_preview',{'asset_id':'employee-laptop-1','parameters':{k:v for k,v in fields.items() if k!='asset_id'}})],[('finish',{})])
        result=await w.service.message(task['task_id'],'本回合提供设备、描述和高影响，请准备预览','typed-preview-turn',task['facts_revision'])
        assert result['facts']==fields and result['preview']['content']['parameters']==fields
        assert result['preview']['content']['execution_ceiling']=='PREVIEW_ONLY' and not result['receipt']
        assert all(result['fact_sources'][key]['source_message_id']=='typed-preview-turn' for key in fields)
        assert result['fact_sources']['asset_id']['origin']=='MODEL_TOOL_TARGET_VALIDATED_OWNED_RESOURCE'
        with pytest.raises(ServiceError,match='EXECUTION_CEILING'):
            w.service.store.confirm(local_actor(),task['task_id'],result['preview']['proposal_id'],result['preview']['content_digest'],True)
        await w.runs.close()
    asyncio.run(check())
