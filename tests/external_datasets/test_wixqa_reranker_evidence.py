from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "wixqa_reranker" / "evidence_v1.json"


def test_wixqa_reranker_evidence_rejects_every_registered_arm() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["decision"] == "VALIDATION_REJECTED_EXPERTWRITTEN_FORBIDDEN"
    assert evidence["expertwritten_status"] == "NOT_RUN_GATE_FORBIDS"
    assert len(evidence["runs"]) == 3
    for run in evidence["runs"]:
        assert run["recall_at_5_delta"] < 0
        assert run["ndcg_at_5_delta"] < 0
        assert run["latency_p95_multiplier"] > 5.0
        assert not any(run["gate_checks"].values())


def test_wixqa_reranker_evidence_preserves_claim_boundary() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    boundary = " ".join(evidence["claim_boundary"]).lower()
    assert "not a blind holdout" in boundary
    assert "answer and citation quality were not evaluated" in boundary
    assert evidence["code_revision"] == "00ed4bbf346aa5d2d8f14ffe08cb6fed41140398"


def test_wixqa_candidate_ceiling_and_stronger_smoke_are_not_promotions() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    ceiling = evidence["candidate_ceiling"]
    assert ceiling["recall_at_10"] > ceiling["recall_at_5"]
    assert ceiling["recall_at_20"] > ceiling["recall_at_10"]
    smoke = evidence["exploratory_stronger_model_smoke"]
    assert smoke["case_count"] == 2
    assert smoke["cuda_attempt"] == "BLOCKED_TORCH_CPU_ONLY"
    assert smoke["decision"] == "FULL_RUN_NOT_JUSTIFIED_BY_COST"
