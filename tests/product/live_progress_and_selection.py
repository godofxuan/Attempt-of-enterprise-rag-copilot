"""Finite real local-model acceptance of progress delivery and user selection.

Explicit TEST form facts and a TEST user's selection; no injected model actions.
Earlier failed attempts remain separate evidence.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
import httpx

folder = Path(".private/esa-vnext/upgrade-050-060")
target = folder / (
    "LIVE_PROGRESS_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
)
record = {"kind": "REAL_MODEL_TWO_TURN_PROGRESS_SELECTION_AND_LONG_HISTORY", "cases": []}
with httpx.Client(
    base_url="http://127.0.0.1:8740", trust_env=False, timeout=10, headers={"X-ESA-Request": "1"}
) as client:

    def save():
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf8")

    def get(path):
        r = client.get(path)
        r.raise_for_status()
        return r.json()

    def post(path, data):
        r = client.post(path, json=data)
        r.raise_for_status()
        return r.json()

    def wait(r):
        deadline = time.monotonic() + 250
        while time.monotonic() < deadline:
            current = get("/api/runs/" + r["id"])
            if current["status"] not in ("queued", "running"):
                return current
            time.sleep(0.5)
        raise TimeoutError("Finite task deadline expired")

    record["before"] = get("/api/status")
    assert record["before"]["mode"] == "SYNTHETIC_LOCAL"
    record["instance"] = get("/api/instance")
    record["before_tickets"] = get("/api/service-desk")["tickets"]
    save()
    facts = {
        "loan_start": "2026-12-01",
        "loan_end": "2026-12-03",
        "purpose": "混合交互TEST",
        "min_memory_gb": 16,
    }
    task = post(
        "/api/tasks",
        {
            "request": {
                "kind": "loan",
                "execution_ceiling": "PREVIEW_ONLY",
                "facts": facts,
                "confirmed": True,
            },
            "kb_id": "kb_18fb91057a234ace",
        },
    )
    record["task_id"] = task["task_id"]
    record["explicit_test_user_form"] = facts
    save()
    try:
        row = {
            "name": "mixed_change_and_policy_progress",
            "question": "把结束日期改为2026年12月4日，其余保持；顺便说明制度有没有规定押金，并给我当前完整预览。绝不提交。",
        }
        record["cases"].append(row)
        save()
        row["run"] = wait(
            post(
                "/api/conversations/" + task["conversation_id"] + "/turns",
                {"text": row["question"], "message_id": uuid.uuid4().hex},
            )
        )
        assert row["run"]["status"] == "succeeded", row["run"].get("error")
        current = get("/api/tasks/" + task["task_id"])
        row["task"] = current
        assert current["facts"] == {**facts, "loan_end": "2026-12-04"} and not current["receipt"]
        answer = current["knowledge_result"]["result"]
        assert (
            answer["mode"] == "answered"
            and "没有规定押金" in answer["answer"]
            and answer["sources"]
        )
        if not current["preview"]:
            assert (
                current["status"] != "COMPLETED" and "尚未生成完整预览" in current["assistant_text"]
            )
        row["status"] = "PREVIEW_READY" if current["preview"] else "PROGRESS_NOT_TASK_COMPLETE"
        save()
        options = get("/api/product/tasks/" + task["task_id"] + "/alternatives")
        assert len(options) >= 2
        record["displayed_choices"] = options
        row = {
            "name": "user_selects_second_and_real_preview",
            "question": "请选择刚才列表中的第二台，其他条件保持不变，为我生成完整预览。仍然不提交。",
            "expected_asset": options[1]["asset_id"],
        }
        record["cases"].append(row)
        save()
        row["run"] = wait(
            post(
                "/api/conversations/" + task["conversation_id"] + "/turns",
                {"text": row["question"], "message_id": uuid.uuid4().hex},
            )
        )
        assert row["run"]["status"] == "succeeded", row["run"].get("error")
        final = get("/api/tasks/" + task["task_id"])
        row["task"] = final
        assert final["preview"] and final["preview"]["content"]["target"] == options[1]["asset_id"]
        assert final["facts"] == {**facts, "loan_end": "2026-12-04"} and not final["receipt"]
        assert final["user_execution_ceiling"] == "PREVIEW_ONLY"
        rejected = client.post(
            "/api/tasks/" + task["task_id"] + "/submit",
            json={
                "proposal_id": final["preview"]["proposal_id"],
                "content_digest": final["preview"]["content_digest"],
                "expected_facts_revision": final["facts_revision"],
                "accepted": True,
            },
        )
        row["forbidden_submission"] = {"status": rejected.status_code, "body": rejected.json()}
        assert (
            rejected.status_code in (400, 403, 409)
            and get("/api/service-desk")["tickets"] == record["before_tickets"]
        )
        row["status"] = "PASS"
        record["mixed_group"] = "PASS_AFTER_ACTUAL_USER_SELECTION"
        save()
    except Exception as exc:
        record["cases"][-1].update(status="FAIL", failure=str(exc))
        save()
    finally:
        record["explicit_test_user_cancel"] = post("/api/tasks/" + task["task_id"] + "/cancel", {})
        save()
    row = {
        "name": "normal_followup_after_preserved_long_history",
        "question": "那借用最久多久，开始日期有什么限制？",
        "negative_case_retained": "MIXED_FOLLOWUP_20261030T171625Z/followup_after_preserved_long_failed_turn remains FAIL",
    }
    record["cases"].append(row)
    save()
    try:
        row["run"] = wait(
            post(
                "/api/conversations/conversation_08245f5a5e1f4363/turns",
                {"text": row["question"], "message_id": uuid.uuid4().hex},
            )
        )
        assert row["run"]["status"] == "succeeded", row["run"].get("error")
        answer = row["run"]["result"]["result"]
        assert (
            answer["mode"] == "answered"
            and answer["sources"]
            and "14" in answer["answer"]
            and "早于" in answer["answer"]
        )
        row["status"] = "PASS"
    except Exception as exc:
        row.update(status="FAIL", failure=str(exc))
    record["after"] = get("/api/status")
    record["passed"] = (
        record.get("mixed_group") == "PASS_AFTER_ACTUAL_USER_SELECTION" and row["status"] == "PASS"
    )
    save()
    print(
        json.dumps(
            {
                "path": str(target),
                "results": [(r["name"], r["status"]) for r in record["cases"]],
                "passed": record["passed"],
                "chat_delta": record["after"]["generation_calls"]
                - record["before"]["generation_calls"],
            },
            ensure_ascii=False,
        )
    )
