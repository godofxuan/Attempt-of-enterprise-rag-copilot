"""Finite real local-model quality checks through the running product API.

Expected facts come from the existing unmodified synthetic rule documents.
These are explicit content checks, not an independent semantic human review.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8740")
    parser.add_argument("--kb", default="kb_18fb91057a234ace")
    args = parser.parse_args()
    folder = Path(".private/esa-vnext/upgrade-050-060")
    target = folder / (
        "QUALITY_060_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    record = {
        "kind": "REAL_LOCAL_MODEL_API_RULE_DOCUMENTS",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "expected_basis": "unmodified rule-backed loan/repair/room documents; no oracle injected into runtime",
        "cases": [],
    }
    with httpx.Client(
        base_url=args.url, trust_env=False, timeout=20, headers={"X-ESA-Request": "1"}
    ) as client:

        def save():
            target.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf8")

        def post(path, data):
            response = client.post(path, json=data)
            response.raise_for_status()
            return response.json()

        def wait(run):
            deadline = time.monotonic() + 260
            while time.monotonic() < deadline:
                current = client.get("/api/runs/" + run["id"]).json()
                if current["status"] not in {"queued", "running"}:
                    return current
                time.sleep(0.5)
            raise TimeoutError("Bounded product run did not finish")

        def knowledge(
            name, question, *, entry="RAG", deep=False, cid=None, required=(), insufficient=False
        ):
            row = {
                "name": name,
                "question": question,
                "entry": entry,
                "deep": deep,
                "required_content": list(required),
                "expect_insufficient": insufficient,
            }
            record["cases"].append(row)
            save()
            started = time.monotonic()
            try:
                if entry == "RAG":
                    run = wait(
                        post(
                            "/api/knowledge/runs",
                            {
                                "kb_id": args.kb,
                                "question": question,
                                "detailed": deep,
                                "conversation_id": cid,
                            },
                        )
                    )
                else:
                    task = post(
                        "/api/tasks",
                        {
                            "request": {
                                "kind": "knowledge",
                                "question": question,
                                "execution_ceiling": "READ_ONLY",
                                "confirmed": True,
                            },
                            "kb_id": args.kb,
                        },
                    )
                    row["task_id"] = task["task_id"]
                    run = wait(post("/api/tasks/" + task["task_id"] + "/runs", {}))
                row["run"] = run
                assert run["status"] == "succeeded", run.get("error")
                value = run["result"]
                answer = value.get("knowledge_result", value)["result"]
                body = answer["answer"]
                row["content_checks"] = {text: text in body for text in required}
                assert all(row["content_checks"].values()), body
                if insufficient:
                    assert answer["mode"] != "answered", body
                    assert "没有规定押金" not in body and "跨国运费为" not in body, body
                else:
                    assert answer["mode"] == "answered" and answer["sources"], body
                row["status"] = "PASS"
                return value.get("knowledge_result", value).get("conversation_id")
            except Exception as exc:
                row["status"] = "FAIL"
                row["failure"] = str(exc)
            finally:
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                save()

        record["before"] = client.get("/api/status").json()
        record["instance"] = client.get("/api/instance").json()
        save()
        loan = "临时电脑借用的资格、期限和开始日期限制是什么？"
        knowledge("loan_direct", loan, required=("维修", "14", "早于"))
        knowledge("loan_delegated", loan, entry="AGENT", required=("维修", "14", "早于"))
        room = "会议室一次可以预订多久，开放时间和使用结束的要求是什么？"
        knowledge("room_direct", room, required=("2小时", "09:00", "18:00", "清理", "关闭"))
        knowledge(
            "room_delegated",
            room,
            entry="AGENT",
            required=("2小时", "09:00", "18:00", "清理", "关闭"),
        )
        knowledge(
            "deep_two_documents",
            "请深入比较临时电脑借用和会议室预订的时长上限，并分别保留适用条件。",
            deep=True,
            required=("14", "维修", "2小时", "09:00", "18:00"),
        )
        knowledge(
            "genuine_missing_attribute",
            "这些资料是否规定了跨国运送临时电脑的运费金额和支付责任？",
            insufficient=True,
        )
        long_question = ("我正在整理本地服务说明，需要了解规则依据，暂不进行任何提交。" * 20) + loan
        cid = knowledge("long_first_question", long_question, required=("维修", "14", "早于"))
        if cid:
            knowledge(
                "long_context_followup",
                "如果维修还没登记，是否已符合申请资格？",
                cid=cid,
                required=("维修",),
            )
        row = {
            "name": "readonly_actual_observation_delivery",
            "entry": "AGENT",
            "question": "查询我当前的维修资格、可用电脑和借用申请，不要新建。",
        }
        record["cases"].append(row)
        save()
        try:
            before = client.get("/api/service-desk").json()
            task = post(
                "/api/tasks",
                {
                    "request": {
                        "kind": "loan",
                        "execution_ceiling": "READ_ONLY",
                        "confirmed": True,
                    },
                    "kb_id": args.kb,
                },
            )
            run = wait(
                post(
                    "/api/conversations/" + task["conversation_id"] + "/turns",
                    {"text": row["question"], "message_id": uuid.uuid4().hex},
                )
            )
            row["run"] = run
            assert run["status"] == "succeeded", run.get("error")
            current = client.get("/api/tasks/" + task["task_id"]).json()
            row["task"] = current
            assert not current["preview"] and not current["receipt"]
            assert (
                current["outcome"]["goal_satisfied"]
                and "eligible" in current["assistant_text"]
                and "available laptops" in current["assistant_text"]
            )
            assert client.get("/api/service-desk").json()["tickets"] == before["tickets"]
            row["status"] = "PASS"
        except Exception as exc:
            row["status"] = "FAIL"
            row["failure"] = str(exc)
        record["after"] = client.get("/api/status").json()
        record["passed"] = all(row["status"] == "PASS" for row in record["cases"])
        save()
        print(
            json.dumps(
                {
                    "path": str(target),
                    "results": [(r["name"], r["status"]) for r in record["cases"]],
                    "chat_delta": record["after"]["generation_calls"]
                    - record["before"]["generation_calls"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
