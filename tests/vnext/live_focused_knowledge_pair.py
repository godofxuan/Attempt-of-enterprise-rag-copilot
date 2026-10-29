"""Finite real pair after a source/need handoff change; every attempt is recorded."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import time
import httpx

parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8741')
parser.add_argument('--data-dir',default='.private/esa-vnext/demo-validation');parser.add_argument('--kb',required=True)
args=parser.parse_args();data=Path(args.data_dir)
question=json.loads(Path('tests/fixtures/vnext/knowledge_unit_handoff.json').read_text('utf8'))['question']
path=data/'logs'/('KNOWLEDGE_HANDOFF_PAIR_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
record={'kind':'REAL_LOCAL_KNOWLEDGE_PAIR_NOT_REPLAY','question':question,'kb_id':args.kb,
 'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'results':[]}
def count():
 with sqlite3.connect(data/'app.sqlite3') as db:return dict(db.execute('SELECT kind,COUNT(*) FROM model_calls GROUP BY kind'))
record['before']=count()
with httpx.Client(base_url=args.url,trust_env=False,timeout=20,headers={'X-ESA-Request':'1'}) as client:
 def post(url,value):
  response=client.post(url,json=value);response.raise_for_status();return response.json()
 def wait(run):
  for _ in range(245):
   state=client.get('/api/runs/'+run['id']).json()
   if state['status'] not in ('queued','running'):return state
   time.sleep(1)
  raise TimeoutError('Run did not finish within its bound')
 try:
  direct=wait(post('/api/knowledge/runs',{'kb_id':args.kb,'question':question}));record['results'].append({'entry':'RAG','run':direct})
  path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
  task=post('/api/tasks',{'request':{'kind':'knowledge','question':question,'execution_ceiling':'READ_ONLY','confirmed':True},'kb_id':args.kb})
  agent=wait(post('/api/tasks/'+task['task_id']+'/runs',{}));record['results'].append({'entry':'AGENT','run':agent})
 finally:
  record['after']=count();path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
 for row in record['results']:
  result=row['run'].get('result') or {};answer=result.get('knowledge_result',result).get('result',{})
  print(row['entry'],answer.get('mode'),answer.get('answer') or row['run'].get('error'))
 print(path)
