"""Current rc4 HTTP app + temp SQLite; explicit external-only doubles.
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
 with tempfile.TemporaryDirectory(prefix='esa-rc4-review-') as d:
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
 return w.service.create({'kind':'loan','execution_ceiling':ceiling,'confirmed':True,'facts':{'loan_start':str(day+timedelta(days=1)),'loan_end':str(day+timedelta(days=3)),'purpose':'rc4审核合成场景'}})
