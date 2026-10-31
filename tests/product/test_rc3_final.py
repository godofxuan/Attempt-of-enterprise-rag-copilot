"""Current HTTP factory/SQLite; only external model and answer calls are doubles."""

import json
from datetime import timedelta

import pytest

from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import H, wait
from tests.vnext.test_conversations import SequenceModel
from app.service_desk.store import ServiceError
from app.workbench_service import local_actor


@pytest.mark.parametrize("preview", [False, True])
def test_knowledge_recovery_has_no_unrelated_preparation_dependency(tmp_path, preview):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        kb = w.library.create("合成知识恢复")["id"]
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True}, kb_id=kb
        )
        tid, cid = task["task_id"], task["conversation_id"]
        calls = []

        async def answer(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise ServiceError("TRANSIENT_TOOL_FAILURE")
            return {
                "id": "recovered",
                "result": {"mode": "not_found", "answer": "合成无证据结果", "sources": []},
            }

        w.library.answer = answer
        model = SequenceModel(
            [
                (
                    "update_parameters",
                    {
                        "changes": {},
                        "turn_request": {"preview": preview, "knowledge_quote": "借用期限"},
                    },
                )
            ],
            [("knowledge_answer", {"question": "借用期限"})],
            [("finish", {})],
        )
        w.models.chat = model.chat
        run = c.post(
            f"/api/conversations/{cid}/turns",
            headers=H,
            json={
                "text": "先解释借用期限，日期尚未决定。",
                "message_id": "recover",
                "detailed": True,
            },
        )
        assert wait(c, run.json()["id"])["status"] == "succeeded"
        view = c.get(f"/api/product/tasks/{tid}").json()
        assert view["turn_delivery"]["status"] == "partial"
        assert view["turn_delivery"]["retryable"]
        assert view["next_action"]["kind"] == "retry_knowledge"
        assert view["preview"] is None and view["receipt"] is None
        # Persisted rc3 waiting turns must also be recoverable after an upgrade.
        with w.conversations.db() as db:
            db.execute("UPDATE conversation_turns SET status='WAITING_USER' WHERE id='recover'")
        retry = c.post(f"/api/product/conversations/{cid}/turns/recover/retry", headers=H, json={})
        assert retry.status_code == 202, retry.text
        assert wait(c, retry.json()["id"])["status"] == "succeeded"
        assert len(model.calls) == 3 and len(calls) == 2
        assert calls[1][1]["detailed"] is True
        actual = w.service.view(tid)
        assert actual["facts"] == {} and not actual["preview"] and not actual["receipt"]
        delivery = c.get(f"/api/product/tasks/{tid}").json()["turn_delivery"]
        assert delivery["pending"] == (["preview"] if preview else [])
        assert delivery["status"] == ("waiting_input" if preview else "complete")
        with w.service.store.transaction() as db:
            assert db.execute("SELECT count(*) FROM action_proposals").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM tickets").fetchone()[0] == 0


def test_old_answer_by_primary_key_keeps_ownership_context_and_source_notices(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        with w.library.db() as db:
            for i in range(55):
                db.execute(
                    "INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES(?,?,?,?,?,?)",
                    (
                        f"answer-{i}",
                        "original-conversation",
                        "original-kb",
                        f"原问题{i}",
                        json.dumps({"mode": "not_found", "answer": "无证据", "sources": []}),
                        "old-generation",
                    ),
                )
        old = c.get("/api/product/answers/answer-0")
        assert old.status_code == 200, old.text
        assert old.json()["conversation_id"] == "original-conversation"
        assert old.json()["kb_id"] == "original-kb"
        assert old.json()["question"] == "原问题0" and old.json()["source_notices"] == []
        assert c.get("/api/product/answers/nonexistent").status_code == 409


def test_task_pages_search_ties_and_insertions_do_not_lose_history(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        ids = []
        for i in range(55):
            task = w.service.create(
                {"kind": "loan", "execution_ceiling": "READ_ONLY", "confirmed": True}
            )
            ids.append(task["task_id"])
        # Simulate one nonlocal row: pagination cannot bypass the store actor scope.
        with w.service.store.transaction() as db:
            db.execute("UPDATE agent_tasks SET owner='other-owner' WHERE task_id=?", (ids[10],))
        first = c.get("/api/product/tasks/page?limit=11")
        assert first.status_code == 200, first.text
        page = first.json()
        seen = [x["id"] for x in page["items"]]
        newer = w.service.create(
            {"kind": "repair", "execution_ceiling": "READ_ONLY", "confirmed": True}
        )
        while page["next_cursor"] is not None:
            page = c.get(
                "/api/product/tasks/page", params={"limit": 11, "cursor": page["next_cursor"]}
            ).json()
            seen.extend(x["id"] for x in page["items"])
        assert len(seen) == len(set(seen)) == 54
        assert seen == [i for i in reversed(ids) if i != ids[10]]
        assert newer["task_id"] not in seen
        search = c.get("/api/product/tasks/page", params={"q": ids[0]}).json()
        assert [x["id"] for x in search["items"]] == [ids[0]]
        assert c.get("/api/product/tasks/page?q=no-such-record").json() == {
            "items": [],
            "next_cursor": None,
        }
        assert c.get("/api/product/tasks/page?cursor=-1").status_code == 422
        assert c.get("/api/product/tasks/" + ids[10]).status_code == 409


def test_preview_expiry_projection_is_readonly_and_matches_submit_boundary(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        today = w.service.store.today()
        task = w.service.create(
            {
                "kind": "loan",
                "execution_ceiling": "SUBMIT_AFTER_CONFIRMATION",
                "confirmed": True,
                "facts": {
                    "loan_start": str(today + timedelta(days=1)),
                    "loan_end": str(today + timedelta(days=2)),
                    "purpose": "合成截止验证",
                },
            }
        )
        tid = task["task_id"]
        prepared = c.post(
            f"/api/product/tasks/{tid}/prepare",
            headers=H,
            json={"asset_id": "loan-laptop-1", "expected_facts_revision": task["facts_revision"]},
        ).json()
        preview = prepared["preview"]
        clock = w.service.store.clock
        before = w.service.store.get_task(local_actor(), tid)
        w.service.store.clock = lambda: preview["expires_at"] - 0.1
        assert c.get(f"/api/product/tasks/{tid}").json()["can_submit"]
        w.service.store.clock = lambda: preview["expires_at"]
        expired = c.get(f"/api/product/tasks/{tid}").json()
        assert expired["preview_state"] == "expired" and not expired["can_submit"]
        assert expired["next_action"]["kind"] == "prepare"
        assert expired["preview"]["proposal_id"] == preview["proposal_id"]
        assert w.service.store.get_task(local_actor(), tid) == before, (
            "GET must not mutate preview or task"
        )
        args = {
            "proposal_id": preview["proposal_id"],
            "content_digest": preview["content_digest"],
            "expected_facts_revision": prepared["revision"],
            "accepted": True,
        }
        rejected = c.post(f"/api/tasks/{tid}/submit", headers=H, json=args)
        assert (
            rejected.status_code == 409
            and rejected.json()["error"]["code"] == "CONFIRMATION_EXPIRED"
        )
        current = c.get(f"/api/product/tasks/{tid}").json()
        regenerated = c.post(
            f"/api/product/tasks/{tid}/prepare",
            headers=H,
            json={"expected_facts_revision": current["revision"]},
        )
        assert regenerated.status_code == 200 and regenerated.json()["can_submit"]
        assert regenerated.json()["preview"]["proposal_id"] != preview["proposal_id"]
        with w.service.store.transaction() as db:
            assert db.execute("SELECT count(*) FROM tickets").fetchone()[0] == 0
        w.service.store.clock = clock
