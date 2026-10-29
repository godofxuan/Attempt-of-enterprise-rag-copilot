"""Actual shared transaction/API paths, explicitly program tests rather than LLM runs."""
import pytest
from app.workspace import initialize
from app.workbench_service import local_actor
from app.service_desk.store import ServiceError
from tests.vnext.test_bootstrap import client_for


def create(service,ceiling='SUBMIT_AFTER_CONFIRMATION'):
    return service.create({'kind':'repair','execution_ceiling':ceiling,'confirmed':True,
        'facts':{'asset_id':'employee-laptop-1','description':'屏幕间歇闪烁','impact':'medium'}})


def preview(service,task):
    who=local_actor();identifier=task['task_id'];evidence=service.policy(identifier)
    service.store.observe(who,identifier,'assets.search',{'status':'ok','data':service.assets(identifier)})
    service.store.observe(who,identifier,'tickets.list_mine',{'status':'ok','data':{'tickets':service.tickets(identifier)}})
    return service.store.propose(who,identifier,task['facts']['asset_id'],[evidence['ref']])


def test_repair_shares_exact_confirmation_commit_and_reload_without_loan_side_effects(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service);old=preview(service,task)
        task=service.facts(task['task_id'],{'impact':'high'},task['facts_revision'])
        with pytest.raises(ServiceError,match='PROPOSAL_CHANGED'):
            service.store.confirm(local_actor(),task['task_id'],old['proposal_id'],old['content_digest'],True)
        current=preview(service,task)
        with pytest.raises(ServiceError,match='CONFIRMATION_REQUIRED'):
            service.store.submit(local_actor(),task['task_id'],current['proposal_id'])
        payload={'proposal_id':current['proposal_id'],'content_digest':current['content_digest'],
                 'expected_facts_revision':task['facts_revision'],'accepted':True}
        result=service.submit(task['task_id'],payload);again=service.submit(task['task_id'],payload)
        assert result['receipt']==again['receipt'] and result['status']=='COMPLETED'
        assert result['receipt']['ticket']['status']=='OPEN'
        assert result['receipt']['ticket']['parameters']['impact']=='high'
        assert not service.store.list_tickets(local_actor())
        with service.store.transaction() as db:
            assert db.execute('SELECT COUNT(*) FROM it_repair_tickets').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]==0
            assert tuple(db.execute('SELECT active,version FROM repairs').fetchone())==(1,1)
            assert db.execute("SELECT COUNT(*) FROM command_ledger WHERE command_id LIKE 'repair:%'").fetchone()[0]==1
        identifier=task['task_id'];receipt=result['receipt']
        with pytest.raises(ServiceError,match='ALREADY_SUBMITTED'):service.store.cancel_task(local_actor(),identifier)
    with client_for(tmp_path) as client:
        assert client.app.state.workspace.service.view(identifier)['receipt']==receipt


def test_repair_response_loss_recovers_same_commit_and_does_not_accept_new_scope(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service);proposal=preview(service,task);who=local_actor()
        service.store.confirm(who,task['task_id'],proposal['proposal_id'],proposal['content_digest'],True)
        def disconnect(phase):
            if phase=='after_commit':raise ConnectionError('Synthetic lost response')
        with pytest.raises(ConnectionError):service.store.submit(who,task['task_id'],proposal['proposal_id'],fault=disconnect)
        with pytest.raises(ServiceError,match='TASK_BUSY_OR_COMMITTED'):
            service.store.change_execution_scope(who,task['task_id'],'READ_ONLY',[],'scope-edit','只读',scope_confirmed=True)
        recovered=service.submit(task['task_id'],{'proposal_id':proposal['proposal_id'],'content_digest':proposal['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})
        assert recovered['receipt']['ticket']['status']=='OPEN'
        assert len(service.store.list_tickets(who,kind='repair'))==1


@pytest.mark.parametrize('ceiling',['READ_ONLY','PREVIEW_ONLY'])
def test_repair_scope_and_actual_readonly_completion(tmp_path,ceiling):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service,ceiling)
        if ceiling=='READ_ONLY':
            with pytest.raises(ServiceError,match='EXECUTION_CEILING'):preview(service,task)
            assert service.store.finish_goal(local_actor(),task['task_id'])['goal_satisfied']
        else:
            proposal=preview(service,task)
            with pytest.raises(ServiceError,match='EXECUTION_CEILING'):
                service.store.confirm(local_actor(),task['task_id'],proposal['proposal_id'],proposal['content_digest'],True)
        assert not service.store.list_tickets(local_actor(),kind='repair')


def test_repair_resource_change_and_existing_ticket_are_real_business_branches(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service);proposal=preview(service,task)
        with service.store.transaction() as db:db.execute('UPDATE it_assets SET version=2')
        with pytest.raises(ServiceError,match='RESOURCE_CHANGED'):
            service.store.confirm(local_actor(),task['task_id'],proposal['proposal_id'],proposal['content_digest'],True)
        proposal=preview(service,task)
        service.submit(task['task_id'],{'proposal_id':proposal['proposal_id'],'content_digest':proposal['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})
        other=create(service)
        with pytest.raises(ServiceError,match='EXISTING_TICKET'):preview(service,other)
        owned=service.tickets(other['task_id']);assert len(owned)==1
        service.store.observe(local_actor(),other['task_id'],'tickets.get',{'status':'ok','data':service.ticket(other['task_id'],owned[0]['ticket_id'])})
        assert service.store.finish_goal(local_actor(),other['task_id'])['goal_satisfied']
        with service.store.transaction() as db:assert db.execute('SELECT COUNT(*) FROM it_repair_tickets').fetchone()[0]==1


def test_repair_api_rejects_cross_domain_fields_and_nonowned_asset(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        headers={'X-ESA-Request':'1'}
        data=client.post('/api/tasks',headers=headers,json={'request':{'kind':'repair','execution_ceiling':'READ_ONLY','confirmed':True}}).json()
        response=client.patch('/api/tasks/'+data['task_id']+'/facts',headers=headers,json={'expected_facts_revision':1,'changes':{'loan_end':'2030-01-01'}})
        assert response.status_code==422
        response=client.post('/api/tasks/'+data['task_id']+'/asset',headers=headers,json={'expected_facts_revision':1,'asset_id':'someone-else'})
        assert response.status_code==409 and response.json()['error']['code']=='NOT_OWNED_ASSET'
        catalog=client.get('/api/services').json();assert {s['key'] for s in catalog}=={'loan','repair'}


def test_field_dependencies_retain_reads_but_recheck_actual_resources(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        service=client.app.state.workspace.service;task=create(service);preview(service,task)
        current=service.facts(task['task_id'],{'impact':'high'},task['facts_revision'])
        assert {'assets_search','tickets_list_mine','repair_policy'}<=set(service.valid_observations(current))
        with service.store.transaction() as db:db.execute('UPDATE it_assets SET active=0')
        assert 'assets_search' not in service.valid_observations(service.store.get_task(local_actor(),task['task_id']))
        from tests.vnext.test_service_lifecycle import create as loan_task,preview as loan_preview
        loan=loan_task(service);loan_preview(service,loan)
        from datetime import timedelta
        changed=service.facts(loan['task_id'],{'loan_end':str(service.store.today()+timedelta(days=4))},loan['facts_revision'])
        cache=service.valid_observations(changed)
        assert 'assets_search' not in cache and {'tickets_list_mine','loan_policy'}<=set(cache)
