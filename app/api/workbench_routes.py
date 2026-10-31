"""HTTP adaptation; domain rules remain in application services."""

from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal
import asyncio, json
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
import httpx
from app.api.workbench_errors import WorkspaceError
from app.domain.product_views import RunView
from app.api.workbench_contracts import (
    SettingsPatch,
    CreateKnowledgeBase,
    AskKnowledge,
    CreateTask,
    UpdateFacts,
    SubmitTask,
    TaskMessage,
    SelectAsset,
    ResolveUpdate,
    DeskAction,
    DeskCommit,
    AddDirectory,
    DocumentPatch,
    Feedback,
)


def require_local_request(request: Request):
    """Single-user loopback mode, not an enterprise login or a relaxed legacy ACL."""
    if request.client and request.client.host not in (
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
    ):
        raise HTTPException(403, "LOCAL_OWNER_ONLY")
    origin = request.headers.get("origin")
    if origin and (
        urlsplit(origin).netloc != request.url.netloc
        or urlsplit(origin).scheme != request.url.scheme
    ):
        raise HTTPException(403, "ORIGIN_MISMATCH")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.headers.get("x-esa-request") != "1"
    ):
        raise HTTPException(403, "LOCAL_REQUEST_HEADER_REQUIRED")


def workspace_router(workspace):
    router = APIRouter(dependencies=[Depends(require_local_request)])

    def service_call(action):
        from app.service_desk.store import ServiceError

        try:
            return action()
        except ServiceError as exc:
            raise WorkspaceError(409, exc.code, exc.data) from exc
        except ValueError as exc:
            raise WorkspaceError(422, "INVALID_REQUEST", {"reason": str(exc)}) from exc

    @router.get("/", include_in_schema=False)
    def home():
        frontend = (Path(__file__).resolve().parents[1] / "web_dist") / "index.html"
        if not frontend.is_file():
            raise WorkspaceError(503, "FRONTEND_NOT_BUILT")
        return FileResponse(frontend, headers={"Cache-Control": "no-store"})

    @router.get("/api/status")
    async def status():
        return await workspace.status()

    @router.get("/api/settings")
    def settings():
        return workspace.config.model_dump()

    @router.patch("/api/settings")
    def update_settings(payload: SettingsPatch):
        from pydantic import ValidationError

        try:
            return workspace.save_settings(payload.model_dump(exclude_unset=True))
        except ValidationError as exc:
            raise HTTPException(422, "INVALID_SETTINGS") from exc

    @router.get("/api/history")
    def history():
        return {
            "tasks": workspace.service.list(),
            "conversations": workspace.library.answers(),
            "threads": workspace.conversations.list(),
            "database": str(workspace.db_path),
        }

    @router.get("/api/library")
    def library():
        return workspace.library.list()

    @router.post("/api/library")
    def create_library(payload: CreateKnowledgeBase):
        return workspace.library.create(payload.name)

    @router.post("/api/library/{kb_id}/documents")
    async def upload(kb_id: str, file: UploadFile = File(...)):
        try:
            result = await workspace.library.upload(
                kb_id, file.filename, await file.read(20 * 1024 * 1024 + 1)
            )
            if result["status"] == "PARSED":
                result = {**result, "index_job": workspace.library.enqueue(kb_id, changed=True)}
            return result
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/library/{kb_id}/documents/batch")
    async def batch_upload(kb_id: str, files: list[UploadFile] = File(...)):
        if len(files) > 20:
            raise WorkspaceError(422, "BATCH_FILE_LIMIT")
        total = 0
        results = []
        for file in files:
            content = await file.read(20 * 1024 * 1024 + 1)
            total += len(content)
            if total > 64 * 1024 * 1024:
                raise WorkspaceError(422, "BATCH_SIZE_LIMIT", {"completed": results})
            try:
                results.append(await workspace.library.upload(kb_id, file.filename, content))
            except ValueError as exc:
                results.append({"name": file.filename, "status": "FAILED", "error": str(exc)})
        successful = sum(r["status"] == "PARSED" for r in results)
        return {
            "documents": results,
            "successful": successful,
            "index_job": workspace.library.enqueue(kb_id, changed=True) if successful else None,
        }

    @router.post("/api/library/{kb_id}/build")
    async def build(kb_id: str):
        try:
            return workspace.library.enqueue(kb_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/library/{kb_id}/samples")
    async def import_samples(kb_id: str):
        try:
            return await workspace.library.import_samples(kb_id)
        except ValueError as exc:
            raise WorkspaceError(422, "SAMPLE_IMPORT_FAILED", {"reason": str(exc)}) from exc

    @router.post("/api/library/directories")
    def add_directory(payload: AddDirectory):
        return service_call(
            lambda: workspace.library.register_directory(payload.kb_id, payload.path)
        )

    @router.post("/api/library/directories/{source_id}/sync")
    async def sync_directory(source_id: str):
        try:
            return await workspace.library.sync_directory(source_id)
        except ValueError as exc:
            raise WorkspaceError(422, "DIRECTORY_SYNC_FAILED", {"reason": str(exc)}) from exc

    @router.post("/api/feedback")
    def feedback(payload: Feedback):
        return service_call(lambda: workspace.library.feedback(**payload.model_dump()))

    @router.get("/api/feedback")
    def feedback_list():
        return workspace.library.feedbacks()

    @router.get("/api/feedback/{feedback_id}/case")
    def feedback_case(feedback_id: str):
        return service_call(lambda: workspace.library.feedback_case(feedback_id))

    @router.get("/api/documents/{doc_id}")
    def document(doc_id: str):
        with workspace.library.db() as db:
            row = db.execute(
                "SELECT name,version,parsed,status,active,metadata FROM library_documents WHERE id=?",
                (doc_id,),
            ).fetchone()
        if not row:
            raise HTTPException(404, "DOCUMENT_NOT_FOUND")
        return {
            "name": row["name"],
            "version": row["version"],
            "status": row["status"],
            "active": bool(row["active"]),
            "parsed": json.loads(row["parsed"]) if row["parsed"] else None,
            "metadata": json.loads(row["metadata"]),
        }

    @router.patch("/api/documents/{doc_id}")
    async def update_document(doc_id: str, payload: DocumentPatch):
        changes = payload.model_dump(mode="json", exclude_unset=True)
        result = service_call(lambda: workspace.library.update_document(doc_id, changes))
        if set(changes) - {"name"}:
            result = {
                **result,
                "index_job": workspace.library.enqueue(result["kb_id"], changed=True),
            }
        return result

    @router.post("/api/documents/{doc_id}/retry")
    async def retry_document(doc_id: str):
        try:
            return await workspace.library.retry_document(doc_id)
        except (ValueError, OSError) as exc:
            raise WorkspaceError(422, "DOCUMENT_RETRY_FAILED", {"reason": str(exc)}) from exc

    @router.get("/api/documents/{doc_id}/excerpt")
    def excerpt(
        doc_id: str,
        index_run_id: str,
        target_type: Literal["chunk", "parent", "document"],
        target_id: str,
    ):
        return service_call(
            lambda: workspace.library.excerpt(doc_id, index_run_id, target_type, target_id)
        )

    @router.post("/api/knowledge/ask")
    async def ask(payload: AskKnowledge):
        try:
            run = workspace.runs.start("knowledge", payload.model_dump())
            # Compatibility synchronous result; the durable run is the same one as the UI.
            await workspace.runs.tasks[run["id"]]
            done = workspace.runs.get(run["id"])
            if done["status"] != "succeeded":
                raise HTTPException(503, done["error"] or done["status"])
            return done["result"]
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(503, "MODEL_UNAVAILABLE: " + str(exc)) from exc

    @router.post("/api/knowledge/runs", status_code=202)
    async def knowledge_run(payload: AskKnowledge):
        try:
            return workspace.runs.start("knowledge", payload.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/runs/{run_id}", response_model=RunView)
    def run(run_id: str):
        try:
            return workspace.runs.get(run_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        workspace.runs.get(run_id)
        workspace.runs.cancel(run_id)
        return {"requested": "cancelled", "id": run_id}

    @router.get("/api/tasks")
    def tasks():
        return workspace.service.list()

    @router.get("/api/services")
    def services():
        from app.service_desk.catalog import SERVICES

        return [service.public() for service in SERVICES.values()]

    def desk():
        from app.service_desk.lifecycle import Lifecycle

        return Lifecycle(workspace.service.store)

    @router.get("/api/service-desk")
    def service_desk():
        from app.workbench_service import local_actor

        return service_call(lambda: desk().list(local_actor()))

    @router.post("/api/service-desk/proposals")
    def desk_preview(payload: DeskAction):
        from app.workbench_service import local_actor

        return service_call(
            lambda: desk().propose(local_actor(), **payload.model_dump(mode="json"))
        )

    @router.post("/api/service-desk/commit")
    def desk_commit(payload: DeskCommit):
        from app.workbench_service import local_actor

        return service_call(lambda: desk().commit(local_actor(), **payload.model_dump()))

    @router.post("/api/tasks")
    async def create_task(payload: CreateTask):
        if payload.use_original_parameters and not payload.answer_id:
            raise WorkspaceError(422, "ORIGINAL_QUESTION_REQUIRED")

        def create():
            if payload.kb_id:
                workspace.library.require(payload.kb_id)
            if (
                payload.request.get("kind") == "knowledge"
                and not payload.kb_id
                and not payload.answer_id
            ):
                raise ValueError("KNOWLEDGE_BASE_REQUIRED")
            answer = None
            if payload.answer_id:
                with workspace.library.db() as db:
                    answer = db.execute(
                        "SELECT * FROM knowledge_answers WHERE id=?", (payload.answer_id,)
                    ).fetchone()
                if not answer or (payload.kb_id and answer["kb_id"] != payload.kb_id):
                    raise ValueError("ANSWER_NOT_BOUND")
            task = workspace.service.create(
                payload.request,
                payload.kb_id or (answer["kb_id"] if answer else None),
                conversation_id=payload.conversation_id
                or (answer["conversation_id"] if answer else None),
            )
            if answer:
                from app.workbench_service import local_actor

                with workspace.service.store.transaction() as db:
                    current = workspace.service.store._task(db, local_actor(), task["task_id"])
                    current["linked_answer_id"] = answer["id"]
                    workspace.service.store._save(db, current)
                task = workspace.service.view(task["task_id"])
            return task

        task = service_call(create)
        if payload.use_original_parameters:
            with workspace.library.db() as db:
                source = db.execute(
                    "SELECT question FROM knowledge_answers WHERE id=?", (payload.answer_id,)
                ).fetchone()
            task["prefill_run"] = workspace.runs.start(
                "message",
                {
                    "task_id": task["task_id"],
                    "text": source["question"],
                    "message_id": "answer-" + task["task_id"],
                    "expected_facts_revision": task["facts_revision"],
                },
            )
        return task

    @router.get("/api/tasks/{task_id}")
    def task(task_id: str):
        return service_call(lambda: workspace.service.view(task_id))

    @router.get("/api/tasks/{task_id}/alternatives")
    def alternatives(task_id: str):
        return service_call(lambda: workspace.service.alternatives(task_id))

    @router.post("/api/tasks/{task_id}/asset")
    def select_asset(task_id: str, payload: SelectAsset):
        return service_call(
            lambda: workspace.service.choose_asset(
                task_id, payload.asset_id, payload.expected_facts_revision, payload.date_shift_days
            )
        )

    @router.patch("/api/tasks/{task_id}/facts")
    def facts(task_id: str, payload: UpdateFacts):
        return service_call(
            lambda: workspace.service.facts(
                task_id, payload.changes, payload.expected_facts_revision
            )
        )

    @router.post("/api/tasks/{task_id}/runs", status_code=202)
    async def start_task(task_id: str):
        return service_call(lambda: workspace.runs.start("service", {"task_id": task_id}))

    @router.post("/api/tasks/{task_id}/submit")
    def submit(task_id: str, payload: SubmitTask):
        return service_call(lambda: workspace.service.submit(task_id, payload.model_dump()))

    @router.post("/api/tasks/{task_id}/messages", status_code=202)
    async def message(task_id: str, payload: TaskMessage):
        return service_call(
            lambda: workspace.runs.start("message", {"task_id": task_id, **payload.model_dump()})
        )

    @router.post("/api/tasks/{task_id}/resolve-update")
    def resolve_update(task_id: str, payload: ResolveUpdate):
        return service_call(
            lambda: workspace.service.resolve_update(
                task_id,
                payload.execution_ceiling,
                payload.expected_facts_revision,
                payload.reviewed,
            )
        )

    @router.post("/api/tasks/{task_id}/cancel")
    def cancel(task_id: str):
        def execute():
            from app.workbench_service import local_actor

            current = workspace.service.view(task_id)
            cid = current.get("conversation_id")
            active = workspace.conversations.get(cid)["active_task_id"] if cid else None
            workspace.service.store.cancel_task(local_actor(), task_id)
            for run_id in list(workspace.runs.tasks):
                if workspace.runs.get(run_id)["target"] in (
                    {task_id, cid} if active == task_id else {task_id}
                ):
                    workspace.runs.cancel(run_id)
            return workspace.service.view(task_id)

        return service_call(execute)

    @router.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after_seq: int = 0):
        from fastapi.responses import StreamingResponse

        try:
            after_seq = max(after_seq, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(422, "INVALID_EVENT_CURSOR")

        async def stream():
            seq = after_seq
            while True:
                for row in workspace.runs.events(run_id, seq):
                    seq = row["seq"]
                    yield (
                        "id: "
                        + str(seq)
                        + "\nevent: progress\ndata: "
                        + json.dumps(row, ensure_ascii=False)
                        + "\n\n"
                    )
                if workspace.runs.get(run_id)["status"] not in ("queued", "running"):
                    break
                yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    from app.api.conversation_routes import conversation_router

    router.include_router(conversation_router(workspace, service_call))
    from app.api.product_routes import product_router

    router.include_router(product_router(workspace, service_call))
    return router
