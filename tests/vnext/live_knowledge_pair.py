"""One finite live pair on the previously recorded question after a documented repair."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time
import httpx

folder=Path('.private/esa-vnext/logs')
prior=json.loads((folder/'M4_SHARED_BRANCH_20261029T182938.json').read_text(encoding='utf8'))
question=prior['steps'][0]['question']
kb=json.loads((folder/'M2_KNOWLEDGE_LIVE.json').read_text(encoding='utf8'))['kb_id']
path=folder/('M2_KNOWLEDGE_PAIR_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.json')
record={'kind':'LIVE_LOCAL_SHARED_KNOWLEDGE','question':question,
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'results':[]}
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,timeout=20,headers={'X-ESA-Request':'1'}) as client:
    def post(url,data):
        response=client.post(url,json=data);response.raise_for_status();return response.json()
    def wait(run):
        for _ in range(250):
            state=client.get('/api/runs/'+run['id']).json()
            if state['status'] not in ('queued','running'):return state
            time.sleep(1)
        raise TimeoutError('Run did not terminate')
    direct=wait(post('/api/knowledge/runs',{'kb_id':kb,'question':question}))
    record['results'].append({'entry':'RAG','run':direct})
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    task=post('/api/tasks',{'request':{'kind':'knowledge','execution_ceiling':'READ_ONLY','question':question,'confirmed':True},'kb_id':kb})
    agent=wait(post('/api/tasks/'+task['task_id']+'/runs',{}))
    record['results'].append({'entry':'AGENT','run':agent})
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(str(path))
    for row in record['results']:
        value=row['run'].get('result') or {};answer=value.get('knowledge_result',value).get('result',{})
        print(row['entry'],row['run']['status'],answer.get('mode'),answer.get('answer') or row['run'].get('error'))
