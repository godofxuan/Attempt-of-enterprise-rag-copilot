"""Measured rebuild reuse on unchanged documents; no inference-quality claim."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import time
import httpx

folder=Path('.private/esa-vnext/logs');stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
kb=json.loads((folder/'M2_KNOWLEDGE_LIVE.json').read_text(encoding='utf8'))['kb_id']
path=folder/('M8_CACHE_'+stamp+'.json');record={'kind':'REAL_INDEX_EMBEDDING_REUSE_NOT_QA_SCORE','builds':[]}
def count():
    with sqlite3.connect('.private/esa-vnext/app.sqlite3') as db:
        return db.execute("SELECT COUNT(*) FROM model_calls WHERE kind='embed'").fetchone()[0]
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,timeout=20,headers={'X-ESA-Request':'1'}) as client:
    for _ in range(2):
        before=count();started=time.monotonic();response=client.post('/api/library/'+kb+'/build',json={});response.raise_for_status();job=response.json()
        for __ in range(160):
            state=next(j for j in client.get('/api/library').json()['jobs'] if j['id']==job['id'])
            if state['status'] not in ('QUEUED','RUNNING'):break
            time.sleep(.2)
        record['builds'].append({'job':state,'embedding_attempts':count()-before,'wall_seconds':round(time.monotonic()-started,3)})
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        if state['status']!='SUCCEEDED':break
    print(json.dumps(record,ensure_ascii=False))
