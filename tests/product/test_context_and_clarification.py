import asyncio
import json
from datetime import timedelta

from app.agent_runtime.workbench_tools import ToolCatalog
from app.runtime.context_window import recent_questions, retrieval_windows
from app.workbench_service import local_actor
from tests.product.test_turn_recovery import product


def test_a_pending_user_message_is_consumed_before_missing_field_clarification(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True}
        )
        tool = ToolCatalog(w.service, task, {"id": "input", "text": "本回合包含所有所需日期及用途"})
        names = {s["function"]["name"] for s in tool.schemas(task)}
        assert "ask_user" not in names and "update_parameters" in names
        day = w.service.store.today() + timedelta(days=2)
        args = {
            "loan_start": str(day),
            "loan_end": str(day + timedelta(days=1)),
            "purpose": "正常用户输入",
        }
        result = asyncio.run(
            tool.call("update_parameters", {"changes": args}, task, "program-only-run")
        )
        w.service.store.observe(
            local_actor(), task["task_id"], "update_parameters", {"status": "ok", "data": result}
        )
        current = w.service.view(task["task_id"])
        revision = current["facts_revision"]
        tool.schemas(current)
        fields, question = tool.clarification(
            {"reason": "ambiguous", "fields": ["loan_end"], "question": "结束日是周五还是周一？"},
            current,
        )
        assert fields == ["loan_end"] and "周一" in question
        asyncio.run(tool.call("update_parameters", {"changes": {}}, current, "program-only-run"))
        assert w.service.view(task["task_id"])["facts_revision"] == revision


def test_long_prior_question_is_kept_whole_and_never_becomes_a_new_obligation():
    previous = "用户提供的条件与背景。" * 55
    rows = [{"id": "old", "question": previous}]
    selected = recent_questions(rows, "如果维修还没登记呢？")
    assert selected == rows and len(previous) > 500
    windows = retrieval_windows(previous + "\n如果维修还没登记呢？")
    assert all(len(x) <= 1000 for x in windows)
    assert "如果维修还没登记呢？" in windows[-1]


def test_editable_preview_remains_active_but_cancelled_task_does_not(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True}
        )
        changed = {**task, "status": "COMPLETED"}
        assert w.service.is_active(changed)
        assert not w.service.is_active({**changed, "status": "CANCELLED"})


def test_model_prose_does_not_execute_or_finish_a_business_turn(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True}
        )
        messages = []

        async def prose_only(request, **kwargs):
            messages.append(request)
            return {"role": "assistant", "content": "I will prepare it now."}

        w.models.chat = prose_only

        async def scenario():
            run = w.runs.start(
                "conversation",
                {
                    "conversation_id": task["conversation_id"],
                    "text": "请准备预览",
                    "message_id": "not-a-finish",
                },
            )
            await w.runs.tasks[run["id"]]
            assert w.runs.get(run["id"])["status"] == "failed"
            assert "MODEL_ACTION_REQUIRED" in w.runs.get(run["id"])["error"]

        asyncio.run(scenario())
        assert len(messages) == 2
        assert json.loads(messages[1][-1]["content"])["code"] == "MODEL_ACTION_REQUIRED"
        current = w.service.view(task["task_id"])
        assert not current.get("preview") and not current.get("receipt")
        assert w.conversations.turns(task["conversation_id"])[0]["status"] == "FAILED"
