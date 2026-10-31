"""Independent review probes: original app and SQLite, external answer adapter only."""
import asyncio, json, sys, tempfile, time, shutil
from pathlib import Path
import argparse, os
parser=argparse.ArgumentParser(description="Reproduce ORIGINAL 0.6 findings; not fixed-version acceptance. Uses only synthetic temporary workspaces.")
parser.add_argument("--source", type=Path, required=True, help="Root of extracted 0.6 source containing app/ and tests/")
parser.add_argument("--out", type=Path, default=Path("review-probe-output"))
args=parser.parse_args()
source=args.source.resolve()
if not (source/"app/workbench_app.py").is_file():
    parser.error("--source must point to the actual project root")
args.out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(source))
os.environ["PYTHONPATH"]=str(source)+os.pathsep+os.environ.get("PYTHONPATH", "")
from tests.product.test_turn_recovery import product
from app.launcher.core import open_workspace, selected_workspace, remember
from app.workspace import initialize
import httpx
OUT=args.out.resolve()
H={'X-ESA-Request':'1'}
results=[]
def save(name, data):
 results.append({'id':name,**data}); print(name, json.dumps(data,ensure_ascii=False)); (OUT/'independent_probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
async def wait(w, rid):
 handle=w.runs.tasks.get(rid)
 if handle: await handle

def answer_payload(q):
 return {'id':'probe-answer','result':{'mode':'answered','answer':'测试外部适配器结果','claims':[], 'citations':[], 'sources':[], 'warnings':[], 'stop_reason':'completed'},'question':q}
with tempfile.TemporaryDirectory(prefix='esa-review-') as root:
 with product(Path(root)) as c:
  w=c.app.state.workspace; kb=w.library.create('probe-kb')['id']; cid=w.conversations.create(kb)['id']; calls=[]
  async def external(*args,**kw):
   calls.append(kw.get('detailed',False))
   if len(calls)==1: raise ConnectionError('injected first answer failure')
   return answer_payload(args[1])
  w.library.answer=external
  r=c.post(f'/api/conversations/{cid}/turns',headers=H,json={'text':'比较两个制度','message_id':'deep-retry','detailed':True}); c.portal.call(wait,w,r.json()['id'])
  retry=c.post(f'/api/product/conversations/{cid}/turns/deep-retry/retry',headers=H,json={}); c.portal.call(wait,w,retry.json()['id'])
  save('F01_RETRY_LOSES_MODE',{'external_detailed_flags':calls,'initial_input':json.loads(w.runs.get(r.json()['id'])['input_json']),'retry_input':json.loads(w.runs.get(retry.json()['id'])['input_json']),'retry_status':w.runs.get(retry.json()['id'])['status'],'defect_reproduced':calls==[True,False]})
with tempfile.TemporaryDirectory(prefix='esa-review-') as root:
 with product(Path(root)) as c:
  w=c.app.state.workspace; cid=w.conversations.create()['id']
  r=c.post(f'/api/conversations/{cid}/turns',headers=H,json={'text':'制度是什么','message_id':'before-kb'});c.portal.call(wait,w,r.json()['id']); before=w.runs.get(r.json()['id'])
  kb=w.library.create('later-kb')['id']; called=[]
  async def external(*args,**kw): called.append(args);return answer_payload(args[1])
  w.library.answer=external
  r2=c.post(f'/api/product/conversations/{cid}/turns/before-kb/retry',headers=H,json={});c.portal.call(wait,w,r2.json()['id']); after=w.runs.get(r2.json()['id'])
  save('F02_NO_KB_CONVERSATION_CANNOT_RECOVER',{'initial_error':before['error'],'new_kb_exists':kb in [x['id'] for x in w.library.list()['bases']],'stored_kb_after':w.conversations.get(cid)['kb_id'],'retry_error':after['error'],'external_calls':len(called),'binding_update_routes':[x.path for x in c.app.routes if 'conversation' in getattr(x,'path','') and ('PATCH' in getattr(x,'methods',set()) or 'PUT' in getattr(x,'methods',set()))],'defect_reproduced':after['status']=='failed' and 'KNOWLEDGE_BASE_REQUIRED' in after['error']})
with tempfile.TemporaryDirectory(prefix='esa-review-registry-') as td:
 b=Path(td); old=b/'original'; moved=b/'moved'; registry=b/'registry.json'; initialize(old)
 with product(old) as c: c.app.state.workspace.conversations.create(title='PRESERVE_ME')
 remember(old,registry);old.rename(moved);selected=selected_workspace(None,registry);info=None
 try:
  info=open_workspace(selected,registry=registry,port=0,browser=False)
  with httpx.Client(base_url=info['url'],headers=H,trust_env=False,timeout=5) as client:
   rows=client.get('/api/conversations').json()
   save('F03_STALE_WORKSPACE_SILENT_EMPTY_INIT',{'selected_missing_registry_path':selected==old,'old_path_recreated':(old/'app.sqlite3').exists(),'new_instance_conversations':rows,'original_data_still_at_moved_path':(moved/'app.sqlite3').exists(),'defect_reproduced':selected==old and len(rows)==0 and (old/'app.sqlite3').exists()})
   client.post('/api/product/shutdown')
 finally:
  if info:
   try:httpx.post(info['url']+'/api/product/shutdown',headers=H,trust_env=False,timeout=2)
   except httpx.HTTPError:pass
  time.sleep(.5)
with tempfile.TemporaryDirectory(prefix='esa-review-history-') as root:
 with product(Path(root)) as c:
  w=c.app.state.workspace
  ids=[w.conversations.create(title=f'conversation-{i}')['id'] for i in range(105)]
  listing=c.get('/api/conversations').json()
  old=c.get('/api/conversations/'+ids[0])
  save('F04_HISTORY_HIDDEN_AFTER_100',{'created':len(ids),'listed':len(listing),'earliest_listed':ids[0] in [x['id'] for x in listing],'earliest_direct_http':old.status_code,'defect_reproduced':len(listing)==100 and old.status_code==200 and ids[0] not in [x['id'] for x in listing]})
print('DONE')
