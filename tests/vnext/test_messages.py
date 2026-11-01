"""Explicit model doubles for the shared natural-update and scope boundary."""
import asyncio
import json
import pytest

from app.workspace import initialize
from app.service_desk.store import ServiceError
from tests.vnext.test_bootstrap import client_for
from tests.vnext.test_service_lifecycle import create,preview


def test_message_preserves_ban_and_unmentioned_fields_and_is_idempotent(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace;service=workspace.service;task=create(service,'PREVIEW_ONLY')
        calls=[]
        async def model(*args,**kwargs):
            calls.append(args)
            return {'content':'', 'tool_calls':[{'function':{'name':'update_parameters' if len(calls)==1 else 'finish',
                'arguments':{'changes':{'purpose':'出差测试'}} if len(calls)==1 else {}}}]}
        workspace.models.chat=model
        result=asyncio.run(service.message(task['task_id'],'用途改为出差测试，其余保持','message-1',task['facts_revision']))
        assert result['facts']['purpose']=='出差测试'
        assert result['facts']['loan_start']==task['facts']['loan_start']
        assert result['user_execution_ceiling']=='PREVIEW_ONLY'
        again=asyncio.run(service.message(task['task_id'],'用途改为出差测试，其余保持','message-1',task['facts_revision']))
        assert again['facts']==result['facts'] and len(calls)==2
        proposal=preview(service,result)
        with pytest.raises(ServiceError,match='EXECUTION_CEILING'):
            service.submit(task['task_id'],{'proposal_id':proposal['proposal_id'],'content_digest':proposal['content_digest'],
                'expected_facts_revision':result['facts_revision'],'accepted':True})


def test_model_cannot_raise_scope_or_write_out_of_domain_fields(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace;service=workspace.service;task=create(service,'READ_ONLY')
        async def upgrade(*args,**kwargs):return {'content':'','tool_calls':[{'function':{
            'name':'set_execution_ceiling','arguments':{'value':'SUBMIT_AFTER_CONFIRMATION'}}}]}
        workspace.models.chat=upgrade
        with pytest.raises(ServiceError,match='INVALID_TOOL_ARGUMENTS'):
            asyncio.run(service.message(task['task_id'],'继续','scope-1',task['facts_revision']))
        assert service.view(task['task_id'])['user_execution_ceiling']=='READ_ONLY'
        observed=[]
        async def invalid(*args,**kwargs):
            observed.append(args)
            return {'content':'','tool_calls':[{'function':{'name':'update_parameters' if len(observed)==1 else 'finish',
                'arguments':{'changes':{'impact':'high'}} if len(observed)==1 else {}}}]}
        workspace.models.chat=invalid;task=create(service,'READ_ONLY')
        result=asyncio.run(service.message(task['task_id'],'继续','scope-2',task['facts_revision']))
        assert result['facts']==task['facts']
        assert any('INVALID_PARAMETER' in str(row) for row in observed)


def test_unresolved_message_blocks_real_preview_confirmation_and_resume_until_user_resolves(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace;service=workspace.service;task=create(service)
        proposal=preview(service,task)
        async def wrong(*args,**kwargs):raise ValueError('MODEL_RESPONSE_INVALID')
        workspace.models.chat=wrong
        with pytest.raises(ValueError,match='MODEL_RESPONSE_INVALID'):
            asyncio.run(service.message(task['task_id'],'这条补充尚未理解','pending-1',task['facts_revision']))
        pending=service.view(task['task_id'])
        assert pending['pending_update']['text']=='这条补充尚未理解'
        from app.workbench_service import local_actor
        with pytest.raises(ServiceError,match='USER_UPDATE_PENDING'):
            service.store.confirm(local_actor(),task['task_id'],proposal['proposal_id'],proposal['content_digest'],True)
        with pytest.raises(ServiceError,match='USER_UPDATE_PENDING'):asyncio.run(service.run(task['task_id'],'offline-no-send'))
        with pytest.raises(ServiceError,match='EXPLICIT_SCOPE_REVIEW_REQUIRED'):
            service.resolve_update(task['task_id'],'READ_ONLY',pending['facts_revision'],False)
        resolved=service.resolve_update(task['task_id'],'READ_ONLY',pending['facts_revision'],True)
        assert not resolved['pending_update'] and not resolved['preview']
        assert resolved['user_execution_ceiling']=='READ_ONLY'
        assert not service.store.list_tickets(local_actor())


def test_restart_keeps_unprocessed_input_visible_without_new_model_calls(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service,'READ_ONLY')
        with service.store.transaction() as db:
            db.execute('INSERT INTO workbench_messages VALUES(?,?,?,?,?)',('legacy-pending',task['task_id'],'尚未成功处理的原文','PENDING',None))
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service
        restored=service.view(task['task_id'])
        assert restored['pending_update']['text']=='尚未成功处理的原文'
        assert restored['status']=='WAITING_USER'
        with service.store.transaction() as db:assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0]==0
