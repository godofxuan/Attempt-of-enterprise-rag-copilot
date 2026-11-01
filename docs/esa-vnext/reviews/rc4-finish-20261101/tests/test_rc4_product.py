"""Current packaged app tests: real API/SQLite, only external LLM replaced.
No private data, no Windows/real-model claim. See audit evidence for scope.
"""
import json, asyncio
from datetime import timedelta
import pytest
from probe_support import product,loan,H,Model,wait,post_turn,ServiceError,local_actor


def turn(w,cid,mid):
    return next(t for t in w.conversations.turns(cid) if t['id']==mid)

def send(c,cid,mid,text,detailed=False):
    r=c.post(f'/api/conversations/{cid}/turns',headers=H,json={'text':text,'message_id':mid,'detailed':detailed})
    assert r.status_code==202,r.text
    return wait(c,r.json()['id'])

def retry(c,cid,mid):
    r=c.post(f'/api/product/conversations/{cid}/turns/{mid}/retry',headers=H,json={})
    assert r.status_code==202,r.text
    return wait(c,r.json()['id'])

def knowledge_model(w,quote,preview=False):
    m=Model([('update_parameters',{'changes':{},'turn_request':{'preview':preview,'knowledge_quote':quote}})], [('knowledge_answer',{'question':quote})],[('finish',{})]);w.models.chat=m.chat;return m

def fake_answer(kb,question,**kwargs):
    return {'id':'synth-answer','question':question,'kb_id':kb,'conversation_id':kwargs.get('conversation_id'),'result':{'mode':'not_found','answer':'合成恢复响应（不是模型质量结果）','sources':[]}}

@pytest.mark.parametrize('fail_count',[1,2,3])
def test_knowledge_only_retries_keep_deep_and_empty_business_fields(fail_count):
    with product() as(c,w):
        kb=w.library.create('合成政策库')['id'];t=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True},kb_id=kb)
        tid,cid=t['task_id'],t['conversation_id'];calls=[]
        async def answer(k,q,**kw):
            calls.append((k,q,kw))
            if len(calls)<=fail_count:raise ServiceError('TRANSIENT_TOOL_FAILURE')
            return fake_answer(k,q,**kw)
        w.library.answer=answer;m=knowledge_model(w,'借用期限')
        send(c,cid,'konly','先解释借用期限，不准备申请。',True)
        for i in range(fail_count):
            current=turn(w,cid,'konly');assert current['status'] in {'PARTIAL','FAILED'}
            assert w.conversations.coordinator.result('konly',w.service.view(tid))['retryable']
            retry(c,cid,'konly')
        assert turn(w,cid,'konly')['status']=='DONE'
        assert all(k==kb and q=='借用期限' and kw['detailed'] is True for k,q,kw in calls)
        task=w.service.view(tid);assert not task['facts'].get('loan_start') and not task['preview'] and not task['receipt']
        assert not task.get('pending_user_update')
        assert len(m.calls)==3
        assert len(w.service.store.list_tickets(local_actor()))==0


def test_mixed_incomplete_preview_does_not_block_independent_knowledge():
    with product() as(c,w):
        kb=w.library.create('混合问题库')['id'];t=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True},kb_id=kb)
        tid,cid=t['task_id'],t['conversation_id'];calls=[]
        async def answer(k,q,**kw):
            calls.append(1)
            if len(calls)==1:raise ServiceError('TRANSIENT_TOOL_FAILURE')
            return fake_answer(k,q,**kw)
        w.library.answer=answer;knowledge_model(w,'借用期限',preview=True)
        send(c,cid,'mixed','解释借用期限并准备预览。')
        first=w.conversations.coordinator.result('mixed',w.service.view(tid))
        assert set(first['pending'])=={'knowledge','preview'}
        assert 'loan_start' in first['items']['preview']['blocked_by']
        assert first['action_kind']=='retry_knowledge'
        retry(c,cid,'mixed')
        after=w.conversations.coordinator.result('mixed',w.service.view(tid))
        assert after['pending']==['preview'] and after['status']=='waiting_input'
        now=w.service.view(tid);day=w.service.store.today()
        saved=c.patch(f'/api/product/tasks/{tid}/facts',headers=H,json={'changes':{'loan_start':str(day+timedelta(days=1)),'loan_end':str(day+timedelta(days=3)),'purpose':'合成开发测试'},'expected_facts_revision':now['facts_revision']})
        assert saved.status_code==200,saved.text
        p=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':saved.json()['revision']})
        assert p.status_code==200,p.text
        assert turn(w,cid,'mixed')['status']=='DONE'
        assert len(calls)==2 and not w.service.view(tid)['receipt']


def test_legacy_waiting_knowledge_turn_can_retry():
    with product() as(c,w):
        kb=w.library.create('旧状态恢复')['id'];t=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True},kb_id=kb)
        cid=t['conversation_id'];calls=[]
        async def answer(k,q,**kw):
            calls.append(1)
            if len(calls)==1:raise ServiceError('TRANSIENT_TOOL_FAILURE')
            return fake_answer(k,q,**kw)
        w.library.answer=answer;knowledge_model(w,'期限')
        send(c,cid,'old','请解释期限。')
        with w.conversations.db() as db:db.execute("UPDATE conversation_turns SET status='WAITING_USER' WHERE id='old'")
        assert retry(c,cid,'old')['status']=='succeeded'
        assert turn(w,cid,'old')['status']=='DONE'


def test_task_pages_search_and_old_answer_details():
    with product() as(c,w):
        ids=[]
        for i in range(55):
            t=w.service.create({'kind':'loan','execution_ceiling':'READ_ONLY','confirmed':True,'facts':{'purpose':f'唯一历史用例{i:03d}'}});ids.append(t['task_id'])
        all_ids=[];cursor=None;sizes=[]
        while True:
            params={'limit':20}
            if cursor is not None:params['cursor']=cursor
            r=c.get('/api/product/tasks/page',params=params);assert r.status_code==200,r.text
            data=r.json();sizes.append(len(data['items']));all_ids.extend(x['id'] for x in data['items'])
            cursor=data['next_cursor']
            if cursor is None:break
        assert sizes==[20,20,15] and len(set(all_ids))==55 and set(ids)==set(all_ids)
        r=c.get('/api/product/tasks/page',params={'q':'唯一历史用例000'});assert [x['id'] for x in r.json()['items']]==[ids[0]]
        assert c.get('/api/product/tasks/page',params={'limit':0}).status_code==422
        assert c.get('/api/product/tasks/page',params={'cursor':-1}).status_code==422
        with w.library.db() as db:
            for i in range(55):db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES(?,?,?,?,?,?)',(f'old{i}','conv','kb',f'问题{i}',json.dumps({'mode':'not_found','answer':'合成答案','sources':[]}), 'g'))
        assert c.get('/api/product/answers/old0').status_code==200
        assert c.get('/api/product/answers/old54').status_code==200
        assert c.get('/api/product/answers/absent').status_code==409


def test_expired_preview_read_regenerate_and_old_confirmation():
    with product() as(c,w):
        t=loan(w);tid=t['task_id'];r=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':t['facts_revision']})
        assert r.status_code==200,r.text
        row=r.json();p=row['preview'];clock=w.service.store.clock
        w.service.store.clock=lambda:p['expires_at']-0.01
        before=c.get(f'/api/product/tasks/{tid}').json();assert before['can_submit'] and before['preview_state']=='current'
        w.service.store.clock=lambda:p['expires_at']
        at=c.get(f'/api/product/tasks/{tid}').json();assert not at['can_submit'] and at['preview_state']=='expired' and at['next_action']['kind']=='prepare'
        regen=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'expected_facts_revision':row['revision']});assert regen.status_code==200,regen.text
        new=regen.json();assert new['preview']['proposal_id']!=p['proposal_id'] and new['can_submit']
        old_payload={'proposal_id':p['proposal_id'],'content_digest':p['content_digest'],'accepted':True,'expected_facts_revision':row['revision']}
        assert c.post(f'/api/tasks/{tid}/submit',headers=H,json=old_payload).status_code==409
        payload={'proposal_id':new['preview']['proposal_id'],'content_digest':new['preview']['content_digest'],'accepted':True,'expected_facts_revision':new['revision']}
        a=c.post(f'/api/tasks/{tid}/submit',headers=H,json=payload);b=c.post(f'/api/tasks/{tid}/submit',headers=H,json=payload)
        assert a.status_code==b.status_code==200 and a.json()['receipt']==b.json()['receipt']
        assert len(w.service.store.list_tickets(local_actor()))==1


def test_empty_conversation_bind_kb_and_retry():
    with product() as(c,w):
        cid=w.conversations.create()['id'];calls=[]
        async def answer(k,q,**kw):calls.append(k);return fake_answer(k,q,**kw)
        w.library.answer=answer
        assert send(c,cid,'pure','请解释期限')['status']=='failed'
        kb=w.library.create('补入资料库')['id'];r=c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':kb});assert r.status_code==200
        assert retry(c,cid,'pure')['status']=='succeeded'
        assert calls==[kb] and turn(w,cid,'pure')['status']=='DONE'


def test_running_task_and_stale_edit_rules():
    with product() as(c,w):
        t=loan(w);tid=t['task_id'];rev=t['facts_revision']
        a=c.patch(f'/api/product/tasks/{tid}/facts',headers=H,json={'changes':{'purpose':'A页面新用途'},'expected_facts_revision':rev});assert a.status_code==200
        b=c.patch(f'/api/product/tasks/{tid}/facts',headers=H,json={'changes':{'purpose':'B页面旧用途'},'expected_facts_revision':rev});assert b.status_code==409
        assert w.service.view(tid)['facts']['purpose']=='A页面新用途'
        for i in range(5):
            row=w.service.view(tid)
            change=c.patch(f'/api/product/tasks/{tid}/facts',headers=H,json={'changes':{'purpose':f'第{i}次有效修改'},'expected_facts_revision':row['facts_revision']});assert change.status_code==200
            p=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':change.json()['revision']});assert p.status_code==200,p.text


@pytest.mark.parametrize('ceiling',['READ_ONLY','PREVIEW_ONLY'])
def test_scope_no_accidental_submission(ceiling):
    with product() as(c,w):
        t=loan(w,ceiling);tid=t['task_id'];p=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':t['facts_revision']})
        if ceiling=='READ_ONLY':assert p.status_code==409
        else:
            assert p.status_code==200
            v=p.json();assert not v['can_submit']
            s=c.post(f'/api/tasks/{tid}/submit',headers=H,json={'proposal_id':v['preview']['proposal_id'],'content_digest':v['preview']['content_digest'],'accepted':True,'expected_facts_revision':v['revision']});assert s.status_code==409
        assert not w.service.store.list_tickets(local_actor())


def test_partial_service_turn_bind_new_kb_retains_original_request():
    """Expected normal recovery; currently suspected to fail for PARTIAL turns."""
    with product() as(c,w):
        t=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True});cid=t['conversation_id'];calls=[]
        async def answer(k,q,**kw):
            calls.append(k)
            if k is None:raise ServiceError('KNOWLEDGE_BASE_REQUIRED')
            w.library.require(k)
            return fake_answer(k,q,**kw)
        w.library.answer=answer
        m=Model([('update_parameters',{'changes':{},'turn_request':{'preview':False,'knowledge_quote':'借用期限'}})], [('finish',{})]);w.models.chat=m.chat
        send(c,cid,'late-kb','先解释借用期限，不生成预览。')
        assert turn(w,cid,'late-kb')['status']=='PARTIAL'
        kb=w.library.create('后来选择的资料库')['id'];r=c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':kb});assert r.status_code==200,r.text
        run=retry(c,cid,'late-kb')
        assert run['status']=='succeeded',{'run':run,'command':w.conversations.command({'conversation_id':cid,'message_id':'late-kb','text':'先解释借用期限，不生成预览。'}),'calls':calls}
        assert calls==[kb]


def test_completing_kb_does_not_rewrite_finished_request_or_existing_scope():
    with product() as(c,w):
        first=w.library.create('原资料范围')['id'];second=w.library.create('新资料范围')['id']
        cid=w.conversations.create(first)['id'];calls=[]
        async def answer(k,q,**kw):
            calls.append(k)
            if len(calls)==1:raise ServiceError('TRANSIENT_TOOL_FAILURE')
            return fake_answer(k,q,**kw)
        w.library.answer=answer
        send(c,cid,'scope-fixed','测试原问题',True)
        c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':second})
        assert retry(c,cid,'scope-fixed')['status']=='succeeded'
        assert calls==[first,first]
        before=w.conversations.command({'conversation_id':cid,'message_id':'scope-fixed','text':'测试原问题'})
        c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':first})
        assert w.conversations.command({'conversation_id':cid,'message_id':'scope-fixed','text':'测试原问题'})==before


def test_document_parsing_version_duplicate_and_failed_replacement():
    with product() as(c,w):
        kb=w.library.create('文档解析验证')['id']
        first=c.portal.call(w.library.upload,kb,'制度.md','# 借用制度\n\n单次借用最长14天。\n'.encode())
        same=c.portal.call(w.library.upload,kb,'制度.md','# 借用制度\n\n单次借用最长14天。\n'.encode())
        assert first['id']==same['id'] and first['status']=='PARSED'
        second=c.portal.call(w.library.upload,kb,'制度.md','# 借用制度\n\n单次借用最长7天。\n'.encode())
        assert second['id']!=first['id'] and second['status']=='PARSED'
        bad=c.portal.call(w.library.upload,kb,'制度.md',b'\xff\xfe\x80')
        assert bad['status']=='FAILED'
        with w.library.db() as db:
            docs={x['id']:dict(x) for x in db.execute('SELECT * FROM library_documents')}
        assert docs[first['id']]['active']==0 and docs[second['id']]['active']==1 and docs[second['id']]['version']==2
        assert docs[bad['id']]['active']==0
        d=c.get('/api/documents/'+second['id']);assert d.status_code==200 and '7天' in d.text
        w.library.update_document(second['id'],{'active':False})
        with w.library.db() as db:
            assert db.execute('SELECT withdrawn FROM library_documents WHERE id=?',(second['id'],)).fetchone()[0]==1
        w.library.update_document(second['id'],{'active':True})
        with w.library.db() as db:
            assert db.execute('SELECT active FROM library_documents WHERE id=?',(second['id'],)).fetchone()[0]==1


def test_home_settings_assets_and_no_model():
    with product() as(c,w):
        r=c.get('/');assert r.status_code==200 and '/ui/assets/' in r.text
        import re
        for asset in re.findall(r'(?:src|href)="(/ui/assets/[^\"]+)"',r.text):
            assert c.get(asset).status_code==200
        status=c.get('/api/status');assert status.status_code==200 and status.json()['storage']
        assert not status.json()['chat']['ready']
        assert c.get('/api/settings').status_code==200
        import subprocess
        from probe_support import SRC
        build=SRC/'app'/'resources'/'build.json'
        expected_commit=json.loads(build.read_text('utf-8'))['source_commit'] if build.is_file() else subprocess.check_output(['git','rev-parse','HEAD'],cwd=SRC,text=True).strip()
        instance=c.get('/api/instance').json();assert instance['version']=='0.7.0rc4' and instance['source_commit']==expected_commit
        assert c.get('/health/ready').json()['storage'] is True


def test_moved_workspace_does_not_create_new_empty_database(tmp_path):
    from probe_support import initialize
    from app.launcher.core import remember,open_workspace,selected_workspace
    old=tmp_path/'中文 原工作区';initialize(old,sample=True);registry=tmp_path/'registry.json'
    remember(old,registry);new=tmp_path/'中文 移动后';old.rename(new)
    selected=selected_workspace(None,registry);assert selected==old.resolve()
    with pytest.raises(RuntimeError,match='WORKSPACE_MISSING'):
        open_workspace(selected,registry=registry,browser=False)
    assert not old.exists() and (new/'app.sqlite3').exists()


def test_persistent_workspace_reopens_without_losing_task_and_answer(tmp_path):
    from probe_support import initialize,Settings,TestClient,create_workbench_app,httpx
    initialize(tmp_path,sample=True)
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'models':[]}) if r.url.path=='/api/tags' else httpx.Response(503))
    settings=Settings(data_dir=tmp_path,sqlite_path=tmp_path/'app.sqlite3')
    with TestClient(create_workbench_app(settings,model_transport=transport)) as c:
        w=c.app.state.workspace;t=loan(w);tid=t['task_id'];cid=t['conversation_id']
        with w.library.db() as db:db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES(?,?,?,?,?,?)',('keep',cid,'kb','持久化问题',json.dumps({'mode':'not_found','answer':'合成历史','sources':[]}), 'g'))
    with TestClient(create_workbench_app(settings,model_transport=transport)) as c:
        assert c.get('/api/product/tasks/'+tid).status_code==200
        assert c.get('/api/conversations/'+cid).status_code==200
        assert c.get('/api/product/answers/keep').status_code==200
        assert c.app.state.workspace.service.view(tid)['facts']==t['facts']


def test_submitted_task_remains_submitted_after_retryable_knowledge():
    with product() as(c,w):
        kb=w.library.create('已提交任务知识')['id'];t=loan(w);tid=t['task_id'];cid=t['conversation_id']
        c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':kb})
        p=c.post(f'/api/product/tasks/{tid}/prepare',headers=H,json={'asset_id':'loan-laptop-1','expected_facts_revision':t['facts_revision']}).json()
        payload={'proposal_id':p['preview']['proposal_id'],'content_digest':p['preview']['content_digest'],'accepted':True,'expected_facts_revision':p['revision']}
        original=c.post(f'/api/tasks/{tid}/submit',headers=H,json=payload).json()['receipt']
        # A pending business ticket can remain attached to the conversation.
        # The model selects a read; recovery must not manufacture a second ticket.
        calls=[]
        async def answer(k,q,**kw):
            calls.append(1)
            if len(calls)==1:raise ServiceError('TRANSIENT_TOOL_FAILURE')
            return fake_answer(k,q,**kw)
        w.library.answer=answer
        m=Model([('knowledge_answer',{'question':'提交后的规则','turn_request':{'preview':False,'knowledge_quote':'提交后的规则'}})], [('finish',{})]);w.models.chat=m.chat
        result=send(c,cid,'after-submit','提交后的规则是什么？')
        assert result['status']=='succeeded' and turn(w,cid,'after-submit')['status']=='PARTIAL', {'run':result,'turn':turn(w,cid,'after-submit'),'calls':calls,'model_calls':len(w.models.chat.__self__.calls)}
        assert retry(c,cid,'after-submit')['status']=='succeeded'
        assert w.service.view(tid)['receipt']==original and len(w.service.store.list_tickets(local_actor()))==1


def test_already_stranded_null_scope_can_be_explicitly_completed():
    """Migration shape produced by rc4: selected conversation KB, old pending command null."""
    with product() as(c,w):
        t=w.service.create({'kind':'loan','execution_ceiling':'PREVIEW_ONLY','confirmed':True});cid=t['conversation_id'];calls=[]
        async def answer(k,q,**kw):
            calls.append(k)
            if k is None:raise ServiceError('KNOWLEDGE_BASE_REQUIRED')
            w.library.require(k);return fake_answer(k,q,**kw)
        w.library.answer=answer
        m=Model([('update_parameters',{'changes':{},'turn_request':{'preview':False,'knowledge_quote':'借用期限'}})],[('finish',{})]);w.models.chat=m.chat
        send(c,cid,'legacy-partial','解释借用期限')
        kb=w.library.create('已经选过的知识库')['id']
        # Persist the exact pre-upgrade condition, not a new runtime behavior.
        with w.conversations.db() as db:
            db.execute('UPDATE conversations SET kb_id=? WHERE id=?',(kb,cid))
        r=c.patch(f'/api/conversations/{cid}',headers=H,json={'kb_id':kb});assert r.status_code==200
        out=retry(c,cid,'legacy-partial')
        assert out['status']=='succeeded',out
        assert calls==[kb] and turn(w,cid,'legacy-partial')['status']=='DONE'
