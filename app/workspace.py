"""Local workbench lifecycle and HTTP projection in the existing FastAPI app."""
from __future__ import annotations

from datetime import datetime, timezone,date
import asyncio
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.security.model_endpoint import parse_pinned_model_endpoint


class WorkspaceError(Exception):
    def __init__(self,status,code,data=None):
        self.status=status;self.code=code;self.data=data or {}


def install_workspace_errors(application):
    from fastapi.responses import JSONResponse
    async def handle(request,exc):
        return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.code,'data':exc.data}})
    application.add_exception_handler(WorkspaceError,handle)


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_endpoint: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:9b"
    embedding_model: str = "bge-m3"
    request_timeout_seconds: float = Field(default=90, ge=1, le=300)
    max_parallel_requests: int = Field(default=1, ge=1, le=4)
    sample_data: bool = False

    @field_validator("model_endpoint")
    @classmethod
    def local_endpoint(cls, value):
        return parse_pinned_model_endpoint(value).origin


def data_root(value=None):
    import os
    return Path(value or os.getenv("ESA_DATA_DIR") or Path.home()/".esa").expanduser().resolve()


def load_config(root, overrides=None):
    import os
    path = root/"workspace.json"
    values = json.loads(path.read_text("utf8")) if path.exists() else {}
    for key in ("model_endpoint", "chat_model", "embedding_model"):
        if os.getenv("ESA_"+key.upper()): values[key] = os.environ["ESA_"+key.upper()]
    values.update({k:v for k,v in (overrides or {}).items() if v is not None})
    return WorkspaceConfig.model_validate(values)


def initialize(root, *, sample=False):
    """Explicit idempotent initialization; serve never resets or seeds user state."""
    from app.runtime.workspace_lock import WorkspaceLease
    with WorkspaceLease(root):_initialize(root,sample=sample)


def _initialize(root, *, sample=False):
    root.mkdir(parents=True, exist_ok=True)
    path = root/"workspace.json"
    if not path.exists():
        config = WorkspaceConfig(sample_data=sample)
        with path.open("x", encoding="utf8") as stream: stream.write(config.model_dump_json(indent=2)+"\n")
    for folder in ("documents", "indexes", "logs"): (root/folder).mkdir(exist_ok=True)
    with sqlite3.connect(root/"app.sqlite3") as db:
        db.execute("CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO workspace_meta VALUES('initialized_at',?)", (datetime.now(timezone.utc).isoformat(),))
    if sample and load_config(root).sample_data:
        from app.workbench_service import seed_sample
        seed_sample(root)


class Workspace:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.db_path = settings.sqlite_path.resolve()
        self.config = load_config(self.root)
        self.started = False
        self.client = None

    async def start(self):
        # No model probe, index load, source scan, fixture import or business seed.
        from app.runtime.workspace_lock import WorkspaceLease
        self.lease=WorkspaceLease(self.root).acquire()
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.client = httpx.AsyncClient(trust_env=False, timeout=2, follow_redirects=False)
        from app.runtime.workbench_models import ModelService
        from app.workbench_knowledge import Library
        from app.runtime.workbench_runs import Runs
        from app.workbench_service import TaskService
        self.models = ModelService(self)
        self.library = Library(self)
        self.runs = Runs(self)
        self.service = TaskService(self)
        from app.conversations import ConversationService
        self.conversations=ConversationService(self)
        await self.library.start()
        self.started = True

    async def close(self):
        if getattr(self,'runs',None):await self.runs.close()
        if getattr(self,'library',None):await self.library.close()
        if getattr(self,'models',None):await self.models.close()
        if self.client: await self.client.aclose()
        if getattr(self,'lease',None):self.lease.close()
        self.started = False

    async def status(self):
        models = []; error = None
        try:
            response = await self.client.get(self.config.model_endpoint+"/api/tags")
            response.raise_for_status()
            models = [{"name":m["name"],"digest":m.get("digest")} for m in response.json()["models"]]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            error = {"code": "MODEL_UNAVAILABLE", "message": str(exc)}
        found = {m["name"].removesuffix(":latest") for m in models}
        initialized=None;calls=0
        if self.db_path.is_file():
            with sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True) as db:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'workspace_meta' in tables:initialized = db.execute("SELECT value FROM workspace_meta WHERE key='initialized_at'").fetchone()
                if 'model_calls' in tables:calls = db.execute("SELECT COUNT(*) FROM model_calls WHERE kind='chat'").fetchone()[0]
        return {"web":True,"storage":self.started,"data_dir":str(self.root),"database":str(self.db_path),
                "initialized_at":initialized[0] if initialized else None,"models":models,
                "chat":{"ready":self.config.chat_model.removesuffix(":latest") in found,"model":self.config.chat_model},
                "embedding":{"ready":self.config.embedding_model.removesuffix(":latest") in found,"model":self.config.embedding_model},
                "model_error":error,"mode":"SYNTHETIC_LOCAL" if self.config.sample_data else "LOCAL_OWNER",
                "generation_calls":calls}

    def save_settings(self, changes):
        if getattr(self,'runs',None) and (self.runs.tasks or self.library.running):
            raise WorkspaceError(409,'SETTINGS_IN_USE',{'reason':'请先完成或停止当前运行/索引任务，再修改模型连接'})
        updated = self.config.model_copy(update=changes)
        updated = WorkspaceConfig.model_validate(updated.model_dump())
        temp = self.root/"workspace.json.tmp"
        temp.write_text(updated.model_dump_json(indent=2)+"\n", encoding="utf8")
        temp.replace(self.root/"workspace.json")
        self.config = updated
        return updated.model_dump()


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_endpoint: str | None = None
    chat_model: str | None = Field(default=None,min_length=1,max_length=200)
    embedding_model: str | None = Field(default=None,min_length=1,max_length=200)
    request_timeout_seconds: float | None = Field(default=None,ge=1,le=300)


class CreateKnowledgeBase(BaseModel):
    name: str = Field(min_length=1,max_length=200)


class AskKnowledge(BaseModel):
    kb_id: str
    question: str = Field(min_length=1,max_length=2000)
    conversation_id: str | None = None
    detailed: bool = False


class CreateTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request: dict
    kb_id: str | None = None
    answer_id: str | None = None
    use_original_parameters: bool = False
    conversation_id: str | None = None


class UpdateFacts(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: dict
    expected_facts_revision: int = Field(ge=1)


class SubmitTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    proposal_id: str
    content_digest: str
    accepted: bool = Field(strict=True)
    expected_facts_revision: int = Field(ge=1)


class TaskMessage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str = Field(min_length=1,max_length=2000)
    message_id: str = Field(min_length=1,max_length=100)
    expected_facts_revision: int = Field(ge=1)
    detailed:bool=False


class SelectAsset(BaseModel):
    model_config=ConfigDict(extra='forbid')
    asset_id: str
    expected_facts_revision: int = Field(ge=1)
    date_shift_days:int=Field(default=0,ge=0,le=7,strict=True)


class ResolveUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    execution_ceiling: Literal['READ_ONLY','PREVIEW_ONLY','SUBMIT_AFTER_CONFIRMATION']
    expected_facts_revision: int = Field(ge=1)
    reviewed: bool = Field(strict=True)


class DeskAction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['loan','repair']
    ticket_id:str
    action:str
    expected_version:int=Field(ge=1)
    note:str=Field(min_length=1,max_length=1000)
    loan_end:date|None=None


class DeskCommit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    proposal_id:str
    content_digest:str
    accepted:bool=Field(strict=True)


class AddDirectory(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kb_id: str
    path: str = Field(min_length=1,max_length=1000)


class DocumentPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str|None=Field(default=None,min_length=1,max_length=250)
    active:bool|None=None
    source_type:Literal['policy','wiki','email','ticket','meeting','table','filing']|None=None
    effective_from:date|None=None
    service_tags:list[Literal['loan','repair']]|None=None


class Feedback(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_kind: Literal['answer','task']
    target_id: str
    category: Literal['parse','retrieval','generation','business','ux','other']
    message: str = Field(min_length=1,max_length=2000)


def require_local_request(request: Request):
    """Single-user loopback mode, not an enterprise login or a relaxed legacy ACL."""
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "LOCAL_OWNER_ONLY")
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).netloc != request.url.netloc or urlsplit(origin).scheme != request.url.scheme):
        raise HTTPException(403, "ORIGIN_MISMATCH")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-esa-request") != "1":
        raise HTTPException(403, "LOCAL_REQUEST_HEADER_REQUIRED")


def workspace_router(workspace):
    router = APIRouter(dependencies=[Depends(require_local_request)])

    def service_call(action):
        from app.service_desk.store import ServiceError
        try:return action()
        except ServiceError as exc:raise WorkspaceError(409,exc.code,exc.data) from exc
        except ValueError as exc:raise WorkspaceError(422,'INVALID_REQUEST',{'reason':str(exc)}) from exc

    @router.get("/", include_in_schema=False)
    def home():
        return FileResponse(Path(__file__).with_name("web")/"index.html", headers={"Cache-Control":"no-store"})

    @router.get("/api/status")
    async def status(): return await workspace.status()

    @router.get("/api/settings")
    def settings(): return workspace.config.model_dump()

    @router.patch("/api/settings")
    def update_settings(payload: SettingsPatch):
        from pydantic import ValidationError
        try: return workspace.save_settings(payload.model_dump(exclude_unset=True))
        except ValidationError as exc: raise HTTPException(422,"INVALID_SETTINGS") from exc

    @router.get("/api/history")
    def history():
        return {"tasks":workspace.service.list(),"conversations":workspace.library.answers(),
                'threads':workspace.conversations.list(),"database":str(workspace.db_path)}

    @router.get('/api/library')
    def library(): return workspace.library.list()

    @router.post('/api/library')
    def create_library(payload: CreateKnowledgeBase): return workspace.library.create(payload.name)

    @router.post('/api/library/{kb_id}/documents')
    async def upload(kb_id: str, file: UploadFile = File(...)):
        try: return await workspace.library.upload(kb_id,file.filename,await file.read(20*1024*1024+1))
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc

    @router.post('/api/library/{kb_id}/documents/batch')
    async def batch_upload(kb_id:str,files:list[UploadFile]=File(...)):
        if len(files)>20:raise WorkspaceError(422,'BATCH_FILE_LIMIT')
        total=0;results=[]
        for file in files:
            content=await file.read(20*1024*1024+1);total+=len(content)
            if total>64*1024*1024:raise WorkspaceError(422,'BATCH_SIZE_LIMIT',{'completed':results})
            try:results.append(await workspace.library.upload(kb_id,file.filename,content))
            except ValueError as exc:results.append({'name':file.filename,'status':'FAILED','error':str(exc)})
        return {'documents':results,'successful':sum(r['status']=='PARSED' for r in results),'index_update_required':True}

    @router.post('/api/library/{kb_id}/build')
    async def build(kb_id: str):
        try: return workspace.library.enqueue(kb_id)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc

    @router.post('/api/library/{kb_id}/samples')
    async def import_samples(kb_id:str):
        try:return await workspace.library.import_samples(kb_id)
        except ValueError as exc:raise WorkspaceError(422,'SAMPLE_IMPORT_FAILED',{'reason':str(exc)}) from exc

    @router.post('/api/library/directories')
    def add_directory(payload: AddDirectory):
        return service_call(lambda:workspace.library.register_directory(payload.kb_id,payload.path))

    @router.post('/api/library/directories/{source_id}/sync')
    async def sync_directory(source_id: str):
        try:return await workspace.library.sync_directory(source_id)
        except ValueError as exc:raise WorkspaceError(422,'DIRECTORY_SYNC_FAILED',{'reason':str(exc)}) from exc

    @router.post('/api/feedback')
    def feedback(payload: Feedback):return service_call(lambda:workspace.library.feedback(**payload.model_dump()))

    @router.get('/api/feedback')
    def feedback_list():return workspace.library.feedbacks()

    @router.get('/api/feedback/{feedback_id}/case')
    def feedback_case(feedback_id: str):return service_call(lambda:workspace.library.feedback_case(feedback_id))

    @router.get('/api/documents/{doc_id}')
    def document(doc_id: str):
        with workspace.library.db() as db:
            row = db.execute('SELECT name,version,parsed,status,active,metadata FROM library_documents WHERE id=?',(doc_id,)).fetchone()
        if not row: raise HTTPException(404,'DOCUMENT_NOT_FOUND')
        return {'name':row['name'],'version':row['version'],'status':row['status'],'active':bool(row['active']),
                'parsed':json.loads(row['parsed']) if row['parsed'] else None,'metadata':json.loads(row['metadata'])}

    @router.patch('/api/documents/{doc_id}')
    def update_document(doc_id:str,payload:DocumentPatch):
        return service_call(lambda:workspace.library.update_document(doc_id,payload.model_dump(mode='json',exclude_unset=True)))

    @router.post('/api/documents/{doc_id}/retry')
    async def retry_document(doc_id:str):
        try:return await workspace.library.retry_document(doc_id)
        except (ValueError,OSError) as exc:raise WorkspaceError(422,'DOCUMENT_RETRY_FAILED',{'reason':str(exc)}) from exc

    @router.get('/api/documents/{doc_id}/excerpt')
    def excerpt(doc_id:str,index_run_id:str,target_type:Literal['chunk','parent','document'],target_id:str):
        return service_call(lambda:workspace.library.excerpt(doc_id,index_run_id,target_type,target_id))

    @router.post('/api/knowledge/ask')
    async def ask(payload: AskKnowledge):
        try:
            run=workspace.runs.start('knowledge',payload.model_dump())
            # Compatibility synchronous result; the durable run is the same one as the UI.
            await workspace.runs.tasks[run['id']]
            done=workspace.runs.get(run['id'])
            if done['status']!='succeeded':raise HTTPException(503,done['error'] or done['status'])
            return done['result']
        except (ValueError,FileNotFoundError) as exc: raise HTTPException(422,str(exc)) from exc
        except httpx.HTTPError as exc: raise HTTPException(503,'MODEL_UNAVAILABLE: '+str(exc)) from exc

    @router.post('/api/knowledge/runs',status_code=202)
    async def knowledge_run(payload: AskKnowledge):
        try:return workspace.runs.start('knowledge',payload.model_dump())
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc

    @router.get('/api/runs/{run_id}')
    def run(run_id: str):
        try:return workspace.runs.get(run_id)
        except ValueError as exc:raise HTTPException(404,str(exc)) from exc

    @router.post('/api/runs/{run_id}/cancel')
    def cancel_run(run_id: str):
        workspace.runs.get(run_id);workspace.runs.cancel(run_id)
        return {'requested':'cancelled','id':run_id}

    @router.get('/api/tasks')
    def tasks():return workspace.service.list()

    @router.get('/api/services')
    def services():
        from app.service_desk.catalog import SERVICES
        return [service.public() for service in SERVICES.values()]

    def desk():
        from app.service_desk.lifecycle import Lifecycle
        return Lifecycle(workspace.service.store)

    @router.get('/api/service-desk')
    def service_desk():
        from app.workbench_service import local_actor
        return service_call(lambda:desk().list(local_actor()))

    @router.post('/api/service-desk/proposals')
    def desk_preview(payload:DeskAction):
        from app.workbench_service import local_actor
        return service_call(lambda:desk().propose(local_actor(),**payload.model_dump(mode='json')))

    @router.post('/api/service-desk/commit')
    def desk_commit(payload:DeskCommit):
        from app.workbench_service import local_actor
        return service_call(lambda:desk().commit(local_actor(),**payload.model_dump()))

    @router.post('/api/tasks')
    async def create_task(payload: CreateTask):
        if payload.use_original_parameters and not payload.answer_id:
            raise WorkspaceError(422,'ORIGINAL_QUESTION_REQUIRED')
        def create():
            if payload.kb_id:workspace.library.require(payload.kb_id)
            if payload.request.get('kind')=='knowledge' and not payload.kb_id and not payload.answer_id:
                raise ValueError('KNOWLEDGE_BASE_REQUIRED')
            answer=None
            if payload.answer_id:
                with workspace.library.db() as db:answer=db.execute('SELECT * FROM knowledge_answers WHERE id=?',(payload.answer_id,)).fetchone()
                if not answer or (payload.kb_id and answer['kb_id']!=payload.kb_id):raise ValueError('ANSWER_NOT_BOUND')
            task=workspace.service.create(payload.request,payload.kb_id or (answer['kb_id'] if answer else None),
                conversation_id=payload.conversation_id or (answer['conversation_id'] if answer else None))
            if answer:
                from app.workbench_service import local_actor
                with workspace.service.store.transaction() as db:
                    current=workspace.service.store._task(db,local_actor(),task['task_id'])
                    current['linked_answer_id']=answer['id'];workspace.service.store._save(db,current)
                task=workspace.service.view(task['task_id'])
            return task
        task=service_call(create)
        if payload.use_original_parameters:
            with workspace.library.db() as db:
                source=db.execute('SELECT question FROM knowledge_answers WHERE id=?',(payload.answer_id,)).fetchone()
            task['prefill_run']=workspace.runs.start('message',{'task_id':task['task_id'],
                'text':source['question'],'message_id':'answer-'+task['task_id'],
                'expected_facts_revision':task['facts_revision']})
        return task

    @router.get('/api/tasks/{task_id}')
    def task(task_id: str):return service_call(lambda:workspace.service.view(task_id))

    @router.get('/api/tasks/{task_id}/alternatives')
    def alternatives(task_id: str):return service_call(lambda:workspace.service.alternatives(task_id))

    @router.post('/api/tasks/{task_id}/asset')
    def select_asset(task_id: str,payload: SelectAsset):
        return service_call(lambda:workspace.service.choose_asset(task_id,payload.asset_id,payload.expected_facts_revision,payload.date_shift_days))

    @router.patch('/api/tasks/{task_id}/facts')
    def facts(task_id: str,payload: UpdateFacts):
        return service_call(lambda:workspace.service.facts(task_id,payload.changes,payload.expected_facts_revision))

    @router.post('/api/tasks/{task_id}/runs',status_code=202)
    async def start_task(task_id: str):
        return service_call(lambda:workspace.runs.start('service',{'task_id':task_id}))

    @router.post('/api/tasks/{task_id}/submit')
    def submit(task_id: str,payload: SubmitTask):return service_call(lambda:workspace.service.submit(task_id,payload.model_dump()))

    @router.post('/api/tasks/{task_id}/messages',status_code=202)
    async def message(task_id: str,payload: TaskMessage):
        return service_call(lambda:workspace.runs.start('message',{'task_id':task_id,**payload.model_dump()}))

    @router.post('/api/tasks/{task_id}/resolve-update')
    def resolve_update(task_id: str,payload: ResolveUpdate):
        return service_call(lambda:workspace.service.resolve_update(task_id,payload.execution_ceiling,payload.expected_facts_revision,payload.reviewed))

    @router.post('/api/tasks/{task_id}/cancel')
    def cancel(task_id: str):
        def execute():
            from app.workbench_service import local_actor
            workspace.service.store.cancel_task(local_actor(),task_id)
            for run_id in list(workspace.runs.tasks):
                if workspace.runs.get(run_id)['target']==task_id:workspace.runs.cancel(run_id)
            return workspace.service.view(task_id)
        return service_call(execute)

    @router.get('/api/runs/{run_id}/events')
    async def events(run_id: str,request: Request,after_seq: int=0):
        from fastapi.responses import StreamingResponse
        try:after_seq=max(after_seq,int(request.headers.get('last-event-id','0')))
        except ValueError:raise HTTPException(422,'INVALID_EVENT_CURSOR')
        async def stream():
            seq=after_seq
            while True:
                for row in workspace.runs.events(run_id,seq):
                    seq=row['seq']
                    yield 'id: '+str(seq)+'\nevent: progress\ndata: '+json.dumps(row,ensure_ascii=False)+'\n\n'
                if workspace.runs.get(run_id)['status'] not in ('queued','running'):break
                yield ': keepalive\n\n';await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream')

    from app.api.conversation_routes import conversation_router
    router.include_router(conversation_router(workspace,service_call))
    return router
