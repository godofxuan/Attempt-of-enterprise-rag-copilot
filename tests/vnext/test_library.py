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
    with client_for(tmp_path) as client:
        async def identity():return '1'*64
        client.app.state.workspace.models.embedding_identity=identity
        assert client.get('/api/library').json()['bases'][0]['id']==kb
        assert client.app.state.workspace.library.snapshot(kb).version.manifest.run_id==second['id']


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
