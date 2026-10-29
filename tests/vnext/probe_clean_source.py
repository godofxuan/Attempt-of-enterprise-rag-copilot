"""Run with -I -S: code from the supplied copy; existing third-party deps only."""
import json
from pathlib import Path
import sys

code,data,dependencies=map(Path,sys.argv[1:4])
sys.path[:0]=[str(code.resolve()),str(dependencies.resolve())]
from app.config import Settings
from app.runtime.resources import build_service_container
from app.main import create_app
from app.agent_runtime.workbench_agent import build_service_agent
from app.workspace import initialize
import app
from fastapi.testclient import TestClient

assert Path(app.__file__).resolve().is_relative_to(code.resolve())
assert 'app.agent_runtime.durable_orchestrator' not in sys.modules
assert 'app.agent_runtime.evaluation' not in sys.modules
initialize(data,sample=True)
settings=Settings(workbench_enabled=True,data_dir=data.resolve(),sqlite_path=(data/'app.sqlite3').resolve())
with TestClient(create_app(build_service_container(settings))) as client:
    assert client.get('/').status_code==200
    assert client.get('/assets/workbench.js').status_code==200
    assert client.get('/api/tasks').status_code==200
    assert client.get('/api/library').status_code==200
    print(json.dumps({'code':str(Path(app.__file__).resolve()),'dependency_mode':'EXISTING_THIRD_PARTY_PACKAGES_NO_EDITABLE_PTH',
                      'data':str(data.resolve()),'result':'PASS','model_calls':0},ensure_ascii=False))
