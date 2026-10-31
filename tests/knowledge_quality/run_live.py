"""Finite API semantic run. Saves all original outcomes; never grades by COMPLETED.

Use only an explicitly chosen local TEST workspace and existing published index.
This runner supplies questions, never interpretations, answers or tool order.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid

import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--kb", required=True)
    p.add_argument("--split", choices=["dev", "holdout"], required=True)
    p.add_argument("--commit", required=True, help="Actual frozen application, not the current shell HEAD")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    args = p.parse_args()
    if args.out.exists():
        p.error("Existing raw result is immutable; choose a new output only for a distinct measurement")
    cases = json.loads(args.cases.read_text("utf8"))
    report = {"kind":"REAL_LOCAL_MODEL_API", "application_commit":args.commit,
              "case_sha256":hashlib.sha256(args.cases.read_bytes()).hexdigest(),
              "split":args.split,"started":datetime.now(timezone.utc).isoformat(),"results":[]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf8")
    with httpx.Client(base_url=args.url, timeout=20, trust_env=False, headers={"X-ESA-Request":"1"}) as client:
        report["instance"] = client.get("/api/instance").json()
        status = client.get("/api/status").json()
        if status.get("mode") != "SYNTHETIC_LOCAL":
            raise RuntimeError("This runner requires an explicitly synthetic TEST workspace")
        report["status_before"] = status
        def post(path, value):
            response = client.post(path, json=value)
            response.raise_for_status()
            return response.json()
        def wait(run):
            until = time.monotonic()+250
            while time.monotonic()<until:
                result = client.get("/api/runs/"+run["id"]).json()
                if result["status"] not in {"running","queued"}:
                    return result
                time.sleep(.4)
            client.post("/api/runs/"+run["id"]+"/cancel",json={})
            raise TimeoutError("Run exceeded existing deadline; cancellation requested")
        for case in cases["cases"]:
            if case["split"] != args.split:
                continue
            row = {"case":case,"started":datetime.now(timezone.utc).isoformat(),"score":"PENDING_CONTENT_REVIEW"}
            report["results"].append(row); save()
            try:
                cid = post("/api/conversations",{"kb_id":args.kb,"title":"语义验证 "+case["id"]})["id"]
                if case.get("prior"):
                    row["prior_run"] = wait(post("/api/knowledge/runs",{"kb_id":args.kb,"conversation_id":cid,"question":case["prior"]}))
                question = "我在整理本地服务台说明，希望了解制度而不是实际办理。这些背景不是新的任务。"*case.get("background_repeat",0)+case["question"]
                row["actual_user_question"] = question
                if case["entry"] == "RAG":
                    run = post("/api/knowledge/runs",{"kb_id":args.kb,"conversation_id":cid,"question":question,"detailed":case.get("deep",False)})
                else:
                    task = post("/api/tasks",{"kb_id":args.kb,"conversation_id":cid,"request":{"kind":"knowledge","question":question,"execution_ceiling":"READ_ONLY","confirmed":True}})
                    row["task_id"] = task["task_id"]
                    # A knowledge task is the actual guided Agent entry. Its first
                    # model selects knowledge_answer, no tool choice is injected.
                    run = post("/api/tasks/"+task["task_id"]+"/runs",{}) if not case.get("deep") else post("/api/conversations/"+cid+"/turns",{"text":question,"message_id":uuid.uuid4().hex,"detailed":True})
                started=time.monotonic();row["run"]=wait(run);row["elapsed_seconds"]=round(time.monotonic()-started,3)
                result=row["run"].get("result") or {}
                row["answer_receipt"] = result.get("knowledge_result") if case["entry"]=="Agent" else result
                print(case["id"],row["run"]["status"],round(row["elapsed_seconds"],1),flush=True)
            except Exception as exc:
                row["error"] = type(exc).__name__+": "+str(exc)
                print(case["id"],row["error"],flush=True)
            save()
        report["status_after"] = client.get("/api/status").json()
        report["finished"] = datetime.now(timezone.utc).isoformat(); save()


if __name__ == "__main__":
    main()
