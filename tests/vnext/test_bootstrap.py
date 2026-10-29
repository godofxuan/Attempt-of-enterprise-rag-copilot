"""Product bootstrap program tests; no live inference."""
from unittest.mock import Mock
import sqlite3
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.runtime.resources import build_service_container
from app.workspace import initialize


def client_for(root):
    initialize(root)
    settings=Settings(workbench_enabled=True,data_dir=root,sqlite_path=root/'app.sqlite3')
    service=build_service_container(settings)
    service.resources.start=Mock(side_effect=AssertionError('No expensive legacy startup'))
    return TestClient(create_app(service))


def test_missing_identity_and_model_do_not_block_product_pages(tmp_path):
    with client_for(tmp_path) as client:
        async def offline(request):raise httpx.ConnectError('model deliberately unavailable')
        workspace=client.app.state.workspace
        workspace.client=httpx.AsyncClient(transport=httpx.MockTransport(offline))
        assert client.get('/').status_code==200
        assert client.get('/assets/workbench.js').status_code==200
        assert client.get('/health/live').status_code==200
        status=client.get('/api/status').json()
        assert status['web'] and status['storage'] and not status['chat']['ready']
        assert status['model_error']['code']=='MODEL_UNAVAILABLE'
        assert client.get('/api/history').status_code==200
        assert client.post('/agent/v2/chat',json={'question':'policy?'}).status_code in (401,503)


def test_init_and_restart_preserve_same_database_and_settings(tmp_path):
    initialize(tmp_path)
    with sqlite3.connect(tmp_path/'app.sqlite3') as db:
        first=db.execute("SELECT value FROM workspace_meta WHERE key='initialized_at'").fetchone()[0]
    with client_for(tmp_path) as client:
        result=client.patch('/api/settings',headers={'X-ESA-Request':'1'},json={'chat_model':'chosen-installed-model'})
        assert result.status_code==200
    initialize(tmp_path,sample=True)
    with client_for(tmp_path) as client:
        assert client.get('/api/settings').json()['chat_model']=='chosen-installed-model'
    with sqlite3.connect(tmp_path/'app.sqlite3') as db:
        assert db.execute("SELECT value FROM workspace_meta WHERE key='initialized_at'").fetchone()[0]==first


def test_local_settings_reject_cross_origin_and_missing_write_header(tmp_path):
    with client_for(tmp_path) as client:
        assert client.patch('/api/settings',json={'chat_model':'x'}).status_code==403
        assert client.patch('/api/settings',headers={'Origin':'https://unrelated.invalid','X-ESA-Request':'1'},json={'chat_model':'x'}).status_code==403
        assert client.get('/api/settings',headers={'Host':'evil.invalid'}).status_code==400
