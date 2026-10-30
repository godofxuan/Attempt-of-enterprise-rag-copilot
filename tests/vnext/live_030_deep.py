"""Finite real Deep/Fast journey in the existing DATA_DIR, never injected answers."""
import argparse,json,sqlite3,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
import httpx

parser=argparse.ArgumentParser();parser.add_argument('--kb');parser.add_argument('--deep-only',action='store_true');args=parser.parse_args()
root=Path('.private/esa-vnext');output=root/'upgrade-030-040'/('S2_DEEP_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
record={'kind':'REAL_LOCAL_RETRIEVAL_GENERATION_AND_PUBLISHER','commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'runs':[]}
def counts():
 with sqlite3.connect(root/'app.sqlite3') as db:return dict(db.execute('SELECT kind,COUNT(*) FROM model_calls GROUP BY kind'))
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,headers={'X-ESA-Request':'1'},timeout=20) as client:
 def post(path,data):
  r=client.post(path,json=data);r.raise_for_status();return r.json()
 def save():output.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
 def wait(run):
  for _ in range(245):
   current=client.get('/api/runs/'+run['id']).json()
   if current['status'] not in ('queued','running'):break
   time.sleep(1)
  record['runs'].append(current);save()
  assert current['status']=='succeeded',current.get('error')
  return current['result']
 try:
  record['before']=counts()
  if args.kb:kb=args.kb
  else:
   kb=post('/api/library',{'name':'0.3 规则来源与深入检索 TEST'})['id'];record['kb_id']=kb;save()
   record['samples']=post('/api/library/'+kb+'/samples',{})
   job=post('/api/library/'+kb+'/build',{});record['index_job']=job;save()
   for _ in range(180):
    built=next(j for j in client.get('/api/library').json()['jobs'] if j['id']==job['id'])
    if built['status'] not in ('QUEUED','RUNNING'):break
    time.sleep(1)
   record['built']=built;assert built['status']=='SUCCEEDED',built
  record['kb_id']=kb;save()
  question='请深入比较临时电脑借用和会议室预订的时长上限，并分别保留适用条件。'
  deep=wait(post('/api/knowledge/runs',{'kb_id':kb,'question':question,'detailed':True}))
  answer=deep['result'];record['deep']=deep
  strategy=answer['trace']['knowledge_strategy']
  assert strategy['strategy']=='planned_subquestions_with_anchored_reads'
  assert len(strategy['plan']['subquestions'])>=2 and len(strategy['evidence_table'])>=2
  assert len(strategy['opened_targets'])>=2
  assert len({s['doc_id'] for s in answer['sources']})>=2
  assert all(s['source_spans'] for s in answer['sources'])
  assert '14' in answer['answer'] and '2' in answer['answer'] and '小时' in answer['answer']
  assert '维修' in answer['answer'] and '09:00' in answer['answer'] and '18:00' in answer['answer']
  assert answer['mode']=='answered',answer['warnings']
  source=answer['sources'][0]
  excerpt=client.get('/api/documents/'+source['doc_id']+'/excerpt',params={'index_run_id':source['index_run_id'],
      'target_type':source['target_type'],'target_id':source['target_id']});excerpt.raise_for_status()
  record['actual_source_excerpt']=excerpt.json()
  if not args.deep_only:
   unknown=wait(post('/api/knowledge/runs',{'kb_id':kb,'question':'这些资料是否规定了跨国运送临时电脑的运费金额和支付责任？','detailed':False}))
   record['unknown']=unknown
   assert unknown['result']['trace']['knowledge_strategy']['strategy']=='fast_shared_runner'
   assert unknown['result']['mode']!='answered'
  else:record['unknown_scope']='NOT_REPEATED_KNOWN_FAILED: prior wrong-attribute negative answer retained; not part of this Deep-only result.'
  record['necessary_checks_passed']=True
 except BaseException as exc:record['failure']={'type':type(exc).__name__,'message':str(exc)};raise
 finally:record['after']=counts();save()
 print(json.dumps({'necessary_checks_passed':record.get('necessary_checks_passed'),'before':record['before'],'after':record['after'],
  'kb_id':kb,'deep_mode':record.get('deep',{}).get('result',{}).get('mode'),'unknown_mode':record.get('unknown',{}).get('result',{}).get('mode'),'output':str(output)},ensure_ascii=False))
