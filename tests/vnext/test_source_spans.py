"""Original parsers -> real index -> guarded evidence -> actual publication -> excerpt."""
from io import BytesIO
import json,time
from docx import Document

from tests.vnext.test_bootstrap import client_for
from tests.vnext.test_library import HEADERS


def test_docx_locations_survive_index_guard_and_publication_without_markdown_reparse(tmp_path):
    document=Document();document.add_heading('Device guide',0)
    document.add_paragraph('Only employees with a current repair record may borrow a computer.')
    document.add_paragraph('Borrowing cannot exceed fourteen days.')
    buffer=BytesIO();document.save(buffer)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace
        async def embed(texts,**kwargs):return [[1.,0.] for _ in texts]
        async def identity():return '1'*64
        workspace.models.embed=embed;workspace.models.embedding_identity=identity
        kb=client.post('/api/library',headers=HEADERS,json={'name':'Original Word'}).json()['id']
        doc=client.post(f'/api/library/{kb}/documents',headers=HEADERS,files={'file':('guide.docx',buffer.getvalue())}).json()
        job=client.post(f'/api/library/{kb}/build',headers=HEADERS,json={}).json()
        for _ in range(100):
            built=next(j for j in client.get('/api/library').json()['jobs'] if j['id']==job['id'])
            if built['status'] not in ('QUEUED','RUNNING'):break
            time.sleep(.05)
        assert built['status']=='SUCCEEDED',built
        snapshot=workspace.library.snapshot(kb)
        record=snapshot.documents_by_id[doc['id']]
        assert record.format=='docx' and record.parser_name!='markdown'
        assert record.source_type=='wiki' and str(record.document_version.effective_from)!='2000-01-01'
        assert record.sections and all(s.locator.kind!='page' for s in record.sections)
        chunks=[c for c in snapshot.all_chunks_by_id.values() if c.indexable]
        assert chunks and all(c.source_spans for c in chunks)
        for chunk in chunks:
            for span in chunk.source_spans:
                assert span.document_id==doc['id'] and span.version_id==doc['id']
                if span.text_start is not None:assert record.text[span.text_start:span.text_end]==chunk.text
        from app.retrieval.pipeline import HybridRetrievalPipeline
        from app.retrieval.navigation import DocumentNavigator
        from app.agent.tools_v2 import V2ToolRegistry
        from app.agent.controller_v2 import V2AgentController
        from app.domain.queries import QueryAnalysis,UserContext
        from app.agent.generation_v2 import GenerationV2ResponseBuilder
        from tests.agent_v2.test_generation_v2 import evidence_records_from_prompt,TEST_NONCE
        question='Who may borrow a computer?'
        analysis=QueryAnalysis(original_question=question,intent='fact',required_aspects=[question],search_queries=[question],source='rules')
        controller=V2AgentController(semantic_question=True,clock_ms=lambda:0)
        state=controller.initialize(analysis,UserContext(user_id='local-owner',tenant_id='local',region='local',groups=['local-owner']))
        registry=V2ToolRegistry(DocumentNavigator(snapshot,pipeline=HybridRetrievalPipeline(snapshot,embed_text=lambda text:[1.,0.])),clock_ms=lambda:0)
        decision=controller.next_decision(state);state=controller.observe(state,registry.run(decision.action,state.budget_state))
        assert any(h.hit.source_spans for rows in state.evidence_by_aspect.values() for h in rows)
        def saved_shape(model,messages,**kwargs):
            import re
            prompt=messages[1]['content']
            records=json.loads(prompt.split('[BEGIN_UNTRUSTED_EVIDENCE nonce='+TEST_NONCE+']')[1].split('[END_UNTRUSTED_EVIDENCE')[0])
            source=next(r for r in records if 'current repair record' in r['matched_text'])
            unit=next(m for m in re.finditer(r'\[(S\d+U\d+)\](.*?)\[/\1\]',source['matched_text'],re.S) if 'current repair record' in m[2])
            assert 'answer' not in kwargs['response_format']['properties']
            assert kwargs['response_format']['properties']['need_status']['required']==['N1']
            uses={uid:[] for uid in kwargs['response_format']['properties']['unit_uses']['required']};uses[unit[1]]=['N1']
            return json.dumps({'unit_uses':uses,'need_status':{'N1':{'status':'supported','subject_matches':True,
                    'attribute_matches':True,'conditions_preserved':True}}})
        response=GenerationV2ResponseBuilder(chat_fn=saved_shape,model='EXPLICIT_TEST_SHAPE_NOT_LIVE',nonce_factory=lambda:TEST_NONCE,max_attempts=1,need_first_wire=True).build(
            question=question,state=state,mode='answered',stop_reason='completed',trace={})
        assert response.mode=='answered' and 'current repair record' in response.answer,response.trace
        source=response.sources[0];assert source.source_spans
        excerpt=client.get('/api/documents/'+doc['id']+'/excerpt',params={'index_run_id':job['id'],
            'target_type':source.target_type,'target_id':source.target_id}).json()
        assert excerpt['source_spans'] and 'repair record' in excerpt['text']
        assert excerpt['location_basis']=='original_parser'
        assert client.get('/api/documents/'+doc['id']+'/excerpt',params={'index_run_id':job['id'],
            'target_type':'chunk','target_id':'other-document-chunk'}).status_code==422
        changed=client.patch('/api/documents/'+doc['id'],headers=HEADERS,json={'source_type':'policy'})
        assert changed.status_code==200
        import pytest
        with pytest.raises(ValueError,match='INDEX_OUTDATED'):workspace.library.snapshot(kb)


def test_batch_disable_restore_and_metadata_changes_require_current_index(tmp_path):
    with client_for(tmp_path) as client:
        kb=client.post('/api/library',headers=HEADERS,json={'name':'Lifecycle'}).json()['id']
        batch=client.post(f'/api/library/{kb}/documents/batch',headers=HEADERS,files=[
            ('files',('a.md',b'# Policy\n\nOnly current staff may book.')),
            ('files',('b.txt',b'The desk closes at 18:00.')),('files',('bad.exe',b'not a supported file'))]).json()
        assert batch['successful']==2 and len(batch['documents'])==3
        doc=batch['documents'][0]
        changed=client.patch('/api/documents/'+doc['id'],headers=HEADERS,json={'name':'Readable title','source_type':'policy','service_tags':['loan'],'active':False}).json()
        assert not changed['active']
        restore=client.patch('/api/documents/'+doc['id'],headers=HEADERS,json={'active':True}).json()
        assert restore['active'] and client.get('/api/documents/'+doc['id']).json()['name']=='Readable title'
        assert client.get('/api/documents/'+doc['id']).json()['metadata']['service_tags']==['loan']
        assert client.patch('/api/documents/'+doc['id'],headers=HEADERS,json={'active':None}).status_code==422
        assert client.app.state.workspace.library.service_options({'sources':[{'doc_id':doc['id']}]})==[{'key':'loan','title':'临时电脑借用'}]


def test_pdf_second_page_is_a_real_page_location_not_a_markdown_line(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    pdf=PdfWriter()
    for text in ('Service guide overview.','Only registered employees may request service.'):
        page=pdf.add_blank_page(width=400,height=400)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):pdf._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 40 350 Td ('+text+') Tj ET').encode('ascii'))
        page[NameObject('/Contents')]=pdf._add_object(stream)
    buffer=BytesIO();pdf.write(buffer)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace
        kb=client.post('/api/library',headers=HEADERS,json={'name':'PDF locations'}).json()['id']
        doc=client.post(f'/api/library/{kb}/documents',headers=HEADERS,files={'file':('pages.pdf',buffer.getvalue())}).json()
        def fake_embed(text):return [1.,0.]
        built,_,_=workspace.library._build('pdf-span-check',kb,fake_embed,'1'*64)
        from app.indexing.store import activate_version
        activate_version(tmp_path/'indexes'/kb,built.run_id)
        snapshot=workspace.library.snapshot(kb)
        chunks=[c for c in snapshot.all_chunks_by_id.values() if 'registered employees' in c.text]
        assert chunks and all(any(s.locator_kind=='page' and s.locator_start==2 for s in c.source_spans) for c in chunks)
        excerpt=workspace.library.excerpt(doc['id'],built.run_id,'chunk',chunks[0].chunk_id)
        assert 'registered employees' in excerpt['text'] and excerpt['source_spans'][0]['locator_start']==2


def test_installed_samples_use_the_current_domain_row_and_do_not_invent_room_service(tmp_path):
    from app.workspace import initialize
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        workspace=client.app.state.workspace
        with workspace.service.store.transaction() as db:db.execute('UPDATE loan_rules SET max_days=7')
        kb=client.post('/api/library',headers=HEADERS,json={'name':'Rule-backed samples'}).json()['id']
        imported=client.post(f'/api/library/{kb}/samples',headers=HEADERS,json={}).json()
        assert len(imported['documents'])==3
        loan=next(d for d in imported['documents'] if d['name']=='sample_loan.md')
        room=next(d for d in imported['documents'] if d['name']=='sample_meeting.md')
        parsed=client.get('/api/documents/'+loan['id']).json()
        assert '1至7天' in parsed['parsed']['text'] and '14天' not in parsed['parsed']['text']
        assert parsed['metadata']['rule_binding']['service']=='loan'
        assert workspace.library.service_options({'sources':[{'doc_id':room['id']}]})==[]
        thread=client.post('/api/conversations',headers=HEADERS,json={'title':'One topic','kb_id':kb}).json()
        task=client.post('/api/tasks',headers=HEADERS,json={'request':{'kind':'repair','confirmed':True,
            'execution_ceiling':'READ_ONLY'},'kb_id':kb,'conversation_id':thread['id']}).json()
        assert task['conversation_id']==thread['id']
