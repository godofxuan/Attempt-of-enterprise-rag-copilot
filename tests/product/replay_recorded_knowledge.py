"""Offline HTTP-boundary replay of one original quality failure, no real sends."""

import argparse
import copy
from functools import partial
import json
from pathlib import Path
import sqlite3

import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.workbench_app import create_workbench_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    case = next(
        c
        for c in json.loads(args.quality.read_text("utf8"))["cases"]
        if c["name"] == "long_first_question"
    )
    question = case["question"]
    embedding = {}
    replies = []
    with sqlite3.connect(".private/esa-vnext/app.sqlite3") as db:
        for kind, raw, out in db.execute(
            "SELECT kind,input_json,output_json FROM model_calls WHERE status='OK' ORDER BY rowid"
        ):
            request = json.loads(raw)
            response = json.loads(out)
            if kind == "embed":
                embedding[tuple(request["input"])] = response
            if (
                kind == "chat"
                and "format" in request
                and any(question in m["content"] for m in request["messages"])
            ):
                replies.append(response)
    assert replies, "Original raw generation missing"
    counts = {"chat": 0, "embed": 0}

    async def recorded(kind, payload, **kwargs):
        counts[kind] += 1
        if kind == "chat":
            return copy.deepcopy(replies[0])
        if kind == "embed":
            return copy.deepcopy(embedding[tuple(payload["input"])])
        raise AssertionError("No new request kind allowed in replay")

    def metadata(request):
        assert request.method == "GET" and request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "bge-m3:latest",
                        "digest": "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab",
                    }
                ]
            },
        )

    root = args.workspace.resolve()
    app = create_workbench_app(
        Settings(workbench_enabled=True, data_dir=root, sqlite_path=root / "app.sqlite3"),
        model_transport=httpx.MockTransport(metadata),
    )
    with TestClient(app) as client:
        w = app.state.workspace
        w.models.send = recorded
        result = client.portal.call(partial(w.library.answer, "kb_18fb91057a234ace", question))
    answer = result["result"]
    target = args.quality.parent / ("LONG_PACKET_" + args.label + ".json")
    assert not target.exists()
    target.write_text(
        json.dumps(
            {
                "kind": "OFFLINE_RECORDED_ORIGINAL_REPLY_AND_EMBEDDING_REPLAY",
                "real_model_sends": 0,
                "recorded_adapter_calls": counts,
                "original_quality": str(args.quality),
                "output": result,
                "necessary_facts_retained": all(
                    s in answer["answer"] for s in ("维修", "14", "早于")
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf8",
    )
    print(
        json.dumps(
            {
                "target": str(target),
                "mode": answer["mode"],
                "answer": answer["answer"],
                "packet": answer["trace"].get("publication_packet_coverage"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
