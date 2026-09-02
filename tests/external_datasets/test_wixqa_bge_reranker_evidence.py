from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "wixqa_reranker" / "bge_v2_evidence.json"


def test_wixqa_bge_evidence_records_quality_and_latency_gate_pass() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "wixqa_bge_reranker_public_evidence_v1"
    assert evidence["decision"] == "VALIDATION_GATE_PASSED_RETROSPECTIVE_POSITIVE_UNCERTAIN"
    assert all(evidence["validation"]["gate_checks"].values())
    validation = evidence["validation"]
    assert validation["metrics"]["recall_at_5"]["delta"] > 0.03
    assert validation["metrics"]["ndcg_at_5"]["delta"] > 0.02
    assert validation["latency_ms"]["p95_multiplier"] < 5.0


def test_wixqa_bge_evidence_keeps_retrospective_uncertainty_visible() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    expert = evidence["expertwritten"]
    assert expert["consumption"] == "FIXED_CONSUMED_RETROSPECTIVE"
    assert expert["statistical_conclusion"] == "POSITIVE_POINT_ESTIMATES_CI_CROSSES_ZERO"
    for metric in expert["metrics"].values():
        assert metric["delta"] > 0
        assert metric["ci95_low"] < 0 < metric["ci95_high"]
    boundary = " ".join(evidence["claim_boundary"]).lower()
    assert "historically consumed" in boundary
    assert "answer correctness" in boundary
    assert "not the unconditional default" in boundary
