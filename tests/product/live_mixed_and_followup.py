"""Final finite interaction checks; real model choices, explicit TEST-only scope."""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
import httpx

folder = Path(".private/esa-vnext/upgrade-050-060")
target = folder / (
    "MIXED_FOLLOWUP_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
)
record = {"kind": "REAL_LOCAL_MODEL_API_TEST_USER_AND_CURRENT_OBSERVATIONS", "cases": []}
with httpx.Client(
    base_url="http://127.0.0.1:8740", trust_env=False, timeout=20, headers={"X-ESA-Request": "1"}
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

    def wait(run):
        deadline = time.monotonic() + 260
        while time.monotonic() < deadline:
            current = get("/api/runs/" + run["id"])
            if current["status"] not in {"queued", "running"}:
                return current
            time.sleep(0.5)
        raise TimeoutError("Bounded run did not finish")

    record["before"] = get("/api/status")
    assert record["before"]["mode"] == "SYNTHETIC_LOCAL"
    record["instance"] = get("/api/instance")
    save()
    prior = json.loads((folder / "QUALITY_060_20261030T144939Z.json").read_text("utf8"))
    cid = prior["cases"][0]["run"]["result"]["conversation_id"]
    row = {
        "name": "followup_after_preserved_long_failed_turn",
        "original_evidence": str(folder / "QUALITY_060_20261030T144939Z.json"),
        "question": "如果维修还没登记，是否已符合申请资格？",
    }
    record["cases"].append(row)
    try:
        run = wait(
            post(
                "/api/conversations/" + cid + "/turns",
                {"text": row["question"], "message_id": uuid.uuid4().hex},
            )
        )
        row["run"] = run
        assert run["status"] == "succeeded", run.get("error")
        answer = run["result"]["result"]
        assert "维修" in answer["answer"] and answer["sources"] and answer["mode"] == "answered", (
            answer["answer"]
        )
        row["status"] = "PASS"
    except Exception as exc:
        row["status"] = "FAIL"
        row["failure"] = str(exc)
    save()
    # Initial values below are explicit TEST user form input, not claimed model extraction.
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
    row = {
        "name": "natural_date_change_plus_shared_knowledge",
        "task_id": task["task_id"],
        "explicit_user_form": facts,
        "question": "把结束日期改为2026年12月4日，其余保持；顺便说明制度有没有规定押金，并给我当前完整预览。绝不提交。",
    }
    record["cases"].append(row)
    save()
    before = get("/api/service-desk")
    try:
        run = wait(
            post(
                "/api/conversations/" + task["conversation_id"] + "/turns",
                {"text": row["question"], "message_id": uuid.uuid4().hex},
            )
        )
        row["run"] = run
        assert run["status"] == "succeeded", run.get("error")
        current = get("/api/tasks/" + task["task_id"])
        row["task"] = current
        assert (
            current["facts"]["loan_end"] == "2026-12-04"
            and current["facts"]["loan_start"] == facts["loan_start"]
            and current["facts"]["purpose"] == facts["purpose"]
        )
        assert (
            current["preview"]
            and not current["receipt"]
            and current["user_execution_ceiling"] == "PREVIEW_ONLY"
        )
        answer = current.get("knowledge_result", {}).get("result", {})
        assert (
            answer.get("mode") == "answered"
            and answer.get("sources")
            and "没有规定押金" in answer.get("answer", "")
        ), answer.get("answer")
        assert get("/api/service-desk")["tickets"] == before["tickets"]
        row["status"] = "PASS"
        save()
        choices = get("/api/product/tasks/" + task["task_id"] + "/alternatives")
        row["displayed_choices"] = choices
        assert len(choices) >= 2
        next_row = {
            "name": "second_current_resource_by_natural_reference",
            "task_id": task["task_id"],
            "question": "改选刚才列表里的第二台，其余不变，请给我新的完整预览，仍然绝不提交。",
            "expected_actual_asset": choices[1]["asset_id"],
        }
        record["cases"].append(next_row)
        save()
        follow = wait(
            post(
                "/api/conversations/" + task["conversation_id"] + "/turns",
                {"text": next_row["question"], "message_id": uuid.uuid4().hex},
            )
        )
        next_row["run"] = follow
        assert follow["status"] == "succeeded", follow.get("error")
        final = get("/api/tasks/" + task["task_id"])
        next_row["task"] = final
        assert (
            final["preferred_asset_id"] == choices[1]["asset_id"]
            and final["preview"]["content"]["target"] == choices[1]["asset_id"]
        )
        assert final["facts"]["loan_end"] == "2026-12-04" and not final["receipt"]
        assert get("/api/service-desk")["tickets"] == before["tickets"]
        next_row["status"] = "PASS"
        row["status"] = "PASS"
    except Exception as exc:
        failed = record["cases"][-1]
        failed.update(status="FAIL", failure=str(exc))
    finally:
        # An explicit TEST user ends this no-submission draft; no SQL cleanup.
        record["ended_draft"] = post("/api/tasks/" + task["task_id"] + "/cancel", {})
        record["after"] = get("/api/status")
        record["passed"] = all(r.get("status") == "PASS" for r in record["cases"])
        save()
        print(
            json.dumps(
                {
                    "path": str(target),
                    "results": [(r["name"], r.get("status")) for r in record["cases"]],
                    "chat_delta": record["after"]["generation_calls"]
                    - record["before"]["generation_calls"],
                },
                ensure_ascii=False,
            )
        )
