"""Original rc3 HTTP app + temp SQLite; explicit external-only doubles.
No Windows binaries, private workspaces, or real LLM calls are used.
"""
import json,tempfile,traceback,sys,os
from pathlib import Path
from contextlib import contextmanager
from datetime import timedelta
if not os.environ.get('ESA_SOURCE'):
 raise SystemExit('Set ESA_SOURCE to the real source root containing app/. Use project-supported dependencies.')
SRC=Path(os.environ['ESA_SOURCE']).resolve()
sys.path.insert(0,str(SRC))
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.persistence.workspaces import initialize
from app.workbench_app import create_workbench_app
from app.workbench_service import local_actor
from app.service_desk.store import ServiceError
H={'X-ESA-Request':'1'}
@contextmanager
def product():
 with tempfile.TemporaryDirectory(prefix='esa-rc3-review-') as d:
  root=Path(d);initialize(root,sample=True)
  def external(r):
   if r.url.path=='/api/tags':return httpx.Response(200,json={'models':[]})
   return httpx.Response(503,json={'error':'audit: no real model call'})
  with TestClient(create_workbench_app(Settings(data_dir=root,sqlite_path=root/'app.sqlite3'),model_transport=httpx.MockTransport(external))) as c:
   yield c,c.app.state.workspace
class Model:
 def __init__(self,*batches):self.batches=list(batches);self.calls=[]
 async def chat(self,*args,**kwargs):
  self.calls.append((args,kwargs))
  if not self.batches:raise AssertionError('scripted model exhausted; no implicit success')
  return {'content':'AUDIT_SYNTHETIC_MODEL_DECISION','tool_calls':[{'function':{'name':n,'arguments':a}} for n,a in self.batches.pop(0)]}
def wait(c,run_id):
 async def finish():
  h=c.app.state.workspace.runs.tasks.get(run_id)
  if h:await h
 c.portal.call(finish)
 return c.app.state.workspace.runs.get(run_id)
def post_turn(c,cid,mid,text):
 r=c.post('/api/conversations/'+cid+'/turns',headers=H,json={'text':text,'message_id':mid})
 assert r.status_code==202,r.text
 return wait(c,r.json()['id'])
def loan(w,ceiling='SUBMIT_AFTER_CONFIRMATION'):
 day=w.service.store.today()
 return w.service.create({'kind':'loan','execution_ceiling':ceiling,'confirmed':True,'facts':{'loan_start':str(day+timedelta(days=1)),'loan_end':str(day+timedelta(days=3)),'purpose':'rc3审核合成场景'}})

def fixes_and_new_ui_flow():
 with product() as (c,w):
  t=loan(w);tid=t['task_id'];rev=t['facts_revision']
  r=c.patch(f'/api/product/tasks/{tid}/facts',headers=H,json={'changes':{'purpose':'已保存的新用途'},'expected_facts_revision':rev});assert r.status_code==200,r.text
  form=r.json();assert form['revision']==rev+1 and form['next_action']['kind']=='choice'
  selected=c.post(f'/api/product/tasks/{tid}/asset',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':form['revision']});assert selected.status_code==200,selected.text
  prep=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'expected_facts_revision':selected.json()['revision']});assert prep.status_code==200,prep.text
  p=prep.json();assert p['preview'] and p['can_submit']
  payload={'proposal_id':p['preview']['proposal_id'],'content_digest':p['preview']['content_digest'],'expected_facts_revision':p['revision'],'accepted':True}
  a=c.post(f'/api/tasks/{tid}/submit',headers=H,json=payload);b=c.post(f'/api/tasks/{tid}/submit',headers=H,json=payload)
  assert a.status_code==b.status_code==200 and a.json()['receipt']==b.json()['receipt']
  assert len(w.service.store.list_tickets(local_actor()))==1
  return {'status':'PASS','saved_revision':form['revision'],'saved_next_action':form['next_action'],'selected_next_action':selected.json()['next_action'],'prepared_next_action':p['next_action'],'submit_http':[a.status_code,b.status_code],'ticket_count':1}

def missing_input_and_form_completion():
 with product() as (c,w):
  t=w.service.create({'kind':'repair','execution_ceiling':'PREVIEW_ONLY','confirmed':True});tid=t['task_id'];cid=t['conversation_id']
  m=Model([('update_parameters',{'changes':{'description':'笔记本无法开机'},'turn_request':{'preview':True,'knowledge_quote':''}})],[('ask_user',{'fields':['asset_id','impact'],'reason':'missing','question':'设备编号和影响程度'})]);w.models.chat=m.chat
  result=post_turn(c,cid,'missing','笔记本无法开机，请准备报修预览。');assert result['status']=='succeeded'
  first=c.get('/api/product/tasks/'+tid).json();assert first['next_action']['kind']=='input' and first['status']=='WAITING_USER'
  retry=c.post(f'/api/product/conversations/{cid}/turns/missing/retry',headers=H,json={});assert retry.status_code==409 and retry.json()['error']['code']=='USER_INPUT_REQUIRED'
  choices=c.get(f'/api/product/tasks/{tid}/alternatives').json();asset=choices[0]['asset_id']
  saved=c.patch(f'/api/product/tasks/{tid}/facts',headers=H,json={'changes':{'asset_id':asset,'impact':'high'},'expected_facts_revision':first['revision']});assert saved.status_code==200,saved.text
  prepared=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'expected_facts_revision':saved.json()['revision']});assert prepared.status_code==200,prepared.text
  turns=w.conversations.turns(cid)
  return {'status':'PASS','first_status':first['status'],'first_action':first['next_action'],'waiting_retry_http':retry.status_code,'after_save_action':saved.json()['next_action'],'after_prepare_action':prepared.json()['next_action'],'after_prepare_user_status':next(x['status'] for x in turns if x['id']=='missing'),'assistant_turns':[{'status':x['status'],'text':x['text'],'delivery_status':(x.get('payload',{}).get('turn_delivery') or {}).get('status')} for x in turns if x['role']=='assistant']}

def history_limits():
 with product() as (c,w):
  ids=[]
  for i in range(55):
   t=w.service.create({'kind':'loan','execution_ceiling':'READ_ONLY','confirmed':True});ids.append(t['task_id'])
  listed=c.get('/api/product/tasks');first=c.get('/api/product/tasks/'+ids[0]);assert listed.status_code==first.status_code==200
  with w.library.db() as db:
   for i in range(55):
    db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES(?,?,?,?,?,?)',(f'a{i:03d}','audit-conv','audit-kb',f'问题{i}',json.dumps({'mode':'not_found','answer':f'合成无答案记录{i}','sources':[]}), 'audit-generation'))
  old=c.get('/api/product/answers/a000');new=c.get('/api/product/answers/a054')
  with w.library.db() as db: count=db.execute('SELECT COUNT(*) FROM knowledge_answers').fetchone()[0]
  defect=len(listed.json())==50 and ids[0] not in [x['id'] for x in listed.json()] and old.status_code==409 and new.status_code==200
  return {'status':'DEFECT_REPRODUCED' if defect else 'OBSERVED','tasks_created':55,'tasks_listed':len(listed.json()),'old_task_detail_http':first.status_code,'old_task_in_list':ids[0] in [x['id'] for x in listed.json()],'answers_in_db':count,'old_answer_by_id_http':old.status_code,'old_answer_body':old.json(),'new_answer_by_id_http':new.status_code,'data_deleted':False}

def expired_preview():
 with product() as (c,w):
  t=loan(w);tid=t['task_id']
  prep=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':t['facts_revision']});assert prep.status_code==200,prep.text
  before=prep.json();p=before['preview'];base_clock=w.service.store.clock
  w.service.store.clock=lambda:p['expires_at']+1
  shown=c.get('/api/product/tasks/'+tid);payload={'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],'expected_facts_revision':before['revision'],'accepted':True}
  rejected=c.post(f'/api/tasks/{tid}/submit',headers=H,json=payload)
  after=c.get('/api/product/tasks/'+tid)
  return {'status':'DEFECT_REPRODUCED' if shown.json()['can_submit'] and rejected.status_code==409 else 'OBSERVED','time_shift_seconds':601,'displayed_can_submit':shown.json()['can_submit'],'displayed_next_action':shown.json()['next_action'],'submit_http':rejected.status_code,'submit_error':rejected.json(),'after_rejection_action':after.json()['next_action'],'ticket_count':len(w.service.store.list_tickets(local_actor()))}

def knowledge_retry_not_business_input():
 with product() as (c,w):
  kb=w.library.create('审核合成知识库')['id']
  t=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True},kb_id=kb)
  tid=t['task_id'];cid=t['conversation_id'];calls=[]
  async def answer(*args,**kwargs):
   calls.append(1)
   if len(calls)==1:raise ServiceError('TRANSIENT_TOOL_FAILURE')
   return {'id':'fixture-answer','result':{'mode':'not_found','answer':'合成恢复结果','sources':[]}}
  w.library.answer=answer
  m=Model([('update_parameters',{'changes':{},'turn_request':{'preview':False,'knowledge_quote':'借用期限'}})], [('knowledge_answer',{'question':'借用期限'})], [('finish',{})]);w.models.chat=m.chat
  run=post_turn(c,cid,'knowledge-only','先解释借用期限，我还没决定日期，不要生成预览。')
  turn=next(t for t in w.conversations.turns(cid) if t['id']=='knowledge-only')
  r=c.post(f'/api/product/conversations/{cid}/turns/knowledge-only/retry',headers=H,json={})
  if r.status_code==202:wait(c,r.json()['id'])
  return {'status':'DEFECT_REPRODUCED' if turn['status']=='WAITING_USER' and r.status_code==409 else 'OBSERVED',
    'original_request':'知识解释，不准备预览','run_status':run['status'],'turn_status':turn['status'],
    'delivery':turn['payload'].get('turn_delivery'),'retry_http':r.status_code,'retry_body':r.json(),
    'knowledge_calls':len(calls),'task_required_fields':w.service.view(tid)['missing_fields']}

rows=[]
for name,fn in [('save_select_preview_submit',fixes_and_new_ui_flow),('waiting_input_and_ui_completion',missing_input_and_form_completion),('persistent_history_limits',history_limits),('expired_preview_view',expired_preview),('knowledge_retry_not_business_input',knowledge_retry_not_business_input)]:
 try:rows.append({'case':name,**fn()})
 except BaseException as exc:rows.append({'case':name,'status':'HARNESS_ERROR','error':repr(exc),'trace':traceback.format_exc()})
p=Path(os.environ.get('ESA_PROBE_OUT','rc3_probe_results.json'));p.write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False,indent=2))
