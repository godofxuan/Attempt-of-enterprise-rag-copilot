"""Finite live journeys: shared knowledge, observed existing ticket and natural update."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import time
import httpx

folder=Path('.private/esa-vnext/logs')
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
path=folder/('M4_SHARED_BRANCH_'+stamp+'.json')
record={'kind':'LIVE_NATIVE_MODEL_NO_ORACLE','steps':[]}
def save():path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
with httpx.Client(base_url='http://127.0.0.1:8740',trust_env=False,timeout=20,headers={'X-ESA-Request':'1'}) as client:
    def post(url,data):
        response=client.post(url,json=data);response.raise_for_status();return response.json()
    def wait(run):
        for _ in range(260):
            result=client.get('/api/runs/'+run['id']).json()
            if result['status'] not in ('queued','running'):return result
            time.sleep(1)
        raise TimeoutError('Bounded run did not finish')
    kb=json.loads((folder/'M2_KNOWLEDGE_LIVE.json').read_text(encoding='utf8'))['kb_id']
    question='临时电脑借用的维修资格、期限、开始日期和未关闭申请数量有何限制？提交后是什么状态，是否代表已分配？押金如何规定？'
    direct=wait(post('/api/knowledge/runs',{'kb_id':kb,'question':question}))
    record['steps'].append({'entry':'independent_rag','question':question,'run':direct});save()
    task=post('/api/tasks',{'request':{'kind':'knowledge','execution_ceiling':'READ_ONLY','question':question,'confirmed':True},'kb_id':kb})
    agent=wait(post('/api/tasks/'+task['task_id']+'/runs',{}))
    record['steps'].append({'entry':'knowledge_agent','question':question,'run':agent});save()
    with sqlite3.connect('.private/esa-vnext/app.sqlite3') as db:before=db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]
    readonly=post('/api/tasks',{'request':{'kind':'loan','execution_ceiling':'READ_ONLY','confirmed':True}})
    message='开始日期是2026年11月1日，结束日期是2026年11月3日，用途是异地会议。只做查询，不准备或提交申请。'
    update=wait(post('/api/tasks/'+readonly['task_id']+'/messages',{'text':message,'message_id':'live-'+stamp,'expected_facts_revision':readonly['facts_revision']}))
    record['steps'].append({'entry':'natural_parameter_update','message':message,'run':update});save()
    branch=wait(post('/api/tasks/'+readonly['task_id']+'/runs',{}))
    with sqlite3.connect('.private/esa-vnext/app.sqlite3') as db:after=db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]
    record['steps'].append({'entry':'read_only_existing_application','run':branch,'tickets_before':before,'tickets_after':after});save()
    print(json.dumps({'record':str(path),'results':[(s['entry'],s['run']['status'],s['run'].get('error')) for s in record['steps']],'tickets_before':before,'tickets_after':after},ensure_ascii=False))
