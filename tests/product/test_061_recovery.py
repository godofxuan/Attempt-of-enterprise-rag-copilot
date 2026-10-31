"""0.6.1 contracts through the product factory, SQLite and real Agent tools.

Only network/model boundaries are deterministic doubles. These are not live scores.
"""

import json
from datetime import timedelta

import pytest

from tests.product.test_turn_recovery import product
from tests.vnext.test_conversations import SequenceModel
from tests.vnext.test_service_lifecycle import create
from app.launcher.core import open_workspace, remember, selected_workspace
from app.workspace import initialize
from app.workbench_service import local_actor

H = {"X-ESA-Request": "1"}


def reply(question):
    return {
        "id": "external-test",
        "question": question,
        "result": {"mode": "answered", "answer": "明确标记的外部知识替身", "sources": []},
    }


def wait(client, run_id):
    async def done():
        handle = client.app.state.workspace.runs.tasks.get(run_id)
        if handle:
            await handle

    client.portal.call(done)
    return client.app.state.workspace.runs.get(run_id)


def test_retry_retains_deep_request_and_one_user_turn(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        kb = w.library.create("测试库")["id"]
        cid = w.conversations.create(kb)["id"]
        seen = []

        async def answer(kb_id, question, **options):
            seen.append((kb_id, question, options["detailed"]))
            if len(seen) == 1:
                raise ConnectionError("controlled failure")
            return reply(question)

        w.library.answer = answer
        first = c.post(
            f"/api/conversations/{cid}/turns",
            headers=H,
            json={"text": "比较两份规则", "message_id": "deep", "detailed": True},
        )
        assert wait(c, first.json()["id"])["status"] == "failed"
        retried = c.post(f"/api/product/conversations/{cid}/turns/deep/retry", headers=H, json={})
        assert retried.status_code == 202, retried.text
        assert wait(c, retried.json()["id"])["status"] == "succeeded"
        assert seen == [(kb, "比较两份规则", True)] * 2
        assert len([t for t in w.conversations.turns(cid) if t["role"] == "user"]) == 1
        assert len(w.conversations.coordinator.attempts("deep")) == 2


def test_explicit_binding_recovers_empty_scope_without_rewriting_original(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        cid = w.conversations.create()["id"]
        first = c.post(
            f"/api/conversations/{cid}/turns",
            headers=H,
            json={"text": "解释制度", "message_id": "empty", "detailed": True},
        )
        assert "KNOWLEDGE_BASE_REQUIRED" in wait(c, first.json()["id"])["error"]
        kb = w.library.create("后来创建的库")["id"]
        binding = c.patch(f"/api/conversations/{cid}", headers=H, json={"kb_id": kb})
        assert binding.status_code == 200, binding.text

        async def answer(kb_id, question, **options):
            assert kb_id == kb and options["detailed"]
            return reply(question)

        w.library.answer = answer
        run = c.post(f"/api/product/conversations/{cid}/turns/empty/retry", headers=H, json={})
        assert wait(c, run.json()["id"])["status"] == "succeeded"
        with w.conversations.db() as db:
            rows = db.execute(
                "SELECT payload FROM turn_commands WHERE turn_id='empty' ORDER BY revision"
            ).fetchall()
        assert json.loads(rows[0][0])["kb_id"] is None
        assert json.loads(rows[-1][0])["kb_id"] == kb


def test_retry_cannot_rebind_to_a_later_task_or_reapply_old_facts(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        original = create(w.service, "PREVIEW_ONLY")
        cid = original["conversation_id"]

        async def fail(*a, **kw):
            raise ConnectionError("controlled model failure")

        w.models.chat = fail
        run = c.post(
            f"/api/conversations/{cid}/turns",
            headers=H,
            json={"text": "查询当前申请", "message_id": "old-task"},
        )
        assert wait(c, run.json()["id"])["status"] == "failed"
        latest = w.service.view(original["task_id"])
        changed = w.service.facts(
            original["task_id"], {"purpose": "后续明确修改"}, latest["facts_revision"]
        )
        w.service.store.cancel_task(local_actor(), original["task_id"])
        newer = w.service.create(
            {"kind": "repair", "confirmed": True, "execution_ceiling": "READ_ONLY"},
            conversation_id=cid,
        )
        retried = c.post(
            f"/api/product/conversations/{cid}/turns/old-task/retry", headers=H, json={}
        )
        outcome = wait(c, retried.json()["id"])
        assert outcome["status"] == "failed" and "CANCELLED" in outcome["error"]
        assert w.service.view(original["task_id"])["facts"] == changed["facts"]
        assert w.service.view(newer["task_id"])["facts"] == {}


def test_missing_registered_workspace_never_creates_old_directory(tmp_path):
    old, moved, registry = tmp_path / "原目录", tmp_path / "移动后", tmp_path / "registry.json"
    initialize(old)
    remember(old, registry)
    old.rename(moved)
    assert selected_workspace(None, registry) == old
    with pytest.raises(RuntimeError, match="WORKSPACE_MISSING"):
        open_workspace(old, registry=registry, browser=False)
    assert not old.exists() and (moved / "app.sqlite3").is_file()


def test_server_history_pages_and_search_find_earliest_of_150(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        ids = [w.conversations.create(title=f"旧会话 {i:03d}")["id"] for i in range(150)]
        found, cursor = [], None
        while True:
            params = {"limit": 23}
            if cursor:
                params["cursor"] = cursor
            response = c.get("/api/conversations/page", params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            found.extend(row["id"] for row in page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(found) == len(set(found)) == 150 and set(found) == set(ids)
        search = c.get("/api/conversations/page", params={"q": "旧会话 000"}).json()
        assert [row["id"] for row in search["items"]] == ids[:1]


@pytest.mark.parametrize("order", ["preview_first", "knowledge_first"])
def test_all_proposed_mixed_results_are_delivered_without_extra_model_step(tmp_path, order):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = create(w.service, "PREVIEW_ONLY")
        with w.service.store.transaction() as db:
            current = w.service.store._task(db, local_actor(), task["task_id"])
            current["kb_id"] = "external-test-kb"
            w.service.store._save(db, current)
        called = []

        async def answer(kb, question, **options):
            called.append(question)
            return reply(question)

        w.library.answer = answer
        operations = [
            ("prepare_preview", {"asset_id": "loan-laptop-1"}),
            ("knowledge_answer", {"question": "押金如何规定？"}),
        ]
        if order == "knowledge_first":
            operations.reverse()
        model = SequenceModel(
            [("loan_policy", {}), ("assets_search", {}), ("tickets_list_mine", {})], operations
        )
        w.models.chat = model.chat
        result = c.portal.call(
            w.service.message,
            task["task_id"],
            "完整预览并解释押金，不提交",
            "mixed",
            task["facts_revision"],
        )
        assert called == ["押金如何规定？"]
        assert result["preview"] and result["knowledge_result"]["id"] == "external-test"
        assert "外部知识替身" in result["assistant_text"]
        assert len(model.calls) == 2 and not result["active_run_id"]
        assert not w.service.store.list_tickets(local_actor())


def test_preview_then_date_change_invalidates_and_rebuilds(tmp_path):
    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = create(w.service, "PREVIEW_ONLY")
        end = str(w.service.store.today() + timedelta(days=5))
        model = SequenceModel(
            [("loan_policy", {}), ("assets_search", {}), ("tickets_list_mine", {})],
            [
                ("prepare_preview", {"asset_id": "loan-laptop-1"}),
                ("update_parameters", {"changes": {"loan_end": end}}),
            ],
            [("assets_search", {}), ("prepare_preview", {"asset_id": "loan-laptop-1"})],
        )
        w.models.chat = model.chat
        result = c.portal.call(
            w.service.message,
            task["task_id"],
            "修改日期并准备最新预览",
            "change-after-preview",
            task["facts_revision"],
        )
        assert result["preview"]["content"]["parameters"]["loan_end"] == end
        assert result["preview"]["content"]["task_revision"] == result["facts_revision"]
        with w.service.store.transaction() as db:
            proposals = db.execute(
                "SELECT proposal_id FROM action_proposals WHERE task_id=? ORDER BY rowid",
                (task["task_id"],),
            ).fetchall()
        assert len(proposals) == 2 and result["preview"]["proposal_id"] == proposals[-1][0]
        assert not w.service.store.list_tickets(local_actor())


def test_failed_knowledge_preserves_preview_and_reports_unresolved(tmp_path):
    from app.service_desk.store import ServiceError

    with product(tmp_path) as c:
        w = c.app.state.workspace
        task = create(w.service, "PREVIEW_ONLY")
        with w.service.store.transaction() as db:
            current = w.service.store._task(db, local_actor(), task["task_id"])
            current["kb_id"] = "test"
            w.service.store._save(db, current)

        async def fail(*args, **kwargs):
            raise ServiceError("EVIDENCE_INSUFFICIENT")

        w.library.answer = fail
        model = SequenceModel(
            [("loan_policy", {}), ("assets_search", {}), ("tickets_list_mine", {})],
            [
                ("prepare_preview", {"asset_id": "loan-laptop-1"}),
                ("knowledge_answer", {"question": "解释规则"}),
                ("finish", {}),
            ],
        )
        w.models.chat = model.chat
        result = c.portal.call(
            w.service.message, task["task_id"], "预览与解释", "partial", task["facts_revision"]
        )
        assert result["preview"] and result["status"] == "BLOCKED"
        assert (
            "尚未完成" in result["assistant_text"]
            and "EVIDENCE_INSUFFICIENT" in result["assistant_text"]
        )
        assert not w.service.store.list_tickets(local_actor())
