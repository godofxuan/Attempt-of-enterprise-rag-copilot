"""Audit original 0.2.0 business code without replacing source modules.
No LLM/embedding execution. Scripted tool decisions isolate orchestration branches.
The source's full FastAPI startup/dependency installation is a separate NOT_RUN check.
"""
import argparse, asyncio, json, sqlite3, sys, tempfile, subprocess
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
SOURCE=args.source.resolve()
OUTPUT=args.output.resolve(); OUTPUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(SOURCE))
from app.workspace import initialize, WorkspaceConfig
from app.workbench_service import TaskService, local_actor
from app.runtime.workbench_runs import Runs
from app.service_desk.store import ServiceError
BASE=OUTPUT/'temporary-data'; BASE.mkdir(exist_ok=True)
ROOT=Path(tempfile.mkdtemp(prefix='run-',dir=BASE))
records=[]

def workspace(name):
    root=ROOT/name
    initialize(root,sample=True)
    w=SimpleNamespace(root=root,db_path=root/'app.sqlite3',config=WorkspaceConfig(sample_data=True))
    w.service=TaskService(w)
    return w

def loan(w):
    today=w.service.store.today()
    return w.service.create({'kind':'loan','execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','confirmed':True,
      'facts':{'loan_start':str(today+timedelta(days=1)),'loan_end':str(today+timedelta(days=3)),'purpose':'项目展示'}})

def prepare(w,t,asset):
    s=w.service; actor=local_actor(); tid=t['task_id']; policy=s.policy(tid)
    s.store.observe(actor,tid,'assets.search',{'status':'ok','data':s.assets(tid)})
    s.store.observe(actor,tid,'tickets.list_mine',{'status':'ok','data':{'tickets':s.tickets(tid)}})
    return s.store.propose(actor,tid,asset,[policy['ref']])

def commit(w,t,p):
    body={'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],
       'expected_facts_revision':t['facts_revision'],'accepted':True}
    first=w.service.submit(t['task_id'],body)
    again=w.service.submit(t['task_id'],body)
    return first,again

def add(id,kind,**data):records.append({'id':id,'verification_kind':kind,**data})

# Ordinary happy paths, using original code and real temporary SQLite.
w=workspace('loan')
t=loan(w); first=prepare(w,t,'loan-laptop-1'); old=t['facts_revision']
t=w.service.facts(t['task_id'],{'purpose':None},old)
assert 'purpose' not in t['facts']
try:w.service.facts(t['task_id'],{'purpose':'陈旧输入'},old)
except ServiceError as e:assert e.code=='TASK_CHANGED'
else:raise AssertionError('stale accepted')
t=w.service.facts(t['task_id'],{'purpose':'本次演示'},t['facts_revision'])
for i in range(4,10):
    t=w.service.facts(t['task_id'],{'loan_end':str(w.service.store.today()+timedelta(days=i))},t['facts_revision'])
    p=prepare(w,t,'loan-laptop-1')
r,again=commit(w,t,p)
child="""import json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from app.workspace import WorkspaceConfig
from app.workbench_service import TaskService
root=Path(sys.argv[2]); w=SimpleNamespace(root=root,db_path=root/'app.sqlite3',config=WorkspaceConfig(sample_data=True))
print(json.dumps(TaskService(w).view(sys.argv[3])['receipt']))
"""
completed=subprocess.run([sys.executable,'-c',child,str(SOURCE),str(w.root),t['task_id']],capture_output=True,text=True,check=True)
restored_receipt=json.loads(completed.stdout)
assert r['receipt']==again['receipt']==restored_receipt
add('loan_lifecycle','ORIGINAL_SERVICE_REAL_SQLITE',result='PASS',
    null_clear=True,stale_revision='TASK_CHANGED',successive_preview_revisions=6,
    business_status=r['receipt']['ticket']['status'],ticket_count=len(w.service.tickets(t['task_id'])),
    separate_process_readback=True)

w=workspace('repair')
t=w.service.create({'kind':'repair','execution_ceiling':'SUBMIT_AFTER_CONFIRMATION','confirmed':True,
    'facts':{'asset_id':'employee-laptop-1','description':'屏幕持续闪烁','impact':'high'}})
p=prepare(w,t,'employee-laptop-1'); r,again=commit(w,t,p)
assert r['receipt']==again['receipt']
with sqlite3.connect(w.db_path) as db:
    counts={k:db.execute('SELECT COUNT(*) FROM '+k).fetchone()[0] for k in ('tickets','it_repair_tickets')}
add('repair_lifecycle','ORIGINAL_SERVICE_REAL_SQLITE',result='PASS',business_status=r['receipt']['ticket']['status'],counts=counts)

# Actual asset reader already removes unavailable rows; retain that behavior.
w=workspace('alternatives'); t=loan(w)
with w.service.store.transaction() as db: db.execute('UPDATE assets SET available=0')
options=w.service.alternatives(t['task_id'])
assert options == []
add('all_unavailable_alternatives','ORIGINAL_SERVICE_REAL_SQLITE',
    result='PASS',returned_candidates=len(options))

class AskOnlyModel:
    def __init__(self):self.calls=0
    async def chat(self,*args,**kwargs):
        self.calls+=1
        return {'content':'','tool_calls':[{'function':{'name':'ask_user','arguments':{}}}]}

class WaitingModel:
    def __init__(self):self.entered=asyncio.Event()
    async def chat(self,*args,**kwargs):
        self.entered.set(); await asyncio.Event().wait()

async def async_cases():
    w=workspace('repair_missing'); w.models=AskOnlyModel(); w.runs=Runs(w)
    t=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True})
    run=w.runs.start('service',{'task_id':t['task_id']}); handle=w.runs.tasks[run['id']];await handle
    result=w.runs.get(run['id']); now=w.service.view(t['task_id'])
    add('repair_missing_fields','ORIGINAL_ORCHESTRATOR_SCRIPTED_TOOL_DECISION',
       result='REPRODUCED_BUG',run_status=result['status'],error=result['error'],task_status=now['status'],
       missing_fields=now['missing_fields'],live_model_calls=0)
    await w.runs.close()

    w=workspace('knowledge_followup'); w.models=AskOnlyModel();w.runs=Runs(w)
    t=w.service.create({'kind':'knowledge','execution_ceiling':'READ_ONLY','confirmed':True,'question':'电脑最长借多少天'},kb_id='isolated-probe-kb')
    run=w.runs.start('message',{'task_id':t['task_id'],'text':'为什么有这个限制？','message_id':'followup-1','expected_facts_revision':t['facts_revision']})
    handle=w.runs.tasks[run['id']]; await handle
    result=w.runs.get(run['id']);now=w.service.view(t['task_id'])
    add('knowledge_task_followup','ORIGINAL_MESSAGE_AND_RUN_CODE_NO_MODEL_CALL',result='REPRODUCED_BUG',
        run_status=result['status'],error=result['error'],pending_update=now['pending_update'],
        model_calls=w.models.calls)
    await w.runs.close()

    w=workspace('cancel_running'); w.models=WaitingModel();w.runs=Runs(w);t=loan(w)
    run=w.runs.start('service',{'task_id':t['task_id']});handle=w.runs.tasks[run['id']]
    await asyncio.wait_for(w.models.entered.wait(),timeout=5)
    w.runs.cancel(run['id']); await handle
    stopped=w.runs.get(run['id']);now=w.service.view(t['task_id'])
    retry=w.runs.start('service',{'task_id':t['task_id']});await w.runs.tasks[retry['id']]
    retry_result=w.runs.get(retry['id'])
    add('cancel_and_continue','ORIGINAL_RUN_SERVICE_WITH_SUSPENDED_MODEL_STUB',
       result='REPRODUCED_BUG',run_status=stopped['status'],task_status=now['status'],
       active_run_remaining=bool(now['active_run_id']),retry_status=retry_result['status'],
       retry_error=retry_result['error'],live_model_calls=0)
    await w.runs.close()

asyncio.run(async_cases())
output={'source_archive_commit':'8881b000fe4e216ff035d4f2853c2d7e58087c10',
        'python':sys.version,'full_app_startup':'NOT_TESTED_BY_THIS_SCRIPT',
        'live_llm_runs':0,'records':records}
out=OUTPUT/'product_probes.json'
out.write_text(json.dumps(output,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(output,ensure_ascii=False,indent=2))
