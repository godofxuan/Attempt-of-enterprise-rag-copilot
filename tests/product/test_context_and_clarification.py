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


def test_real_preview_is_terminal_for_a_conversational_turn(tmp_path):
    from tests.vnext.test_conversations import SequenceModel

    with product(tmp_path) as client:
        w = client.app.state.workspace
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "SUBMIT_AFTER_CONFIRMATION", "confirmed": True}
        )
        day = w.service.store.today() + timedelta(days=2)
        facts = {
            "loan_start": str(day),
            "loan_end": str(day + timedelta(days=1)),
            "purpose": "会话准备",
        }
        model = SequenceModel(
            [("update_parameters", {"changes": facts}), ("loan_policy", {})],
            [("assets_search", {}), ("tickets_list_mine", {})],
            [("prepare_preview", {"asset_id": "loan-laptop-1", "parameters": facts})],
        )
        w.models.chat = model.chat
        result = asyncio.run(
            w.service.message(
                task["task_id"], "用户正常办理消息", "terminal-preview", task["facts_revision"]
            )
        )
        assert result["preview"] and not result["receipt"]
        assert result["status"] == "WAITING_CONFIRMATION" and not result["active_run_id"]
        assert len(model.calls) == 3 and not model.batches
        assert not result["pending_update"]


def test_readonly_conversational_delivery_uses_current_domain_observations(tmp_path):
    from tests.vnext.test_conversations import SequenceModel

    with product(tmp_path) as client:
        w = client.app.state.workspace
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "READ_ONLY", "confirmed": True}
        )
        model = SequenceModel(
            [("loan_policy", {}), ("assets_search", {}), ("tickets_list_mine", {})],
            [("finish", {})],
        )
        w.models.chat = model.chat
        result = asyncio.run(
            w.service.message(
                task["task_id"],
                "请查我当前的资格、库存和申请",
                "readonly-delivery",
                task["facts_revision"],
            )
        )
        assert result.get("outcome", {}).get("goal_satisfied") is True
        assert (
            "eligible" in result["assistant_text"]
            and "available laptops: 3" in result["assistant_text"]
        )
        assert "reserve or allocate" in result["assistant_text"]
        assert not result["preview"] and not result["receipt"]


def test_guided_knowledge_accepts_the_same_question_size_without_duplicating_input(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        question = "保持完整的用户背景与条件。" * 52 + "临时电脑的借用期限是多少？"
        assert 600 < len(question) < 2000
        task = w.service.create(
            {
                "kind": "knowledge",
                "execution_ceiling": "READ_ONLY",
                "question": question,
                "confirmed": True,
            },
            kb_id="test-kb",
        )
        packets = []

        async def inspect(messages, **kwargs):
            packets.append(messages)
            assert messages[1]["role"] == "user" and messages[1]["content"] == question
            assert question not in messages[0]["content"]
            raise ConnectionError("Program-only stop after inspecting the complete native input")

        w.models.chat = inspect

        async def run():
            result = w.runs.start("service", {"task_id": task["task_id"]})
            await w.runs.tasks[result["id"]]
            assert w.runs.get(result["id"])["status"] == "failed"
            assert "Program-only stop" in w.runs.get(result["id"])["error"]

        asyncio.run(run())
        assert (
            len(packets) == 1
            and w.service.view(task["task_id"])["user_execution_ceiling"] == "READ_ONLY"
        )
        assert question not in packets[0][0]["content"] and packets[0][1]["content"] == question


def test_displayed_options_and_model_observation_share_the_current_binding(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        day = w.service.store.today() + timedelta(days=3)
        task = w.service.create(
            {
                "kind": "loan",
                "execution_ceiling": "PREVIEW_ONLY",
                "confirmed": True,
                "facts": {
                    "loan_start": str(day),
                    "loan_end": str(day + timedelta(days=1)),
                    "purpose": "候选绑定",
                },
            }
        )
        shown = client.get("/api/product/tasks/" + task["task_id"] + "/alternatives").json()
        assert len(shown) >= 2 and shown[1]["position"] == 2
        tool = ToolCatalog(w.service, task, {"id": "pick-second", "text": "选择刚显示的第二台"})
        observation = asyncio.run(tool.call("assets_search", {}, task, "program-options"))
        assert [o["asset_id"] for o in observation["alternatives"]] == [
            o["asset_id"] for o in shown
        ]
        from app.agent_runtime.workbench_context import ContextBuilder

        context = ContextBuilder(w.service).build(w.service.view(task["task_id"]))
        assert [(o["asset_id"], o["position"]) for o in context["last_presented_options"]] == [
            (o["asset_id"], o["position"]) for o in shown
        ]
        selected = asyncio.run(
            tool.call("select_asset", {"option_id": shown[1]["option_id"]}, task, "program-options")
        )
        assert w.service.view(task["task_id"])["preferred_asset_id"] == shown[1]["asset_id"]
        assert not w.service.view(task["task_id"])["receipt"]


def test_parameter_tool_observations_do_not_embed_the_whole_task_history(tmp_path):
    from tests.vnext.test_conversations import SequenceModel

    with product(tmp_path) as client:
        w = client.app.state.workspace
        task = w.service.create(
            {"kind": "loan", "execution_ceiling": "PREVIEW_ONLY", "confirmed": True}
        )
        for i in range(3):
            model = SequenceModel(
                [("update_parameters", {"changes": {"purpose": "用途" + str(i)}})],
                [("ask_user", {"fields": ["loan_start", "loan_end"]})],
            )
            w.models.chat = model.chat
            task = asyncio.run(
                w.service.message(
                    task["task_id"],
                    "本回合只修改用途",
                    "bounded-history-" + str(i),
                    task["facts_revision"],
                )
            )
        updates = [
            o["result"]["data"] for o in task["observations"] if o["tool"] == "update_parameters"
        ]
        assert len(updates) == 3
        assert all("observations" not in data and "events" not in data for data in updates)
        assert (
            updates[-1]["facts"]["purpose"] == "用途2"
            and task["user_execution_ceiling"] == "PREVIEW_ONLY"
        )


def test_resource_selection_returns_business_data_not_the_task_audit_graph(tmp_path):
    with product(tmp_path) as client:
        w = client.app.state.workspace
        day = w.service.store.today() + timedelta(days=2)
        task = w.service.create(
            {
                "kind": "loan",
                "execution_ceiling": "PREVIEW_ONLY",
                "confirmed": True,
                "facts": {
                    "loan_start": str(day),
                    "loan_end": str(day + timedelta(days=1)),
                    "purpose": "选择设备",
                },
            }
        )
        tool = ToolCatalog(w.service, task, {"id": "resource-input", "text": "选择当前真实设备"})
        result = asyncio.run(
            tool.call("select_asset", {"asset_id": "loan-laptop-2"}, task, "program-selection")
        )
        assert "events" not in result and "observations" not in result
        assert result["selected_asset_id"] == "loan-laptop-2" and result["facts"] == task["facts"]
