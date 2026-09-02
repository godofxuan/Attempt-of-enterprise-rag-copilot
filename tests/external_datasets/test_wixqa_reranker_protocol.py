from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "docs" / "wixqa_reranker" / "protocol_v1.json"
BGE_V2_PROTOCOL = ROOT / "docs" / "wixqa_reranker" / "bge_v2_protocol.json"


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


def test_wixqa_bge_v2_protocol_freezes_gpu_model_and_same_selection_arms() -> None:
    protocol = json.loads(BGE_V2_PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["schema_version"] == "wixqa_bge_reranker_protocol_v2"
    assert protocol["pre_freeze_quality_smoke_case_count"] == 2
    assert protocol["reranker"] == {
        "batch_size": 4,
        "device": "cuda",
        "model": "BAAI/bge-reranker-v2-m3",
        "model_weights_sha256": (
            "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286"
        ),
        "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
        "torch_build": "2.7.0+cu128",
    }
    assert protocol["selection_arms"] == [
        {"dense_head_count": 0, "reranker_top_n": 10},
        {"dense_head_count": 1, "reranker_top_n": 10},
        {"dense_head_count": 1, "reranker_top_n": 20},
    ]


def test_wixqa_bge_v2_protocol_preserves_claim_and_latency_boundaries() -> None:
    protocol = json.loads(BGE_V2_PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["evaluation_boundary"] == {
        "answer_accuracy": "NOT_RUN",
        "expertwritten": "RUN_ONLY_AFTER_GATE_RETROSPECTIVE_FIXED_CONSUMED",
        "runtime_promotion": "FORBIDDEN_BY_THIS_PROTOCOL",
        "simulated": "CONFIGURATION_SELECTION",
    }
    assert protocol["admission_gate"] == {
        "max_p95_latency_multiplier": 5.0,
        "min_ndcg_at_5_delta": 0.02,
        "min_recall_at_5_delta": 0.0,
    }
