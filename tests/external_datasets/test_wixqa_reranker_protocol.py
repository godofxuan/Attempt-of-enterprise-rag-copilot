from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "docs" / "wixqa_reranker" / "protocol_v1.json"


def test_wixqa_reranker_protocol_freezes_model_and_candidate_budget() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["schema_version"] == "wixqa_article_reranker_protocol_v1"
    assert protocol["candidate_k_chunks"] == 200
    assert protocol["final_top_k_articles"] == 5
    assert protocol["reranker"] == {
        "batch_size": 16,
        "device": "cpu",
        "model": "cross-encoder/ms-marco-MiniLM-L6-v2",
        "model_weights_sha256": (
            "821d1aa69520101d6e0737f78a042ae25b19e5cb9160701909d10434f4aeb0ae"
        ),
        "revision": "c5ee24cb16019beea0893ab7796b1df96625c6b8",
    }


def test_wixqa_reranker_protocol_forbids_fresh_holdout_and_runtime_claims() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["evaluation_boundary"] == {
        "answer_accuracy": "NOT_RUN",
        "expertwritten": "RETROSPECTIVE_FIXED_CONSUMED",
        "runtime_promotion": "FORBIDDEN_BY_THIS_PROTOCOL",
        "simulated": "CONFIGURATION_SELECTION",
    }
    assert protocol["admission_gate"] == {
        "max_p95_latency_multiplier": 5.0,
        "min_ndcg_at_5_delta": 0.02,
        "min_recall_at_5_delta": 0.0,
    }
