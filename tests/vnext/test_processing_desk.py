"""Actual SQLite processing lifecycle and schedule conflicts; no model scores."""
from datetime import timedelta
import pytest
from tests.vnext.test_bootstrap import client_for
from tests.vnext.test_service_lifecycle import create,preview
from app.workspace import initialize
from app.workbench_service import local_actor
from app.service_desk.lifecycle import Lifecycle
from app.service_desk.store import ServiceError

def submitted(service):
    task=create(service);p=preview(service,task)
    return service.submit(task['task_id'],{'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],
        'expected_facts_revision':task['facts_revision'],'accepted':True})

def action(desk,ticket,name,**kwargs):
    p=desk.propose(local_actor(),'loan',ticket['ticket_id'],name,ticket['version'],note='本地TEST用户明确操作',**kwargs)
    result=desk.commit(local_actor(),p['proposal_id'],p['content_digest'],True)
    assert desk.commit(local_actor(),p['proposal_id'],p['content_digest'],True)==result
    return result['ticket']

def test_same_database_full_loan_return_and_apply_again(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as c:
        s=c.app.state.workspace.service;desk=Lifecycle(s.store);task=submitted(s);original=task['receipt']
        ticket=original['ticket'];assert not desk.list(local_actor())['reservations']
        ticket=action(desk,ticket,'approve');assert ticket['status']=='RESERVED'
        assert desk.list(local_actor())['reservations'][0]['active']==1
        assert not any(a['asset_id']==ticket['asset_id'] for a in s.store.assets(local_actor(),ticket['parameters'])['assets'])
        ticket=action(desk,ticket,'checkout')
        ticket=action(desk,ticket,'extend',loan_end=str(s.store.today()+timedelta(days=5)))
        assert s.view(task['task_id'])['current_ticket']==ticket
        assert s.view(task['task_id'])['receipt']==original
        assert s.submit(task['task_id'],{'proposal_id':original['proposal_id'],'content_digest':original['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})['receipt']==original
        ticket=action(desk,ticket,'return');assert ticket['status']=='RETURNED'
        assert desk.list(local_actor())['reservations'][0]['active']==0
        second=submitted(s);assert second['receipt']['ticket_id']!=ticket['ticket_id']
        assert len(s.store.list_tickets(local_actor()))==2

def test_processing_confirmation_version_conflict_and_no_partial_write(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as c:
        s=c.app.state.workspace.service;desk=Lifecycle(s.store);ticket=submitted(s)['receipt']['ticket']
        first=desk.propose(local_actor(),'loan',ticket['ticket_id'],'approve',1,note='批准预览')
        stale=desk.propose(local_actor(),'loan',ticket['ticket_id'],'reject',1,note='另一页面预览')
        with pytest.raises(ServiceError,match='CONFIRMATION_REQUIRED'):desk.commit(local_actor(),first['proposal_id'],first['content_digest'],False)
        desk.commit(local_actor(),first['proposal_id'],first['content_digest'],True)
        with pytest.raises(ServiceError,match='TICKET_CHANGED'):desk.commit(local_actor(),stale['proposal_id'],stale['content_digest'],True)
        actor=local_actor().model_copy(update={'subject':'another-test-user'})
        with pytest.raises(ServiceError,match='AUTH_DENIED'):desk.commit(actor,first['proposal_id'],first['content_digest'],True)
        with s.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM command_ledger WHERE command_id LIKE 'lifecycle:%'").fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM asset_reservations WHERE active=1').fetchone()[0]==1

def test_overlapping_approval_is_atomic_and_adjacent_day_is_available(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as c:
        s=c.app.state.workspace.service;desk=Lifecycle(s.store);ticket=submitted(s)['receipt']['ticket']
        from app.service_desk.scheduling import available
        with s.store.transaction() as db:
            from app.service_desk.scheduling import interval
            start,end=interval(ticket['parameters'])
            db.execute('INSERT INTO asset_reservations VALUES(?,?,?,?,?,1)',('another-test-ticket','local',ticket['asset_id'],start,end))
        with pytest.raises(ServiceError,match='SCHEDULE_CONFLICT'):desk.propose(local_actor(),'loan',ticket['ticket_id'],'approve',1,note='冲突不能批准')
        with s.store.transaction() as db:
            assert available(db,'local',ticket['asset_id'],{'loan_start':end,'loan_end':end})
            assert db.execute('SELECT status FROM tickets WHERE ticket_id=?',(ticket['ticket_id'],)).fetchone()[0]=='PENDING_APPROVAL'

def test_repair_real_api_lifecycle_does_not_mutate_loan_eligibility(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as c:
        s=c.app.state.workspace.service;actor=local_actor();headers={'X-ESA-Request':'1'}
        task=s.create({'kind':'repair','execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','confirmed':True,
            'facts':{'asset_id':'employee-laptop-1','description':'屏幕闪烁','impact':'high'}})
        e=s.policy(task['task_id']);s.store.observe(actor,task['task_id'],'tickets.list_mine',{'status':'ok','data':{'tickets':[]}})
        p=s.store.propose(actor,task['task_id'],'employee-laptop-1',[e['ref']])
        ticket=s.submit(task['task_id'],{'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],
            'expected_facts_revision':task['facts_revision'],'accepted':True})['receipt']['ticket']
        before=s.store.assets(actor)['repair']
        for name,state in [('start','IN_PROGRESS'),('resolve','RESOLVED'),('close','CLOSED'),('reopen','OPEN')]:
            r=c.post('/api/service-desk/proposals',headers=headers,json={'kind':'repair','ticket_id':ticket['ticket_id'],
                'action':name,'expected_version':ticket['version'],'note':'TEST 操作说明'})
            assert r.status_code==200,r.text
            p=r.json();r=c.post('/api/service-desk/commit',headers=headers,json={'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],'accepted':True})
            assert r.status_code==200,r.text
            ticket=r.json()['ticket'];assert ticket['status']==state
        assert s.store.assets(actor)['repair']==before
        assert c.get('/api/service-desk').json()['origin']=='LOCAL_SYNTHETIC_TEST_ONLY'

def test_preferences_and_date_candidates_are_actual_and_require_explicit_choice(tmp_path):
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as c:
        s=c.app.state.workspace.service;task=create(s);day=task['facts']['loan_start']
        task=s.facts(task['task_id'],{'loan_end':day,'min_memory_gb':16,'pickup_location':'B区服务台'},task['facts_revision'])
        with s.store.transaction() as db:
            from app.service_desk.scheduling import interval
            start,end=interval(task['facts'])
            db.execute('INSERT INTO asset_reservations VALUES(?,?,?,?,?,1)',('busy-local-test','local','loan-laptop-2',start,end))
        assert s.alternatives(task['task_id'])==[]
        task=s.facts(task['task_id'],{'date_flex_days':1},task['facts_revision'])
        choices=s.alternatives(task['task_id']);assert choices and choices[0]['date_shift_days']==1
        assert choices[0]['asset_id']=='loan-laptop-2' and choices[0]['details']['memory_gb']>=16
        assert s.view(task['task_id'])['facts']['loan_start']==day
        task=s.choose_asset(task['task_id'],choices[0]['asset_id'],task['facts_revision'],1)
        assert task['facts']['loan_start']==choices[0]['parameters']['loan_start']
        with pytest.raises(ServiceError,match='DATE_CHANGE_NOT_AUTHORIZED'):s.choose_asset(task['task_id'],'loan-laptop-2',task['facts_revision'],2)
