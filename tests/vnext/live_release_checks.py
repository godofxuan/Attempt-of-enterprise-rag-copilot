"""Final bounded checks after the generation-output contract correction."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse,json,sqlite3,subprocess,time
import httpx

parser=argparse.ArgumentParser();parser.add_argument('--kb',required=True);parser.add_argument('--knowledge-only',action='store_true');args=parser.parse_args()
root=Path('.private/esa-vnext');path=root/'logs'/('FINAL_LIVE_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
record={'kind':'REAL_LOCAL_FROZEN_RELEASE_CHECKS','code_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'runs':[]}
def state():
 with sqlite3.connect(root/'app.sqlite3') as db:return {'calls':dict(db.execute('SELECT kind,COUNT(*) FROM model_calls GROUP BY kind')),
  'business':{t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('tickets','it_repair_tickets','repairs')}}
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,headers={'X-ESA-Request':'1'},timeout=20) as client:
 def post(url,data):
  response=client.post(url,json=data);response.raise_for_status();return response.json()
 def run(started):
  for _ in range(245):
   result=client.get('/api/runs/'+started['id']).json()
   if result['status'] not in ('queued','running'):break
   time.sleep(1)
  record['runs'].append(result);path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
  assert result['status']=='succeeded',result.get('error');return result['result']
 try:
  assert client.get('/api/status').json()['mode']=='SYNTHETIC_LOCAL'
  record['before']=state();record['question']='比较临时电脑借用与会议室预订的时长上限，分别有哪些适用条件？'
  direct=run(post('/api/knowledge/runs',{'kb_id':args.kb,'question':record['question'],'detailed':True}))
  task=post('/api/tasks',{'request':{'kind':'knowledge','question':record['question'],'execution_ceiling':'READ_ONLY','confirmed':True},'kb_id':args.kb})
  agent=run(post('/api/tasks/'+task['task_id']+'/runs',{}))['knowledge_result']
  record['knowledge']={'RAG':direct,'AGENT':agent}
  for answer in (direct['result'],agent['result']):
   assert answer['mode']=='answered',answer.get('warnings')
   assert len({s['doc_id'] for s in answer['sources']})>=2
   assert '14' in answer['answer'] and '天' in answer['answer'] and '2' in answer['answer'] and '小时' in answer['answer']
   assert '维修' in answer['answer']
  if not args.knowledge_only:
   today=datetime.now(ZoneInfo('Asia/Shanghai')).date();start=str(today+timedelta(days=1));end=str(today+timedelta(days=3));changed=str(today+timedelta(days=4))
   loan=post('/api/tasks',{'request':{'kind':'loan','execution_ceiling':'READ_ONLY','confirmed':True,
    'facts':{'loan_start':start,'loan_end':end,'purpose':'本地合成参数检查'}}})
   updated=run(post('/api/tasks/'+loan['task_id']+'/messages',{'expected_facts_revision':loan['facts_revision'],
    'message_id':'release-'+loan['task_id'],'text':f'结束日期改到{changed}，用途改为“异地会议”，其余不变。'}))
   assert updated['facts']=={'loan_start':start,'loan_end':changed,'purpose':'异地会议'}
   assert updated['user_execution_ceiling']=='READ_ONLY' and updated['pending_proposal_id'] is None
   record['loan_update']=updated
  record['after']=state();assert record['before']['business']==record['after']['business']
  with sqlite3.connect(root/'app.sqlite3') as db:
   row=db.execute("SELECT input_json FROM model_calls WHERE kind='chat' AND input_json LIKE '%request_coverage%' ORDER BY rowid DESC LIMIT 1").fetchone()
  record['generation_options']=json.loads(row[0])['options'];assert record['generation_options']['num_predict']==1024
  record['necessary_checks_passed']=True
 finally:path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
 for name,answer in record.get('knowledge',{}).items():print(name,answer['result']['mode'],answer['result']['answer'])
 print(json.dumps({'necessary_checks_passed':record.get('necessary_checks_passed'),'generation_options':record.get('generation_options'),'path':str(path)},ensure_ascii=False))
