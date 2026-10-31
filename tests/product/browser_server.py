"""Isolated UI test server. Production factory/SQLite, controlled external answer only.

The /__test endpoints exist only in this test module, never in an ESA release.
"""

import argparse
import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import httpx
import uvicorn
from app.config import Settings
from app.workspace import initialize
from app.workbench_app import create_workbench_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="esa-browser-test-") as directory:
        root = Path(directory)
        initialize(root, sample=True)

        def external(request):
            if request.method == "GET" and request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": []})
            raise AssertionError("UI regression cannot send real model requests")

        app = create_workbench_app(
            Settings(workbench_enabled=True, data_dir=root, sqlite_path=root / "app.sqlite3"),
            model_transport=httpx.MockTransport(external),
        )
        original = app.router.lifespan_context
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app):
            async with original(app):
                w = app.state.workspace
                counters = {"agent_decisions": 0, "explanation_attempts": 0}
                plans = {}
                from fastapi import Request

                @app.post("/__test/decisions/{task_id}")
                async def decisions(task_id: str, request: Request):
                    plans[task_id] = await request.json()
                    return {"external_model_double": True}

                @app.get("/__test/counters")
                def test_counters():
                    return counters

                async def model(messages, **kwargs):
                    from app.runtime.request_context import current_request_id

                    target = w.runs.get(current_request_id())["target"]
                    if target in plans:
                        if not plans[target]:
                            raise AssertionError("Explicit external decision fixture exhausted")
                        return {
                            "content": "EXPLICIT_EXTERNAL_MODEL_DOUBLE",
                            "tool_calls": [
                                {"function": {"name": name, "arguments": arguments}}
                                for name, arguments in plans[target].pop(0)
                            ],
                        }
                    counters["agent_decisions"] += 1
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "prepare_preview",
                                    "arguments": {
                                        "asset_id": "loan-laptop-1",
                                        "turn_request": {
                                            "preview": True,
                                            "knowledge_quote": "解释押金制度",
                                        },
                                    },
                                }
                            },
                            {
                                "function": {
                                    "name": "knowledge_answer",
                                    "arguments": {"question": "解释押金制度"},
                                }
                            },
                        ],
                    }

                w.models.chat = model

                async def answer(kb, question, **options):
                    w.library.require(kb)
                    if question == "解释押金制度":
                        from app.service_desk.store import ServiceError

                        counters["explanation_attempts"] += 1
                        if counters["explanation_attempts"] == 1:
                            raise ServiceError("EVIDENCE_INSUFFICIENT")
                    # Controlled latency for ownership/cancel tests, not a model decision.
                    if question.startswith("UI等待"):
                        await asyncio.Event().wait()
                    return {
                        "id": "ui-double",
                        "kb_id": kb,
                        "question": question,
                        "result": {
                            "mode": "partial",
                            "answer": "UI外部回答替身，非实时模型。",
                            "sources": [],
                            "claims": [],
                            "citations": [],
                        },
                    }

                w.library.answer = answer
                with w.conversations.db() as db:
                    db.execute(
                        "INSERT OR REPLACE INTO workspace_meta VALUES('onboarding_completed','1')"
                    )
                yield

        app.router.lifespan_context = lifespan
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
