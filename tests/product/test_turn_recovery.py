"""Current product factory with real persistence and only the external answer replaced."""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.workspace import initialize
from app.workbench_app import create_workbench_app
from app.workbench_service import local_actor


def product(root):
    import httpx

    initialize(root, sample=True)

    def external(request):
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        raise AssertionError("Program tests cannot send to a real model: " + str(request.url))

    return TestClient(
        create_workbench_app(
            Settings(workbench_enabled=True, data_dir=root, sqlite_path=root / "app.sqlite3"),
            model_transport=httpx.MockTransport(external),
        )
    )


def test_legacy_task_knowledge_is_not_misread_as_a_published_answer(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        conversation = w.conversations.create()
        payload = {
            "task_id": "historical-task",
            "knowledge": {"rule-ref": {"text": "原始业务规则"}},
            "facts": {"purpose": "历史记录"},
        }
        turn = w.conversations.append(
            conversation["id"], "assistant", "result", "已读取规则", payload
        )
        response = client.get("/api/conversations/" + conversation["id"])
        assert response.status_code == 200
        assert response.json()["turns"][0]["payload"]["knowledge"] is None
        assert w.conversations.turns(conversation["id"])[0]["payload"] == payload


def test_actual_http_retry_route_runs_in_the_product_event_loop(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        cid = w.conversations.create("test-kb")["id"]
        attempts = []

        async def answer(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("test external failure")
            return {"id": "test-answer", "result": {"answer": "test-only external reply"}}

        w.library.answer = answer

        async def wait(run_id):
            task = w.runs.tasks.get(run_id)
            if task:
                await task

        headers = {"X-ESA-Request": "1"}
        first = client.post(
            "/api/conversations/" + cid + "/turns",
            json={"text": "真实HTTP路径", "message_id": "http-retry"},
            headers=headers,
        )
        assert first.status_code == 202
        client.portal.call(wait, first.json()["id"])
        retry = client.post(
            "/api/product/conversations/" + cid + "/turns/http-retry/retry",
            json={},
            headers=headers,
        )
        assert retry.status_code == 202, retry.text
        client.portal.call(wait, retry.json()["id"])
        assert w.runs.get(retry.json()["id"])["status"] == "succeeded"
        assert len([t for t in w.conversations.turns(cid) if t["role"] == "user"]) == 1


def test_knowledge_failure_retry_reuses_user_turn(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        cid = w.conversations.create("test-kb")["id"]
        calls = []

        async def answer(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ConnectionError("deliberately unavailable external model")
            return {"id": "answer-test", "result": {"answer": "external adapter test answer"}}

        w.library.answer = answer

        async def scenario():
            payload = {
                "conversation_id": cid,
                "message_id": "same-user-turn",
                "text": "期限有哪些条件？",
            }
            first = w.runs.start("conversation", payload)
            await w.runs.tasks[first["id"]]
            assert w.runs.get(first["id"])["status"] == "failed"
            assert w.conversations.turns(cid)[0]["status"] == "FAILED"
            second = w.runs.start("conversation", payload)
            await w.runs.tasks[second["id"]]
            assert w.runs.get(second["id"])["status"] == "succeeded"
            turns = w.conversations.turns(cid)
            assert len([t for t in turns if t["role"] == "user"]) == 1
            assert turns[0]["status"] == "DONE"
            assert len(w.conversations.coordinator.attempts("same-user-turn")) == 2

        asyncio.run(scenario())


def test_cancelled_knowledge_turn_is_terminal_and_retryable(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        cid = w.conversations.create("test-kb")["id"]

        async def scenario():
            entered = asyncio.Event()

            async def answer(*args, **kwargs):
                entered.set()
                await asyncio.Event().wait()

            w.library.answer = answer
            run = w.runs.start(
                "conversation",
                {"conversation_id": cid, "message_id": "cancel-one", "text": "规则？"},
            )
            handle = w.runs.tasks[run["id"]]
            await asyncio.wait_for(entered.wait(), 2)
            w.runs.cancel(run["id"])
            await handle
            assert w.runs.get(run["id"])["status"] == "cancelled"
            assert w.conversations.turns(cid)[0]["status"] == "CANCELLED"

        asyncio.run(scenario())


def test_cancelled_task_does_not_capture_later_knowledge_or_reopen(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        cid = w.conversations.create("test-kb")["id"]
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True},
            kb_id="test-kb",
            conversation_id=cid,
        )
        w.service.store.cancel_task(local_actor(), task["task_id"])
        calls = []

        async def answer(*args, **kwargs):
            calls.append(args)
            return {"id": "after-cancel", "result": {"answer": "knowledge after cancellation"}}

        w.library.answer = answer
        result = asyncio.run(w.conversations.turn(cid, "现在只解释制度", "after-cancel"))
        assert result["id"] == "after-cancel" and len(calls) == 1
        assert w.service.view(task["task_id"])["status"] == "CANCELLED"
        assert w.conversations.get(cid)["active_task_id"] is None
        assert task["task_id"] in w.conversations.get(cid)["task_history"]


def test_restart_marks_orphan_turn_interrupted_without_duplication(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        cid = w.conversations.create("test-kb")["id"]
        w.conversations.append(
            cid, "user", "message", "保留的原始问题", turn_id="orphan", status="PENDING"
        )
    with product(tmp_path) as client:
        assert client.app.state.workspace.conversations.turns(cid)[0]["status"] == "INTERRUPTED"
