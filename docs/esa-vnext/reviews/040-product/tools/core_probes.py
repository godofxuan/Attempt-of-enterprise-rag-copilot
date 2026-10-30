"""Read supplied source; execute real service code only against disposable synthetic data.
No change to project source or user database. Injected model/library failures are labeled.
Usage: python core_probes.py --source PATH --out PATH
"""
import argparse, asyncio, json, platform, sqlite3, sys, tempfile, traceback
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta

p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);a=p.parse_args()
sys.path.insert(0,str(Path(a.source).resolve()))
from app.workspace import initialize, WorkspaceConfig
from app.workbench_service import TaskService,local_actor
from app.runtime.workbench_runs import Runs
from app.conversations import ConversationService
from app.service_desk.lifecycle import Lifecycle

results=[]
def wspace(root):
    initialize(root,sample=True)
    w=SimpleNamespace(root=root,db_path=root/'app.sqlite3',config=WorkspaceConfig(sample_data=True))
    w.service=TaskService(w);w.runs=Runs(w);w.conversations=ConversationService(w)
    return w

def create(w,kind='loan',cid=None):
    day=w.service.store.today()
    facts=({'loan_start':str(day+timedelta(days=1)),'loan_end':str(day+timedelta(days=3)),'purpose':'审核合成场景'} if kind=='loan' else {'asset_id':'employee-laptop-1','description':'审核合成场景：屏幕闪烁','impact':'medium'})
    return w.service.create({'kind':kind,'execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','confirmed':True,'facts':facts},kb_id='synthetic-kb',conversation_id=cid)

def propose(w,t):
    s=w.service; who=local_actor(); ev=s.policy(t['task_id'])
    s.store.observe(who,t['task_id'],'assets.search',{'status':'ok','data':s.assets(t['task_id'])})
    s.store.observe(who,t['task_id'],'tickets.list_mine',{'status':'ok','data':{'tickets':s.tickets(t['task_id'])}})
    return s.store.propose(who,t['task_id'],t['facts'].get('asset_id','loan-laptop-1'),[ev['ref']])

def submit(w,t):
    pv=propose(w,t);pay={'proposal_id':pv['proposal_id'],'content_digest':pv['content_digest'],'expected_facts_revision':w.service.view(t['task_id'])['facts_revision'],'accepted':True}
    one=w.service.submit(t['task_id'],pay);two=w.service.submit(t['task_id'],pay)
    assert one['receipt']==two['receipt']
    return one

def lifecycle(w,kind,ticket,action,**kw):
    desk=Lifecycle(w.service.store)
    pv=desk.propose(local_actor(),kind,ticket['ticket_id'],action,ticket['version'],note='合成审核执行',**kw)
    one=desk.commit(local_actor(),pv['proposal_id'],pv['content_digest'],True)
    assert desk.commit(local_actor(),pv['proposal_id'],pv['content_digest'],True)==one
    return one['ticket']

async def loan(root):
    w=wspace(root);t=create(w);t=submit(w,t);original=t['receipt'];ticket=original['ticket'];states=[ticket['status']]
    for op in ['approve','checkout','extend','return']:
        ticket=lifecycle(w,'loan',ticket,op,**({'loan_end':str(w.service.store.today()+timedelta(days=5))} if op=='extend' else {}));states.append(ticket['status'])
    assert w.service.view(t['task_id'])['receipt']==original
    second=submit(w,create(w));assert second['receipt']['ticket_id']!=original['ticket_id']
    with sqlite3.connect(w.db_path) as db:
        counts={'tickets':db.execute('SELECT count(*) FROM tickets').fetchone()[0],'active_reservations':db.execute('SELECT count(*) FROM asset_reservations WHERE active=1').fetchone()[0]}
    await w.runs.close();w2=wspace(root)
    assert w2.service.view(t['task_id'])['current_ticket']['status']=='RETURNED'
    await w2.runs.close()
    return {'result':'PASS','mode':'real domain and SQLite, no LLM','states':states,'counts':counts,'reopen_workspace_preserves_returned':True}

async def repair(root):
    w=wspace(root);t=submit(w,create(w,'repair'));ticket=t['receipt']['ticket'];states=[ticket['status']]
    for op in ['start','resolve','close','reopen','start','resolve','close']:
        ticket=lifecycle(w,'repair',ticket,op);states.append(ticket['status'])
    with sqlite3.connect(w.db_path) as db:counts={'repair_tickets':db.execute('SELECT count(*) FROM it_repair_tickets').fetchone()[0],'loan_tickets':db.execute('SELECT count(*) FROM tickets').fetchone()[0]}
    await w.runs.close();return {'result':'PASS','mode':'real domain and SQLite, no LLM','states':states,'counts':counts}

async def knowledge_failure(root):
    w=wspace(root);c=w.conversations.create('synthetic-kb','失败恢复探针')
    async def fail(*args,**kwargs):raise ConnectionError('injected model connectivity failure')
    w.library=SimpleNamespace(answer=fail)
    data={'conversation_id':c['id'],'text':'设备借用期限是什么？','message_id':'knowledge-failed'}
    run=w.runs.start('conversation',data);await w.runs.tasks[run['id']]
    state=w.runs.get(run['id']);turns=w.conversations.turns(c['id'])
    try:await w.conversations.turn(**data)
    except Exception as e:retry_error=f'{type(e).__name__}: {e}'
    else:retry_error=None
    await w.runs.close()
    reproduced=(state['status']=='failed' and turns[0]['status']=='PENDING')
    return {'result':'DEFECT_REPRODUCED' if reproduced else 'NOT_REPRODUCED','mode':'real Runs/ConversationService, injected library ConnectionError','run_status':state['status'],'user_turn_status':turns[0]['status'],'same_message_retry':retry_error}

async def knowledge_cancel(root):
    w=wspace(root);entered=asyncio.Event();c=w.conversations.create('synthetic-kb','取消恢复探针')
    async def wait(*args,**kwargs):entered.set();await asyncio.Event().wait()
    w.library=SimpleNamespace(answer=wait)
    run=w.runs.start('conversation',{'conversation_id':c['id'],'text':'制度期限是什么？','message_id':'knowledge-cancelled'})
    handle=w.runs.tasks[run['id']];await asyncio.wait_for(entered.wait(),2);w.runs.cancel(run['id']);await handle
    state=w.runs.get(run['id']);turns=w.conversations.turns(c['id']);await w.runs.close()
    return {'result':'DEFECT_REPRODUCED' if state['status']=='cancelled' and turns[0]['status']=='PENDING' else 'NOT_REPRODUCED','mode':'real cancellation, injected pending library task','run_status':state['status'],'user_turn_status':turns[0]['status']}

async def cancelled_task_chat(root):
    w=wspace(root);c=w.conversations.create('synthetic-kb','取消事项后继续问资料');t=create(w,cid=c['id']);w.service.store.cancel_task(local_actor(),t['task_id'])
    calls=[]
    async def answer(*args,**kwargs):calls.append('knowledge');return {'result':{'answer':'合成答案'},'id':'a'}
    w.library=SimpleNamespace(answer=answer)
    try:await w.conversations.turn(c['id'],'我暂时不申请，只想了解借用规则','after-cancel')
    except Exception as e:error=f'{type(e).__name__}: {e}'
    else:error=None
    await w.runs.close()
    return {'result':'DEFECT_REPRODUCED' if error and not calls else 'NOT_REPRODUCED','mode':'real conversation/task routing, synthetic knowledge answer never used','error':error,'knowledge_calls':len(calls),'bound_task_status':w.service.view(t['task_id'])['status']}

async def main():
    for name,fn in [('loan_full_lifecycle',loan),('repair_full_lifecycle',repair),('knowledge_failure_status',knowledge_failure),('knowledge_cancel_status',knowledge_cancel),('chat_after_task_cancel',cancelled_task_chat)]:
        with tempfile.TemporaryDirectory(prefix='esa040_probe_') as td:
            try:entry=await fn(Path(td))
            except Exception:entry={'result':'PROBE_ERROR','traceback':traceback.format_exc()}
            entry={'id':name,**entry};results.append(entry)
    out={'source':str(Path(a.source).resolve()),'python':platform.python_version(),'supported_source_python':'3.11/3.12; current independent runner is 3.13.5, not a pinned install','scope':'Real domain and persistence code, isolated synthetic data. No real LLM, embeddings, FastAPI launch or full browser E2E is claimed.','results':results}
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2))
asyncio.run(main())
