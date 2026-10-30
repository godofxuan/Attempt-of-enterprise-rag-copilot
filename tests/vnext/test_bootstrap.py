"""Product bootstrap program tests; no live inference."""
from unittest.mock import Mock
import sqlite3
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.workbench_app import create_workbench_app
from app.workspace import initialize


def client_for(root):
    initialize(root)
    settings=Settings(workbench_enabled=True,data_dir=root,sqlite_path=root/'app.sqlite3')
    return TestClient(create_workbench_app(settings))


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
        assert client.post('/agent/v2/chat',json={'question':'policy?'}).status_code == 404  # Explicit legacy API is not mounted in the product factory.


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


def test_second_app_cannot_recover_the_first_apps_active_run(tmp_path):
    import pytest
    with client_for(tmp_path) as first:
        workspace=first.app.state.workspace
        with sqlite3.connect(tmp_path/'app.sqlite3') as db:
            db.execute("INSERT INTO workbench_runs(id,kind,target,status,input_json) VALUES('active-original','knowledge','one','running','{}')")
        with pytest.raises(RuntimeError,match='WORKSPACE_ALREADY_RUNNING'):
            with client_for(tmp_path):pass
        with sqlite3.connect(tmp_path/'app.sqlite3') as db:
            assert db.execute("SELECT status FROM workbench_runs WHERE id='active-original'").fetchone()[0]=='running'


def test_doctor_does_not_start_recovery_and_os_lock_is_released_after_crash(tmp_path):
    import json,subprocess,sys
    from app.runtime.workspace_lock import WorkspaceLease
    with client_for(tmp_path) as client:
        client.patch('/api/settings',headers={'X-ESA-Request':'1'},json={'model_endpoint':'http://127.0.0.1:1'})
        with sqlite3.connect(tmp_path/'app.sqlite3') as db:
            db.execute("INSERT INTO workbench_runs(id,kind,target,status,input_json) VALUES('keep-running','knowledge','one','running','{}')")
        doctor=subprocess.run([sys.executable,'-B','-X','utf8','-m','app.cli','doctor','--data-dir',str(tmp_path)],capture_output=True,text=True,encoding='utf8',timeout=15)
        assert doctor.returncode==0,doctor.stderr
        assert json.loads(doctor.stdout)['inspection']=='READ_ONLY_NO_STARTUP_OR_RECOVERY'
        with sqlite3.connect(tmp_path/'app.sqlite3') as db:
            assert db.execute("SELECT status FROM workbench_runs WHERE id='keep-running'").fetchone()[0]=='running'
    code="from pathlib import Path;from app.runtime.workspace_lock import WorkspaceLease;import sys;lease=WorkspaceLease(Path(sys.argv[1])).acquire();print('LOCKED',flush=True);sys.stdin.read()"
    child=subprocess.Popen([sys.executable,'-B','-c',code,str(tmp_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='LOCKED'
        import pytest
        with pytest.raises(RuntimeError,match='WORKSPACE_ALREADY_RUNNING'):WorkspaceLease(tmp_path).acquire()
    finally:child.kill();child.wait(timeout=5)
    with WorkspaceLease(tmp_path):pass
