"""Offline UI fixtures through actual transactions. No model choices or model success."""
import asyncio,json
from datetime import timedelta
from pathlib import Path
from app.workspace import initialize,Workspace
from app.config import Settings
from app.workbench_service import local_actor

root=Path('.private/esa-vnext/presentation-fixture').resolve()
initialize(root,sample=True)
async def prepare():
 workspace=Workspace(Settings(workbench_enabled=True,data_dir=root,sqlite_path=root/'app.sqlite3'));await workspace.start()
 try:
  service=workspace.service;who=local_actor();today=service.store.today();tasks=[]
  for scope,purpose in [('SUBMIT_AFTER_CONFIRMATION','PROGRAM_FIXTURE <img src=x onerror="window.__injected=1"> '+('长文本仅用于表现层。'*50)),('PREVIEW_ONLY','PROGRAM_FIXTURE 仅预览'),('SUBMIT_AFTER_CONFIRMATION','PROGRAM_FIXTURE 已提交回执')]:
   task=service.create({'kind':'loan','execution_ceiling':scope,'confirmed':True,'facts':{'loan_start':str(today+timedelta(days=1)),'loan_end':str(today+timedelta(days=3)),'purpose':purpose}})
   evidence=service.policy(task['task_id']);service.store.observe(who,task['task_id'],'assets.search',{'status':'ok','data':service.assets(task['task_id'])})
   service.store.observe(who,task['task_id'],'tickets.list_mine',{'status':'ok','data':{'tickets':service.tickets(task['task_id'])}})
   proposal=service.store.propose(who,task['task_id'],'loan-laptop-1',[evidence['ref']]);tasks.append({'task_id':task['task_id'],'preview':proposal})
  third=tasks[2];third['final']=service.submit(third['task_id'],{'proposal_id':third['preview']['proposal_id'],
   'content_digest':third['preview']['content_digest'],'expected_facts_revision':1,'accepted':True})
  workspace.save_settings({'model_endpoint':'http://127.0.0.1:1'})
  record={'kind':'PROGRAM_FIXTURE_NOT_REAL_MODEL_TRAJECTORY','root':str(root),'tasks':tasks,'model_sends':0}
  (root/'logs/presentation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8');print(root)
 finally:await workspace.close()
asyncio.run(prepare())
