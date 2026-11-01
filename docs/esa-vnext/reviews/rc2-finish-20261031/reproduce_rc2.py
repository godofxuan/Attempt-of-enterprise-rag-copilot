"""Current rc2 product factory, original business code and temporary SQLite.
Only external model decisions / knowledge calls are replaced deterministically.
"""
import json,tempfile,traceback,os,sys
from pathlib import Path
source=Path(os.environ.get("ESA_SOURCE", ".")).resolve()
if not (source/"app/workbench_app.py").is_file():
 raise SystemExit("Set ESA_SOURCE to repository root or extracted runtime/Lib/site-packages")
sys.path.insert(0,str(source))
from datetime import timedelta
from contextlib import contextmanager
import httpx
from fastapi.testclient import TestClient
from app.workbench_app import create_workbench_app
from app.config import Settings
from app.persistence.workspaces import initialize
from app.service_desk.store import ServiceError
from app.workbench_service import local_actor
H={'X-ESA-Request':'1'}
@contextmanager
def product():
 with tempfile.TemporaryDirectory(prefix='rc2-probe-') as d:
  root=Path(d); initialize(root,sample=True)
  app=create_workbench_app(Settings(data_dir=root,sqlite_path=root/'app.sqlite3'),model_transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'models':[]})))
  with TestClient(app) as c: yield c

def wait(c,run):
 async def done():
  handle=c.app.state.workspace.runs.tasks.get(run)
  if handle: await handle
 c.portal.call(done)
 return c.app.state.workspace.runs.get(run)
class Model:
 def __init__(self,*batches):self.batches=list(batches);self.calls=[]
 async def chat(self,*args,**kwargs):
  self.calls.append((args,kwargs))
  batch=self.batches.pop(0) if self.batches else [('finish',{})]
  return {'content':'合成模型决策，不代表真实模型效果','tool_calls':[{'function':{'name':n,'arguments':a}} for n,a in batch]}
def create(w,scope='SUBMIT_AFTER_CONFIRMATION'):
 today=w.service.store.today()
 return w.service.create({'kind':'loan','execution_ceiling':scope,'confirmed':True,'facts':{'loan_start':str(today+timedelta(days=1)),'loan_end':str(today+timedelta(days=3)),'purpose':'发行包正常流程复核'}})
def post(c,cid,mid,text):
 r=c.post(f'/api/conversations/{cid}/turns',headers=H,json={'message_id':mid,'text':text})
 assert r.status_code==202,r.text
 return wait(c,r.json()['id'])
rows=[]
def record(name,f):
 try: rows.append({'case':name,'scope':'rc2 original API/SQLite; external model/knowledge doubles where stated',**f()})
 except Exception: rows.append({'case':name,'harness_error':traceback.format_exc()})
def partial():
 with product() as c:
  w=c.app.state.workspace;t=create(w,'PREVIEW_ONLY');cid=t['conversation_id'];tid=t['task_id'];kb=w.library.create('合成制度')['id'];w.conversations.update(cid,{'kb_id':kb})
  n=[]
  async def answer(*args,**kwargs):
   n.append({'args':args,'kwargs':kwargs})
   if len(n)==1: raise ServiceError('EVIDENCE_INSUFFICIENT')
   return {'id':'test-answer','result':{'mode':'answered','answer':'合成测试回答','sources':[]}}
  w.library.answer=answer
  brief={'preview':True,'knowledge_quote':'解释押金制度'}
  m=Model([('loan_policy',{}),('assets_search',{}),('tickets_list_mine',{})],[('prepare_preview',{'asset_id':'loan-laptop-1','turn_request':brief}),('knowledge_answer',{'question':'解释押金制度'})])
  w.models.chat=m.chat
  one=post(c,cid,'partial','请准备借用预览，并解释押金制度，不要提交。')
  turn=next(x for x in w.conversations.turns(cid) if x['id']=='partial');preview1=w.service.view(tid)['preview'];calls=len(m.calls)
  r=c.post(f'/api/product/conversations/{cid}/turns/partial/retry',headers=H,json={});two=wait(c,r.json()['id']) if r.status_code==202 else r.json()
  turn2=next(x for x in w.conversations.turns(cid) if x['id']=='partial');view=w.service.view(tid)
  ok=turn['status']=='PARTIAL' and r.status_code==202 and turn2['status']=='DONE' and preview1['proposal_id']==view['preview']['proposal_id'] and len(m.calls)==calls
  return {'expected_behavior':ok,'initial_run_status':one['status'],'initial_turn_status':turn['status'],'retry_http':r.status_code,'after_turn_status':turn2['status'],'retry_run_status':two.get('status'),'knowledge_calls':len(n),'model_calls_before_after':[calls,len(m.calls)],'preview_reused':preview1['proposal_id']==view['preview']['proposal_id'],'tickets':len(w.service.store.list_tickets(local_actor()))}
def missing():
 with product() as c:
  w=c.app.state.workspace;t=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True});tid=t['task_id'];cid=t['conversation_id']
  brief={'preview':True,'knowledge_quote':''}
  m=Model([('update_parameters',{'changes':{'description':'笔记本无法开机'},'turn_request':brief})],[('ask_user',{'fields':['asset_id','impact'],'reason':'missing','question':'请补充设备编号和影响程度。'})]);w.models.chat=m.chat
  run=post(c,cid,'ask_missing','我的笔记本无法开机，请帮我准备报修预览。');view=w.service.view(tid);turn=next(x for x in w.conversations.turns(cid) if x['id']=='ask_missing')
  return {'run_status':run['status'],'run_error':run.get('error'),'task_status':view['status'],'missing_fields':view.get('missing_fields'),'question':view.get('question'),'assistant_text':view.get('assistant_text'),'turn_status':turn['status'],'delivery':turn['payload'].get('turn_delivery'),'tools':[[(a['function']['name']) for a in c[1].get('tools',[])] for c in m.calls],'actual_form':c.get(f'/api/product/tasks/{tid}').json()}
def omitted():
 with product() as c:
  w=c.app.state.workspace;t=create(w,'PREVIEW_ONLY');cid=t['conversation_id'];tid=t['task_id'];kb=w.library.create('合成资料')['id'];w.conversations.update(cid,{'kb_id':kb});n=[]
  async def answer(*a,**kw):n.append(a);return {'id':'not-called','result':{'mode':'answered','answer':'x','sources':[]}}
  w.library.answer=answer
  brief={'preview':True,'knowledge_quote':'解释押金制度'}
  m=Model([('loan_policy',{}),('assets_search',{}),('tickets_list_mine',{})],[('prepare_preview',{'asset_id':'loan-laptop-1','turn_request':brief})],[('finish',{})]);w.models.chat=m.chat
  run=post(c,cid,'omit','请准备借用预览，并解释押金制度，不要提交。');turn=next(x for x in w.conversations.turns(cid) if x['id']=='omit')
  return {'fixed_no_false_complete':turn['status']=='PARTIAL','run_status':run['status'],'turn_status':turn['status'],'knowledge_calls':len(n),'delivery':turn['payload'].get('turn_delivery')}
def deterministic():
 with product() as c:
  w=c.app.state.workspace;t=create(w);tid=t['task_id'];count=[]
  async def no_model(*a,**kw):count.append(1);raise AssertionError('model forbidden for explicit button')
  w.models.chat=no_model
  r=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'expected_facts_revision':t['facts_revision']})
  selection_required = r.status_code == 409 and r.json().get('error',{}).get('code') == 'RESOURCE_SELECTION_REQUIRED'
  r=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'expected_facts_revision':t['facts_revision'],'asset_id':'loan-laptop-1'})
  if r.status_code!=200:return {'prepare_http':r.status_code,'body':r.json()}
  t=w.service.view(tid);p=t['preview'];args={'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],'accepted':True,'expected_facts_revision':t['facts_revision']}
  a=c.post(f'/api/tasks/{tid}/submit',headers=H,json=args);b=c.post(f'/api/tasks/{tid}/submit',headers=H,json=args)
  return {'resource_selection_required_before_choice':selection_required,'prepare_http':r.status_code,'submit_http':[a.status_code,b.status_code],'tickets':len(w.service.store.list_tickets(local_actor())),'same_receipt':a.json().get('receipt')==b.json().get('receipt'),'model_calls':len(count)}
def saved_then_prepare_fails():
 with product() as c:
  w=c.app.state.workspace;t=create(w,'PREVIEW_ONLY');tid=t['task_id'];old=t['facts_revision']
  payload={'changes':{'purpose':'已经保存的新用途'},'expected_facts_revision':old}
  first=c.patch(f'/api/tasks/{tid}/facts',headers=H,json=payload)
  current=first.json()['facts_revision']
  second=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'expected_facts_revision':current})
  repeated=c.patch(f'/api/tasks/{tid}/facts',headers=H,json=payload)
  actual=c.get(f'/api/product/tasks/{tid}').json()
  return {'first_save_http':first.status_code,'prepare_http':second.status_code,'prepare_code':second.json().get('error',{}).get('code'),'repeat_same_ui_payload_http':repeated.status_code,'repeat_code':repeated.json().get('error',{}).get('code'),'old_revision':old,'saved_revision':current,'actual_revision':actual['revision'],'persisted_purpose':w.service.view(tid)['facts']['purpose'],'frontend_branch':'shipped mutation awaits prepare before cache invalidation, verified statically; browser not executed'}
record('save_success_prepare_needs_choice_stale_retry',saved_then_prepare_fails)
record('partial_preview_knowledge_retry',partial)
record('omitted_knowledge_is_partial',omitted)
record('explicit_prepare_and_idempotent_submit',deterministic)
record('ordinary_repair_missing_fields',missing)
out=Path(os.environ.get('ESA_PROBE_OUT','rc2_probe_results.json')).resolve();out.write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str))
for row in rows:
 x={k:v for k,v in row.items() if k not in {'actual_form','tools'}};print(json.dumps(x,ensure_ascii=False,indent=2))
