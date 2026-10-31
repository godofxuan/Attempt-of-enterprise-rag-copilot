"""Program adapters only; current library, index, runner and publisher stay real."""

import json
import asyncio
from functools import partial

from tests.product.test_turn_recovery import product


def test_prior_questions_reach_generation_without_becoming_clarification_replies(
    tmp_path, monkeypatch
):
    from app.indexing.store import activate_version
    from app.agent.tools_v2 import V2ToolRegistry

    with product(tmp_path) as client:
        w = client.app.state.workspace
        kb = w.library.create("Followup")["id"]
        client.portal.call(
            w.library.upload,
            kb,
            "policy.md",
            b"# Device\n\nOnly employees with a current repair record may borrow a computer.\n",
        )
        built, _, _ = w.library._build("followup-index", kb, lambda _: [1.0, 0.0], "1" * 64)
        activate_version(tmp_path / "indexes" / kb, built.run_id)
        old = "The employee asks about borrowing a laptop with repair conditions. " * 14
        assert 500 < len(old) < 1100
        with w.library.db() as db:
            db.execute("INSERT INTO conversations(id,kb_id) VALUES('history',?)", (kb,))
            db.execute(
                "INSERT INTO knowledge_answers(id,conversation_id,kb_id,question,result_json,generation) VALUES('previous','history',?,?,?,?)",
                (kb, old, '{"answer":"OLD_ANSWER_NOT_EVIDENCE"}', built.run_id),
            )
        packets = []
        timeouts = []
        original = V2ToolRegistry.run

        def inspect_registry(self, action, state):
            if action.tool == "search":
                timeouts.append(action.search_request.timeout_ms)
            return original(self, action, state)

        monkeypatch.setattr(V2ToolRegistry, "run", inspect_registry)

        async def embed(texts, **kwargs):
            return [[1.0, 0.0] for _ in texts]

        async def generate(messages, **kwargs):
            packets.append(messages)
            schema = kwargs["response_format"]["properties"]
            return {
                "content": json.dumps(
                    {
                        "answer_blocks": [
                            {
                                "text": "Only employees with a current repair record may borrow a computer.",
                                "source_unit_ids": schema["answer_blocks"]["items"]["properties"][
                                    "source_unit_ids"
                                ]["items"]["enum"],
                                "need_refs": ["N1"],
                                "assumptions": [],
                            }
                        ],
                        "need_status": {
                            "N1": {
                                "status": "supported",
                                "subject_matches": True,
                                "attribute_matches": True,
                                "conditions_preserved": True,
                                "selection_scope": "linked_units",
                            }
                        },
                    }
                )
            }

        w.models.embed = embed
        w.models.chat = generate
        result = client.portal.call(
            partial(
                w.library.answer, kb, "What is the repair condition?", conversation_id="history"
            )
        )
        assert result["result"]["mode"] == "answered", result["result"]["trace"]
        assert "current repair record" in result["result"]["answer"] and result["result"]["sources"]
        prompt = packets[0][1]["content"]
        assert old in prompt and "OLD_ANSWER_NOT_EVIDENCE" not in prompt
        assert "clarification_replies_untrusted" not in prompt
        assert timeouts == [int(w.config.request_timeout_seconds * 1000)]


def test_real_retrieval_failure_keeps_trace_and_retryable_turn(tmp_path):
    from app.indexing.store import activate_version

    with product(tmp_path) as client:
        w = client.app.state.workspace
        kb = w.library.create("Unavailable model")["id"]
        client.portal.call(
            w.library.upload,
            kb,
            "rule.md",
            b"# Devices\n\nBorrowing requires a current repair record.\n",
        )
        built, _, _ = w.library._build("failed-search-index", kb, lambda _: [1.0, 0.0], "1" * 64)
        activate_version(tmp_path / "indexes" / kb, built.run_id)

        async def offline(*args, **kwargs):
            raise ConnectionError("PROGRAM_MODEL_OFFLINE")

        w.models.embed = offline
        cid = w.conversations.create(kb)["id"]

        async def scenario():
            r = w.runs.start(
                "conversation",
                {"conversation_id": cid, "message_id": "offline-search", "text": "Who may borrow?"},
            )
            await w.runs.tasks[r["id"]]
            current = w.runs.get(r["id"])
            assert current["status"] == "failed" and "KNOWLEDGE_SYSTEM" in current["error"]

        client.portal.call(scenario)
        turns = w.conversations.turns(cid)
        assert turns[0]["status"] == "FAILED" and not any(t["status"] == "PENDING" for t in turns)
        failed = w.library.answers()[0]
        assert (
            failed["result"]["mode"] == "system"
            and failed["result"]["trace"]["steps"][0]["status"] == "error"
        )
