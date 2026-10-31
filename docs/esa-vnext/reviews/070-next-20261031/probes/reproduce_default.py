"""Independent product-path probes: original application + real SQLite, only model/knowledge boundaries doubled.
Run with ESA_SOURCE pointed at the reviewed candidate. Not live-model quality evidence.
"""
import json,os,sys,tempfile,traceback
from pathlib import Path
source=Path(os.environ.get('ESA_SOURCE', '.')).resolve()
if not (source/'app/workbench_app.py').is_file(): raise SystemExit('Set ESA_SOURCE to the candidate repository root')
sys.path.insert(0,str(source))
from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import wait,H
from tests.vnext.test_conversations import SequenceModel
from tests.vnext.test_service_lifecycle import create
from app.workbench_service import local_actor
from app.service_desk.store import ServiceError
rows=[]
def probe(mode):
 with tempfile.TemporaryDirectory(prefix='esa070-independent-') as d:
  with product(Path(d)) as c:
   w=c.app.state.workspace
   kb=w.library.create('独立复核合成资料库')['id']
   task=create(w.service,'PREVIEW_ONLY'); tid=task['task_id']; cid=task['conversation_id']
   w.conversations.update(cid,{'kb_id':kb})
   with w.service.store.transaction() as db:
    t=w.service.store._task(db,local_actor(),tid); t['kb_id']=kb; w.service.store._save(db,t)
   calls=[]
   async def answer(*a,**kw):
    calls.append({'args':a,'kwargs':kw})
    if mode=='partial_failure': raise ServiceError('EVIDENCE_INSUFFICIENT')
    return {'id':'synthetic-knowledge','question':a[1],'result':{'mode':'answered','answer':'合成测试边界结果','sources':[]}}
   w.library.answer=answer
   plan=[('prepare_preview',{'asset_id':'loan-laptop-1'})]
   if mode=='partial_failure': plan += [('knowledge_answer',{'question':'押金制度如何规定？'}),('finish',{})]
   model=SequenceModel([('loan_policy',{}),('assets_search',{}),('tickets_list_mine',{})],plan)
   w.models.chat=model.chat
   mid='independent-'+mode
   req=c.post(f'/api/conversations/{cid}/turns',headers=H,json={'message_id':mid,'text':'请准备借用预览，并解释押金制度，不要提交。'})
   if req.status_code!=202: raise RuntimeError(req.text)
   result=wait(c,req.json()['id']); latest=w.service.view(tid)
   user=next(t for t in w.conversations.turns(cid) if t['id']==mid)
   retry=c.post(f'/api/product/conversations/{cid}/turns/{mid}/retry',headers=H,json={})
   return {'case':mode,'model_is_double':True,'knowledge_is_double':True,'run_status':result['status'],'turn_status':user['status'],'task_status':latest['status'],'preview_present':bool(latest.get('preview')),'knowledge_calls':len(calls),'knowledge_present':bool(latest.get('knowledge_result')),'assistant_text':latest.get('assistant_text'),'retry_http':retry.status_code,'retry_body':retry.json(),'ticket_count':len(w.service.store.list_tickets(local_actor())),'model_steps':len(model.calls)}
for mode in ['partial_failure','omitted_knowledge']:
 try: rows.append(probe(mode))
 except Exception: rows.append({'case':mode,'harness_error':traceback.format_exc()})
out=Path(os.environ.get('ESA_PROBE_OUT','esa070_review_probes.json')).resolve()
out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8'); print(out.read_text(encoding='utf-8'))
