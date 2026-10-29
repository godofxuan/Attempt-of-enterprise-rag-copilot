"""Program tests of the actual transactional lifecycle, not live Agent scores."""
from datetime import timedelta
import pytest

from tests.vnext.test_bootstrap import client_for
from app.workspace import initialize
from app.workbench_service import local_actor
from app.service_desk.store import ServiceError


def create(service,ceiling='SUBMIT_AFTER_CONFIRMATION'):
    today=service.store.today()
    return service.create({'kind':'loan','execution_ceiling':ceiling,'confirmed':True,
        'facts':{'loan_start':str(today+timedelta(days=1)),'loan_end':str(today+timedelta(days=3)),'purpose':'现场测试'}})


def preview(service,task):
    actor=local_actor();store=service.store;task_id=task['task_id']
    evidence=service.policy(task_id)
    store.observe(actor,task_id,'assets.search',{'status':'ok','data':store.assets(actor)})
    store.observe(actor,task_id,'tickets.list_mine',{'status':'ok','data':{'tickets':store.list_tickets(actor)}})
    return store.propose(actor,task_id,'loan-laptop-1',[evidence['ref']])


def test_revision_conflict_clear_and_multiple_preview_revisions(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service)
        first=preview(service,task)
        assert preview(service,task)['proposal_id']==first['proposal_id']
        stale_revision=task['facts_revision']
        task=service.facts(task['task_id'],{'purpose':None},stale_revision)
        assert 'purpose' not in task['facts'] and not task['preview']
        with pytest.raises(ServiceError,match='TASK_CHANGED'):
            service.facts(task['task_id'],{'purpose':'stale'},stale_revision)
        task=service.facts(task['task_id'],{'purpose':'现场测试'},task['facts_revision'])
        for offset in range(4,10):
            task=service.facts(task['task_id'],{'loan_end':str(service.store.today()+timedelta(days=offset))},task['facts_revision'])
            current=preview(service,task)
        with pytest.raises(ServiceError,match='PROPOSAL_CHANGED'):
            service.store.confirm(local_actor(),task['task_id'],first['proposal_id'],first['content_digest'],True)
        result=service.submit(task['task_id'],{'proposal_id':current['proposal_id'],'content_digest':current['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})
        again=service.submit(task['task_id'],{'proposal_id':current['proposal_id'],'content_digest':current['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})
        assert result['receipt']==again['receipt']
        assert result['receipt']['ticket']['status']=='PENDING_APPROVAL'
        assert result['receipt']['ticket']['parameters']['loan_end']==task['facts']['loan_end']
        assert len(service.store.list_tickets(local_actor()))==1
    with client_for(tmp_path) as client:
        assert client.app.state.workspace.service.view(task['task_id'])['receipt']==result['receipt']


@pytest.mark.parametrize('ceiling',['READ_ONLY','PREVIEW_ONLY'])
def test_narrow_scope_cannot_submit_or_be_upgraded_by_fact_updates(tmp_path,ceiling):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service,ceiling)
        task=service.facts(task['task_id'],{'purpose':'补充用途'},task['facts_revision'])
        if ceiling=='READ_ONLY':
            with pytest.raises(ServiceError,match='EXECUTION_CEILING'):preview(service,task)
        else:
            proposal=preview(service,task)
            with pytest.raises(ServiceError,match='EXECUTION_CEILING'):
                service.store.confirm(local_actor(),task['task_id'],proposal['proposal_id'],proposal['content_digest'],True)
        assert service.view(task['task_id'])['user_execution_ceiling']==ceiling
        assert not service.store.list_tickets(local_actor())


def test_actual_api_rejects_stale_updates(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        headers={'X-ESA-Request':'1'}
        task=client.post('/api/tasks',headers=headers,json={'request':{'kind':'loan','execution_ceiling':'READ_ONLY','confirmed':True}}).json()
        url='/api/tasks/'+task['task_id']+'/facts'
        assert client.patch(url,headers=headers,json={'changes':{'purpose':'new'},'expected_facts_revision':1}).status_code==200
        stale=client.patch(url,headers=headers,json={'changes':{'purpose':'old'},'expected_facts_revision':1})
        assert stale.status_code==409 and stale.json()['error']['code']=='TASK_CHANGED'
        assert stale.json()['error']['data']['current_facts']['purpose']=='new'


def test_missing_prefill_origin_is_rejected_before_creating_a_task(tmp_path):
    with client_for(tmp_path) as client:
        response=client.post('/api/tasks',headers={'X-ESA-Request':'1'},json={
            'request':{'kind':'loan','execution_ceiling':'READ_ONLY','confirmed':True},'use_original_parameters':True})
        assert response.status_code==422
        assert client.get('/api/tasks').json()==[]
