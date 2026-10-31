"""Current factory and SQLite. Only the external model decision is a double."""

from tests.product.test_turn_recovery import product
from tests.product.test_061_recovery import H, wait
from tests.vnext.test_conversations import SequenceModel


def test_missing_repair_input_survives_finalization_and_resumes_same_item(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = w.service.create(
            {"kind": "repair", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True}
        )
        tid, cid = task["task_id"], task["conversation_id"]
        model = SequenceModel(
            [
                (
                    "update_parameters",
                    {
                        "changes": {"description": "笔记本无法开机"},
                        "turn_request": {"preview": True, "knowledge_quote": ""},
                    },
                )
            ],
            [
                (
                    "ask_user",
                    {
                        "fields": ["asset_id", "impact"],
                        "reason": "missing",
                        "question": "请补充设备和影响程度。",
                    },
                )
            ],
        )
        w.models.chat = model.chat
        run = c.post(
            f"/api/conversations/{cid}/turns",
            headers=H,
            json={
                "message_id": "repair-fields",
                "text": "笔记本无法开机，帮我准备报修预览。",
            },
        )
        assert wait(c, run.json()["id"])["status"] == "succeeded"
        actual = w.service.view(tid)
        assert actual["status"] == "WAITING_USER"
        assert actual["assistant_text"] == actual["question"]
        assert set(actual["missing_fields"]) == {"asset_id", "impact"}
        view = c.get(f"/api/product/tasks/{tid}").json()
        assert view["next_action"]["kind"] == "input"
        assert set(view["next_action"]["fields"]) == {"asset_id", "impact"}
        assert view["turn_delivery"]["status"] == "waiting_input"
        assert not view["turn_delivery"]["retryable"] and not view["can_run"]
        turn = next(t for t in w.conversations.turns(cid) if t["id"] == "repair-fields")
        assert turn["status"] == "WAITING_USER"
        retry = c.post(
            f"/api/product/conversations/{cid}/turns/repair-fields/retry", headers=H, json={}
        )
        assert retry.status_code == 409 and len(model.calls) == 2
        changed = c.patch(
            f"/api/tasks/{tid}/facts",
            headers=H,
            json={
                "changes": {"asset_id": "employee-laptop-1", "impact": "high"},
                "expected_facts_revision": actual["facts_revision"],
            },
        )
        assert changed.status_code == 200
        ready = c.post(
            f"/api/product/tasks/{tid}/prepare",
            headers=H,
            json={
                "expected_facts_revision": changed.json()["facts_revision"],
            },
        )
        assert ready.status_code == 200, ready.text
        assert ready.json()["preview"] and not ready.json()["receipt"]
        with w.service.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM it_repair_tickets").fetchone()[0] == 0
