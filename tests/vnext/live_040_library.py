"""Finite real batch/cache, version lifecycle and exact-source journey; synthetic docs."""
import json,sqlite3,time,subprocess,os
from pathlib import Path
from datetime import datetime,timezone
import httpx

root=Path('.private/esa-vnext');out=root/'upgrade-030-040'/('S4_LIBRARY_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
resume=os.getenv('ESA_RESUME_LIBRARY')
record={**(json.loads(Path(resume).read_text('utf8')) if resume else {}),'resumed_from':resume,'kind':'REAL_LOCAL_BATCH_EMBEDDING_RETRIEVAL_VERSION_JOURNEY','commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()}
def save():out.write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
def calls():
 with sqlite3.connect(root/'app.sqlite3') as d:return [{'id':r[0],'kind':r[1],'purpose':r[2],'status':r[3],
  'input_texts':len(json.loads(r[4]).get('input',[])) if r[1]=='embed' else None,'elapsed_ms':r[5]}
  for r in d.execute('SELECT id,kind,purpose,status,input_json,elapsed_ms FROM model_calls ORDER BY rowid')]
with httpx.Client(base_url='http://127.0.0.1:8740',headers={'X-ESA-Request':'1'},timeout=20,trust_env=False) as c:
 def post(path,payload):
  r=c.post(path,json=payload);r.raise_for_status();return r.json()
 def build(kb):
  started=time.monotonic();job=post('/api/library/'+kb+'/build',{})
  for _ in range(180):
   row=next(j for j in c.get('/api/library').json()['jobs'] if j['id']==job['id'])
   if row['status'] not in ('QUEUED','RUNNING'):break
   time.sleep(1)
  assert row['status']=='SUCCEEDED',row
  return {'elapsed_seconds':round(time.monotonic()-started,3),'job':row}
 def ask(kb):
  run=post('/api/knowledge/runs',{'kb_id':kb,'question':'《本地资料导入示例1》中，处理时限是多少？'})
  for _ in range(240):
   r=c.get('/api/runs/'+run['id']).json()
   if r['status'] not in ('queued','running'):break
   time.sleep(1)
  assert r['status']=='succeeded',r
  return r['result']
 try:
  if not resume:
   record['before']=calls();kb=post('/api/library',{'name':'批量索引与版本 TEST'})['id'];record['kb_id']=kb;save()
   files=[('files',(f'example-{i}.md',f'# 本地资料导入示例{i}\n\n仅用于合成测试，不是企业制度。\n该示例规定处理时限为{23+i}小时，提交时必须附上设备编号。\n'.encode(),'text/markdown')) for i in range(1,9)]
   r=c.post('/api/library/'+kb+'/documents/batch',files=files);r.raise_for_status();record['uploaded']=r.json();save()
   assert len(record['uploaded']['documents'])==8
   record['cold']=build(kb);record['after_cold']=calls();save()
   record['warm']=build(kb);record['after_warm']=calls();save()
   fresh=record['after_cold'][len(record['before']):];assert sum(x['input_texts'] or 0 for x in fresh if x['purpose']=='index_embedding')==8
   assert len([x for x in fresh if x['purpose']=='index_embedding'])==1
   assert len(record['after_warm'])==len(record['after_cold'])
   first=ask(kb);record['v1_answer']=first;save();assert '24' in first['result']['answer'] and first['result']['sources']
   r=c.post('/api/library/'+kb+'/documents/batch',files=[('files',('example-1.md','# 本地资料导入示例1\n\n仅用于合成测试，不是企业制度。\n该示例规定处理时限为72小时，提交时必须附上设备编号。\n'.encode(),'text/markdown'))]);r.raise_for_status();new=r.json()['documents'][0];record['replacement']=new;save()
   record['v2_build']=build(kb);second=ask(kb);record['v2_answer']=second;save()
   assert '72' in second['result']['answer'] and new['id'] in {s['doc_id'] for s in second['result']['sources']}
  else:
   kb=record['kb_id'];first=record['v1_answer'];second=record['v2_answer'];new=record['replacement']
  record['answer_quality']={'v1':first['result']['mode'],'v2':second['result']['mode'],'note':'Partial cross-document conflict output is NOT a content-quality pass; lifecycle and batch checks are separate.'}
  old=next(d for d in record['uploaded']['documents'] if d['name']=='example-1.md')
  source=next(s for s in first['result']['sources'] if s['doc_id']==old['id']);r=c.get('/api/documents/'+source['doc_id']+'/excerpt',params={k:source[k] for k in ('index_run_id','target_type','target_id')});r.raise_for_status();record['historical_source']=r.json();assert '24' in r.json()['text']
  r=c.patch('/api/documents/'+new['id'],json={'active':False});r.raise_for_status();record['disabled']=r.json();record['disable_build']=build(kb)
  r=c.patch('/api/documents/'+new['id'],json={'active':True});r.raise_for_status();record['restored']=r.json();record['restore_build']=build(kb)
  record.pop('failure',None);record['passed']=True
 except BaseException as e:record['failure']={'type':type(e).__name__,'message':str(e)};raise
 finally:record['after']=calls();save()
 print(json.dumps({'passed':record.get('passed'),'cold_seconds':record.get('cold',{}).get('elapsed_seconds'),'warm_seconds':record.get('warm',{}).get('elapsed_seconds'),'output':str(out)},ensure_ascii=False))
