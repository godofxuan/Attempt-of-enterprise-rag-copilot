"""Offline transport doubles; parser, FAISS publication, retrieval and HTTP are real."""
import asyncio
import json
import time
from tests.vnext.test_bootstrap import client_for

HEADERS={'X-ESA-Request':'1'}


def test_document_job_generation_and_history_survive_reopen(tmp_path):
    with client_for(tmp_path) as client:
        kb=client.post('/api/library',headers=HEADERS,json={'name':'Test policies'}).json()['id']
        workspace=client.app.state.workspace
        async def embed(texts,**kwargs):return [[1.,float(len(text)%7)+1] for text in texts]
        async def identity():return '1'*64
        workspace.models.embed=embed
        workspace.models.embedding_identity=identity
        doc=client.post(f'/api/library/{kb}/documents',headers=HEADERS,
                        files={'file':('policy.md',b'# Booking\n\nBooking requires sponsor approval.\n')}).json()
        assert doc.get('status')=='PARSED',doc
        assert client.get('/api/documents/'+doc['id']).json()['parsed']['text']
        job=client.post(f'/api/library/{kb}/build',headers=HEADERS,json={}).json()
        for _ in range(100):
            data=client.get('/api/library').json()
            state=next(j for j in data['jobs'] if j['id']==job['id'])
            if state['status'] not in ('QUEUED','RUNNING'):break
            time.sleep(.05)
        assert state['status']=='SUCCEEDED',state
        assert json.loads(state['metrics'])['embedding_misses']>0
        original_config=workspace.config
        workspace.config=original_config.model_copy(update={'embedding_model':'different-installed-family'})
        import pytest
        with pytest.raises(ValueError,match='INDEX_EMBEDDING_MODEL_CHANGED'):workspace.library.snapshot(kb)
        workspace.config=original_config
        pointer=(tmp_path/'indexes'/kb/'active.json').read_bytes()
        # Same actual documents: a new published generation, zero embedding sends.
        async def forbidden_embed(*args,**kwargs):raise AssertionError('Unchanged chunks must reuse embeddings')
        workspace.models.embed=forbidden_embed
        second=client.post(f'/api/library/{kb}/build',headers=HEADERS,json={}).json()
        for _ in range(100):
            latest=next(j for j in client.get('/api/library').json()['jobs'] if j['id']==second['id'])
            if latest['status'] not in ('QUEUED','RUNNING'):break
            time.sleep(.05)
        assert latest['status']=='SUCCEEDED',latest
        assert json.loads(latest['metrics'])['embedding_misses']==0
        pointer=(tmp_path/'indexes'/kb/'active.json').read_bytes()
        # Failed replacement preserves the active document and generation.
        broken=client.post(f'/api/library/{kb}/documents',headers=HEADERS,files={'file':('policy.md',b' ')}).json()
        assert broken['status']=='FAILED'
        active=[d for d in client.get('/api/library').json()['documents'] if d['active']]
        assert [d['id'] for d in active]==[doc['id']]
        assert (tmp_path/'indexes'/kb/'active.json').read_bytes()==pointer
        # A real replacement must not silently answer current questions from
        # the old generation; the old source remains independently readable.
        new=client.post(f'/api/library/{kb}/documents',headers=HEADERS,files={'file':('policy.md',b'# Booking\n\nBooking now requires manager approval.\n')}).json()
        import pytest
        with pytest.raises(ValueError,match='INDEX_OUTDATED'):workspace.library.snapshot(kb)
        historical=client.get('/api/documents/'+doc['id']).json()
        assert not historical['active'] and 'sponsor' in historical['parsed']['text']
        notices=workspace.library.source_notices({'sources':[{'doc_id':doc['id']}]})
        assert len(notices)==1 and '历史版本' in notices[0]
        # Snapshot compatibility check below reopens a clean, unmodified base.
        # Complete the changed index first with the explicit test transport.
        workspace.models.embed=embed
        latest_job=client.post(f'/api/library/{kb}/build',headers=HEADERS,json={}).json()
        for _ in range(100):
            latest=next(j for j in client.get('/api/library').json()['jobs'] if j['id']==latest_job['id'])
            if latest['status'] not in ('QUEUED','RUNNING'):break
            time.sleep(.05)
        assert latest['status']=='SUCCEEDED',latest
    with client_for(tmp_path) as client:
        async def identity():return '1'*64
        client.app.state.workspace.models.embedding_identity=identity
        assert client.get('/api/library').json()['bases'][0]['id']==kb
        assert client.app.state.workspace.library.snapshot(kb).version.manifest.run_id==latest_job['id']


def test_followup_context_uses_only_user_questions_and_rejects_wrong_base_before_send(tmp_path):
    with client_for(tmp_path) as client:
        library=client.app.state.workspace.library;kb=library.create('One')['id'];other=library.create('Other')['id']
        with library.db() as db:
            db.execute('INSERT INTO conversations VALUES(?,?)',('c1',kb))
            db.execute('INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES(?,?,?,?,?,?)',
                       ('a1','c1',kb,'电脑借用期限是什么？',json.dumps({'answer':'UNTRUSTED_OLD_ANSWER_NEVER_BECOMES_CONTEXT_EVIDENCE'}),'old-generation'))
        assert library.conversation_context(kb,'c1')==[{'id':'a1','question':'电脑借用期限是什么？'}]
        import pytest
        with pytest.raises(ValueError,match='KNOWLEDGE_BASE_MISMATCH'):
            asyncio.run(library.answer(other,'那押金呢？',conversation_id='c1'))
        with pytest.raises(ValueError,match='CONVERSATION_NOT_FOUND'):
            asyncio.run(library.answer(kb,'那押金呢？',conversation_id='not-a-conversation'))
        with library.db() as db:assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0]==0


def test_job_failure_is_visible_and_no_empty_active_index(tmp_path):
    with client_for(tmp_path) as client:
        kb=client.post('/api/library',headers=HEADERS,json={'name':'Empty'}).json()['id']
        client.post(f'/api/library/{kb}/build',headers=HEADERS,json={})
        for _ in range(30):
            job=client.get('/api/library').json()['jobs'][0]
            if job['status']=='FAILED':break
            time.sleep(.02)
        assert job['status']=='FAILED' and 'NO_PARSED_DOCUMENTS' in job['error']
        assert not (tmp_path/'indexes'/kb/'active.json').exists()


def test_model_failure_is_recorded_before_return(tmp_path):
    import httpx
    with client_for(tmp_path) as client:
        models=client.app.state.workspace.models
        async def fail(request):raise httpx.ConnectError('offline test')
        async def run():
            await models.client.aclose()
            models.client=httpx.AsyncClient(transport=httpx.MockTransport(fail))
            try:await models.chat([{'role':'user','content':'test'}])
            except httpx.ConnectError:pass
        asyncio.run(run())
        with models.db() as db:
            row=db.execute('SELECT status,error,input_json FROM model_calls').fetchone()
        assert row[0]=='ERROR' and 'offline test' in row[1] and 'test' in row[2]


def test_actual_generation_transport_uses_the_output_reserve_used_by_packing(tmp_path):
    import httpx
    from app.agent.generation_v2 import MAX_OUTPUT_TOKENS,MODEL_CONTEXT_FLOOR
    with client_for(tmp_path) as client:
        models=client.app.state.workspace.models;observed=[]
        async def reply(request):
            observed.append(json.loads(request.content))
            return httpx.Response(200,json={'message':{'role':'assistant','content':'{}'},'done_reason':'stop'})
        async def run():
            await models.client.aclose();models.client=httpx.AsyncClient(transport=httpx.MockTransport(reply))
            callback=models.sync_chat(asyncio.get_running_loop())
            await asyncio.to_thread(callback,'transport-test',[{'role':'user','content':'Offline wire check'}],response_format={'type':'object'})
        asyncio.run(run())
        assert observed[0]['options']['num_predict']==MAX_OUTPUT_TOKENS
        assert observed[0]['options']['num_ctx']==MODEL_CONTEXT_FLOOR


def test_expired_run_does_not_send_and_active_settings_cannot_change(tmp_path,monkeypatch):
    from app.runtime.request_context import bind_request_context,reset_request_context,RequestDeadlineExceeded
    from app.runtime import request_context
    import httpx
    import pytest
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace
        async def expired():
            clock=[1000.0]
            monkeypatch.setattr(request_context,'_default_clock_ms',lambda:clock[0])
            async def unexpected_send(request):raise AssertionError('Expired run attempted HTTP')
            await workspace.models.client.aclose()
            workspace.models.client=httpx.AsyncClient(transport=httpx.MockTransport(unexpected_send))
            token=bind_request_context('expired-before-send',deadline_ms=1)
            try:
                clock[0]=1002.0
                with pytest.raises(RequestDeadlineExceeded):await workspace.models.chat([{'role':'user','content':'No send'}])
            finally:reset_request_context(token)
        asyncio.run(expired())
        with workspace.models.db() as db:assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0]==0
        workspace.runs.tasks['deliberately-active-test']=None
        try:
            response=client.patch('/api/settings',headers=HEADERS,json={'chat_model':'different-model'})
            assert response.status_code==409 and response.json()['error']['code']=='SETTINGS_IN_USE'
        finally:workspace.runs.tasks.pop('deliberately-active-test')


def test_pdf_and_docx_reuse_real_parsers_and_preserve_locations_and_table_text(tmp_path):
    from io import BytesIO
    from docx import Document
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    word=Document();word.add_heading('Loan policy',0);word.add_paragraph('A loan requires sponsor approval.')
    table=word.add_table(rows=2,cols=2);table.cell(0,0).text='Item';table.cell(0,1).text='Days';table.cell(1,0).text='Loan';table.cell(1,1).text='14'
    docx=BytesIO();word.save(docx)
    pdf=PdfWriter();page=pdf.add_blank_page(width=400,height=400)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):pdf._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 40 350 Td (Meeting hours are 09:00 to 18:00.) Tj ET')
    page[NameObject('/Contents')]=pdf._add_object(content);pdf_bytes=BytesIO();pdf.write(pdf_bytes)
    with client_for(tmp_path) as client:
        kb=client.post('/api/library',headers=HEADERS,json={'name':'Formats'}).json()['id']
        results=[]
        for name,data in [('policy.docx',docx.getvalue()),('meeting.pdf',pdf_bytes.getvalue())]:
            document=client.post('/api/library/'+kb+'/documents',headers=HEADERS,files={'file':(name,data)}).json()
            assert document['status']=='PARSED',document
            results.append(client.get('/api/documents/'+document['id']).json()['parsed'])
        assert 'sponsor approval' in results[0]['text'] and '14' in results[0]['text'] and results[0]['tables']
        assert '09:00 to 18:00' in results[1]['text'] and results[1]['sections'][0]['locator']['kind']=='page'
        with client.app.state.workspace.library.db() as db:assert db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0]==0
