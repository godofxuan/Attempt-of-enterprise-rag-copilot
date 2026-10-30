"""Small typed views for the product; domain operations retain their existing APIs."""

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.service_desk.catalog import SERVICES
from app.service_desk.lifecycle import NOTICES
from app.service_desk.store import ServiceError
from app.domain.evidence import AnswerResponse


from app.domain.product_views import (
    PublishedAnswerView,
    FieldView,
    TaskView,
    TicketView,
    ProposalContent,
    ProposalView,
    ReceiptView,
    OutcomeView,
)
from app.service_desk.views import task_view


def product_router(workspace, service_call):
    router = APIRouter(prefix="/api/product")

    @router.post("/shutdown")
    def shutdown():
        callback = getattr(workspace, "request_shutdown", None)
        if callback is None:
            raise ServiceError("NOT_LAUNCHER_OWNED")
        callback()
        return {"stopping": True, "data_preserved": True}

    @router.post("/setup-demo")
    def setup_demo():
        from app.workbench_service import seed_sample

        if workspace.config.sample_data:
            return {"enabled": True}
        if workspace.service.list():
            raise ServiceError("EXISTING_TASKS_PREVENT_DEMO_SEED")
        workspace.save_settings({"sample_data": True})
        seed_sample(workspace.root)
        workspace.service.store.writes_enabled = True
        return {"enabled": True, "origin": "EXPLICIT_LOCAL_SYNTHETIC_SETUP"}

    @router.post("/setup-complete")
    def setup_complete():
        with workspace.service.store.transaction() as db:
            db.execute("INSERT OR REPLACE INTO workspace_meta VALUES('onboarding_completed','1')")
        return {"complete": True}

    @router.get("/answers/{answer_id}", response_model=PublishedAnswerView)
    def answer(answer_id: str):
        def read():
            result = next((a for a in workspace.library.answers() if a["id"] == answer_id), None)
            if result is None:
                raise ServiceError("ANSWER_NOT_FOUND")
            return result

        return service_call(read)

    @router.get("/tasks", response_model=list[TaskView])
    def tasks():
        return [task_view(workspace.service, t["task_id"]) for t in workspace.service.list()]

    @router.get("/tasks/{task_id}", response_model=TaskView)
    def task(task_id: str):
        return service_call(lambda: task_view(workspace.service, task_id))

    @router.get("/tasks/{task_id}/alternatives")
    def alternatives(task_id: str):
        return service_call(lambda: workspace.service.presented_options(task_id))

    @router.post("/conversations/{cid}/turns/{turn_id}/retry", status_code=202)
    def retry(cid: str, turn_id: str):
        def start():
            workspace.conversations.get(cid)
            with workspace.conversations.db() as db:
                row = db.execute(
                    "SELECT * FROM conversation_turns WHERE id=? AND conversation_id=? AND role='user'",
                    (turn_id, cid),
                ).fetchone()
            if not row:
                raise ServiceError("TURN_NOT_FOUND")
            if row["status"] not in {"FAILED", "CANCELLED", "INTERRUPTED"}:
                raise ServiceError("TURN_NOT_RETRYABLE")
            return workspace.runs.start(
                "conversation", {"conversation_id": cid, "text": row["text"], "message_id": turn_id}
            )

        return service_call(start)

    @router.get("/conversations/{cid}/runs")
    def runs(cid: str):
        conversation = workspace.conversations.get(cid)
        targets = [cid, *conversation["task_history"]]
        with workspace.runs.db() as db:
            rows = db.execute(
                "SELECT * FROM workbench_runs WHERE target IN ("
                + ",".join("?" for _ in targets)
                + ") ORDER BY rowid DESC LIMIT 10",
                targets,
            ).fetchall()
        return [
            {"id": r["id"], "kind": r["kind"], "status": r["status"], "error": r["error"]}
            for r in rows
        ]

    return router
