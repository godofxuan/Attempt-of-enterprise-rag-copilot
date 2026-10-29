"""Finite actual-model check of host-revalidated observations after an independent field edit."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import time
import httpx

root=Path('.private/esa-vnext');record={'kind':'REAL_MODEL_OBSERVATION_REUSE_READONLY_NOT_NEW_BUSINESS','runs':[]}
path=root/'logs'/('READ_REUSE_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
def snapshot():
 with sqlite3.connect(root/'app.sqlite3') as db:
  return {table:db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in ('tickets','it_repair_tickets','repairs')}
def calls():
 with sqlite3.connect(root/'app.sqlite3') as db:return db.execute("SELECT COUNT(*) FROM model_calls WHERE kind='chat'").fetchone()[0]
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,headers={'X-ESA-Request':'1'},timeout=20) as client:
 def post(url,data):
  response=client.post(url,json=data);response.raise_for_status();return response.json()
 def run(identifier):
  before=calls();started=post('/api/tasks/'+identifier+'/runs',{})
  for _ in range(245):
   state=client.get('/api/runs/'+started['id']).json()
   if state['status'] not in ('queued','running'):break
   time.sleep(1)
  with sqlite3.connect(root/'app.sqlite3') as db:
   rows=db.execute("SELECT data FROM run_events WHERE run_id=? AND kind='tool_result' ORDER BY seq",(started['id'],)).fetchall()
  return {'run':state,'chat_attempts':calls()-before,'tool_names':[json.loads(r[0])['tool'] for r in rows]}
 try:
  record['before']=snapshot();task=post('/api/tasks',{'request':{'kind':'repair','execution_ceiling':'READ_ONLY','confirmed':True,
    'facts':{'asset_id':'employee-laptop-1','description':'只读查看设备与报修','impact':'medium'}}});record['task_id']=task['task_id']
  record['runs'].append(run(task['task_id']));current=client.get('/api/tasks/'+task['task_id']).json()
  response=client.patch('/api/tasks/'+task['task_id']+'/facts',json={'expected_facts_revision':current['facts_revision'],'changes':{'description':'仅更正备注，仍只读查询'}});response.raise_for_status()
  record['runs'].append(run(task['task_id']));record['after']=snapshot()
  record['both_correct']=all(r['run']['status']=='succeeded' and r['run']['result']['outcome']['goal_satisfied'] for r in record['runs'])
  record['observed_reuse']=not record['runs'][1]['tool_names']
  record['retained_read_tools']=sorted(set(record['runs'][0]['tool_names'])-set(record['runs'][1]['tool_names']))
  record['business_unchanged']=record['before']==record['after']
 finally:path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({key:record.get(key) for key in ('task_id','both_correct','observed_reuse','business_unchanged')},ensure_ascii=False))
print([(r['chat_attempts'],r['tool_names']) for r in record['runs']]);print(path)
