import json,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.config import Settings
from app.workspace import initialize
from app.workbench_app import create_workbench_app
from app.indexing.workbench_cache import CachedChunkEmbeddings
from app.ingestion.chunking import ChunkerConfig

def test_current_factory_settings_and_synthetic_processing_routes_without_legacy(tmp_path):
    initialize(tmp_path,sample=True)
    with TestClient(create_workbench_app(Settings(data_dir=tmp_path,sqlite_path=tmp_path/'app.sqlite3'))) as c:
        assert c.get('/health/live').status_code==200
        assert c.get('/api/service-desk').json()['origin']=='LOCAL_SYNTHETIC_TEST_ONLY'
        assert c.post('/api/tasks',json={}).status_code==403
        assert c.get('/assets/ui/service-desk.js').status_code==200
        assert c.get('/agent/v2/chat').status_code==404
    code="import app.cli,app.workbench_app,sys;assert 'app.main' not in sys.modules;assert 'app.runtime.resources' not in sys.modules"
    r=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=10)
    assert r.returncode==0,r.stderr

def test_embedding_misses_are_batched_and_second_build_is_cached(tmp_path):
    initialize(tmp_path)
    w=SimpleNamespace(root=tmp_path,db_path=tmp_path/'app.sqlite3',config=SimpleNamespace(embedding_model='program-test-model'))
    chunks=[SimpleNamespace(tenant_id='local',policy_id='document-'+str(i),text='program fixture '+str(i)) for i in range(35)]
    calls=[]
    def single(text):raise AssertionError('Must use the real batch boundary')
    def batch(texts):calls.append(texts);return [[float(len(t)),1.,2.] for t in texts]
    single.batch=batch
    first=CachedChunkEmbeddings(w,'a'*64,single,ChunkerConfig(mode="heading"))
    vectors=first(chunks)
    assert vectors.shape==(35,3) and [len(x) for x in calls]==[16,16,3] and first.misses==35
    second=CachedChunkEmbeddings(w,'a'*64,single,ChunkerConfig(mode="heading"))
    assert (second(chunks)==vectors).all() and second.hits==35 and second.misses==0 and len(calls)==3
