"""Bounded current local-model canary; no preselected model actions or business writes."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import time
import httpx

parser=argparse.ArgumentParser();parser.add_argument('--kb',required=True);args=parser.parse_args()
root=Path('.private/esa-vnext');output=root/'upgrade-030-040'/('S1_CANARY_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
record={'kind':'REAL_LOCAL_MODEL_NATIVE_CHOICES','commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'working_diff_paths':subprocess.check_output(['git','diff','--name-only'],text=True,encoding='utf8').splitlines(),'runs':[]}
def snapshot():
 with sqlite3.connect(root/'app.sqlite3') as db:
  return {'counts':dict(db.execute('SELECT kind,COUNT(*) FROM model_calls GROUP BY kind')),
   'highwater':db.execute('SELECT COALESCE(MAX(rowid),0) FROM model_calls').fetchone()[0],
   'business':{t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('tickets','it_repair_tickets','assets','repairs')}}
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,headers={'X-ESA-Request':'1'},timeout=15) as client:
 def post(path,data):
  r=client.post(path,json=data);r.raise_for_status();return r.json()
 def wait(run):
  for _ in range(245):
   result=client.get('/api/runs/'+run['id']).json()
   if result['status'] not in ('running','queued'):break
   time.sleep(1)
  record['runs'].append(result);output.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
  assert result['status']=='succeeded',result.get('error')
  return result['result']
 try:
  record['before']=snapshot()
  task=post('/api/tasks',{'request':{'kind':'repair','confirmed':True,'execution_ceiling':'PREVIEW_ONLY'},'kb_id':args.kb})
  first=wait(post('/api/tasks/'+task['task_id']+'/runs',{}))
  assert first['status']=='WAITING_USER' and set(first['missing_fields'])=={'asset_id','description','impact'}
  assert first['question'] and not first['active_run_id']
  text='我的设备是employee-laptop-1，屏幕一直闪烁，影响程度高。再告诉我临时电脑最长能借几天？'
  record['user_input']=text
  result=wait(post('/api/tasks/'+task['task_id']+'/messages',{'message_id':'canary-'+task['task_id'],
      'text':text,'expected_facts_revision':first['facts_revision']}))
  record['result']=result
  assert result['facts'].get('asset_id')=='employee-laptop-1' and result['facts'].get('impact')=='high'
  assert '闪烁' in result['facts'].get('description','')
  assert result['knowledge_result']['result']['sources'] and '14' in result['knowledge_result']['result']['answer']
  assert not result['pending_update'] and not result['active_run_id']
  record['functional_checks_passed']=True
 except BaseException as exc:
  record['failure']={'type':type(exc).__name__,'message':str(exc)};raise
 finally:
  record['after']=snapshot();record['business_unchanged']=record['before']['business']==record['after']['business']
  with sqlite3.connect(root/'app.sqlite3') as db:
   rows=db.execute('SELECT id,kind,status,elapsed_ms,error,input_json FROM model_calls WHERE rowid>? ORDER BY rowid',(record['before']['highwater'],)).fetchall()
  record['new_attempts']=[{'id':r[0],'kind':r[1],'status':r[2],'elapsed_ms':r[3],'error':r[4],
      'serialized_input_bytes':len(r[5].encode('utf8')),'options':json.loads(r[5]).get('options')} for r in rows]
  output.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
 print(json.dumps({'functional_checks_passed':record.get('functional_checks_passed'),'business_unchanged':record['business_unchanged'],
  'before':record['before']['counts'],'after':record['after']['counts'],'output':str(output)},ensure_ascii=False))
