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
            return {'content':json.dumps({'updates':[{'field':'purpose','value':'出差测试','quote':'出差测试'}],
                                          'execution_ceiling':None,'scope_quote':''})}
        workspace.models.chat=model
        result=asyncio.run(service.message(task['task_id'],'用途改为出差测试，其余保持','message-1',task['facts_revision']))
        assert result['facts']['purpose']=='出差测试'
        assert result['facts']['loan_start']==task['facts']['loan_start']
        assert result['user_execution_ceiling']=='PREVIEW_ONLY'
        again=asyncio.run(service.message(task['task_id'],'用途改为出差测试，其余保持','message-1',task['facts_revision']))
        assert again['facts']==result['facts'] and len(calls)==1
        proposal=preview(service,result)
        with pytest.raises(ServiceError,match='EXECUTION_CEILING'):
            service.submit(task['task_id'],{'proposal_id':proposal['proposal_id'],'content_digest':proposal['content_digest'],
                'expected_facts_revision':result['facts_revision'],'accepted':True})


def test_model_cannot_raise_scope_or_write_unquoted_parameters(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace;service=workspace.service;task=create(service,'READ_ONLY')
        async def upgrade(*args,**kwargs):return {'content':json.dumps({'updates':[],
            'execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','scope_quote':'继续'})}
        workspace.models.chat=upgrade
        with pytest.raises(ServiceError,match='SCOPE_CHANGE_REQUIRES_USER_FORM'):
            asyncio.run(service.message(task['task_id'],'继续','scope-1',task['facts_revision']))
        async def invent(*args,**kwargs):return {'content':json.dumps({'updates':[{'field':'purpose','value':'编造值','quote':'不存在的文字'}],
            'execution_ceiling':None,'scope_quote':''})}
        workspace.models.chat=invent
        with pytest.raises(ServiceError,match='UNBOUND_PARAMETER_UPDATE'):
            asyncio.run(service.message(task['task_id'],'继续','scope-2',task['facts_revision']))
        assert service.view(task['task_id'])['facts']==task['facts']
