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
