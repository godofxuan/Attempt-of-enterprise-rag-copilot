"""One real local product journey. No injected answers, retrieval or model decisions."""
import json
from pathlib import Path
import time
import httpx

root=Path('.private/esa-vnext/logs');root.mkdir(parents=True,exist_ok=True)
with httpx.Client(base_url='http://127.0.0.1:8740',headers={'X-ESA-Request':'1'},trust_env=False,timeout=290) as client:
    kb=client.post('/api/library',json={'name':'合成服务说明（vNext冒烟）'}).json()['id']
    docs={'loan.md':'# 合成电脑借用制度\n\n只有存在有效维修记录的员工可以申请临时电脑。借用期限为1至14天，开始日期不得早于申请当天。同一员工只能有一个未关闭的借用申请。提交后工单为待审批；待审批不等于已批准、已分配或已预留。该制度没有规定押金。\n',
          'meeting.md':'# 合成会议室规则\n\n会议室每日开放时间为09:00至18:00。每次预订不得超过2小时。使用结束后必须清理桌面并关闭设备。\n'}
    uploads=[]
    for name,text in docs.items():
        response=client.post(f'/api/library/{kb}/documents',files={'file':(name,text.encode('utf8'))});response.raise_for_status();uploads.append(response.json())
    job=client.post(f'/api/library/{kb}/build',json={}).json()
    for _ in range(150):
        state=next(j for j in client.get('/api/library').json()['jobs'] if j['id']==job['id'])
        if state['status'] not in ('QUEUED','RUNNING'):break
        time.sleep(1)
    record={'kb_id':kb,'uploads':uploads,'job':state,'kind':'LIVE_LOCAL_PRODUCT_NOT_HISTORICAL_REACCEPTANCE'}
    (root/'M2_KNOWLEDGE_LIVE.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    assert state['status']=='SUCCEEDED',state
    started=time.monotonic()
    answer=client.post('/api/knowledge/ask',json={'kb_id':kb,'question':'临时电脑借用的资格、期限和申请限制是什么？'})
    record.update(status_code=answer.status_code,result=answer.json(),wall_seconds=round(time.monotonic()-started,3))
    (root/'M2_KNOWLEDGE_LIVE.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(record,ensure_ascii=False))
