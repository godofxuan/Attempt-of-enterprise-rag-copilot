"""Reproduce/verify the missing-KB recovery using current HTTP API and real SQLite.
Only the external model selection/answer are scripted. Never uses user data.
"""
import json,os
from pathlib import Path
from probe_support import product,H,Model,wait,ServiceError,local_actor


def run_case(already_selected=False):
    with product() as (c,w):
        task=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True})
        cid=task['conversation_id'];tid=task['task_id'];mid='scope-recovery';text='先解释借用期限，不生成预览。';calls=[]
        async def answer(k,q,**kw):
            calls.append({'kb_id':k,'question':q,'detailed':kw.get('detailed')})
            if not k:raise ServiceError('KNOWLEDGE_BASE_REQUIRED')
            w.library.require(k)
            return {'id':'audit-synth-answer','kb_id':k,'question':q,'conversation_id':cid,'result':{'mode':'not_found','answer':'合成知识响应，仅验证路由恢复。','sources':[]}}
        w.library.answer=answer
        w.models.chat=Model([('update_parameters',{'changes':{},'turn_request':{'preview':False,'knowledge_quote':'借用期限'}})], [('finish',{})]).chat
        sent=c.post(f'/api/conversations/{cid}/turns',headers=H,json={'message_id':mid,'text':text,'detailed':True})
        first=wait(c,sent.json()['id'])
        initial=next(x for x in w.conversations.turns(cid) if x['id']==mid)
        selected=w.library.create('审核合成知识库')['id']
        if already_selected:
            # Exact persisted old-state shape; normal PATCH below is under test.
            with w.conversations.db() as db:db.execute('UPDATE conversations SET kb_id=? WHERE id=?',(selected,cid))
        bound=c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':selected})
        cmd=w.conversations.command({'conversation_id':cid,'message_id':mid,'text':text})
        resumed=c.post(f'/api/product/conversations/{cid}/turns/{mid}/retry',headers=H,json={})
        result=wait(c,resumed.json()['id']) if resumed.status_code==202 else None
        final=next(x for x in w.conversations.turns(cid) if x['id']==mid)
        return {'scenario':'previously_selected_but_request_null' if already_selected else 'select_after_partial',
          'initial_run':first['status'],'initial_turn':initial['status'],
          'bind_http':bound.status_code,'selected_kb_id':selected,'saved_request_kb_id':cmd['kb_id'],
          'request_detailed':cmd['detailed'],'retry_http':resumed.status_code,
          'retry_run_status':result['status'] if result else None,'retry_error':result.get('error') if result else resumed.json(),
          'final_turn':final['status'],'external_answer_calls':calls,
          'facts_unchanged':w.service.view(tid)['facts']==task['facts'],
          'preview':bool(w.service.view(tid)['preview']),'ticket_count':len(w.service.store.list_tickets(local_actor()))}

if __name__=='__main__':
    report={'external_only_doubles':True,'scenarios':[run_case(False),run_case(True)]}
    p=Path(os.environ.get('ESA_PROBE_OUT','missing_scope_result.json'));p.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
