from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_wixqa_multidoc_candidate import verify_public_evidence


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "multidoc_candidate" / "evidence"
PROTOCOL = (
    ROOT / "docs" / "multidoc_candidate" / "00_LONG_TERM_PLAN_AND_PROTOCOL.md"
)


def test_checked_in_candidate_evidence_recomputes_and_remains_rejected() -> None:
    result = verify_public_evidence(
        EVIDENCE,
        candidate_protocol_path=PROTOCOL,
        frozen_protocol_path=(
            ROOT
            / "docs"
            / "final_evidence_closure"
            / "evidence"
            / "answer_citation_60_protocol_v1.json"
        ),
        expected_code_revision="d29639c8b3f037560385d5c7ad1b847dae4fc4ab",
    )
    assert result["status"] == "VERIFIED_REJECTED_CANDIDATE"
    assert result["case_count"] == 20
    assert result["decision"] == "DEVELOPMENT_CANDIDATE_REJECTED"


def test_candidate_result_locks_quality_cost_and_claim_boundaries() -> None:
    aggregate = json.loads((EVIDENCE / "aggregate_v1.json").read_bytes())
    current = aggregate["arm_summaries"]["current"]
    combined = aggregate["arm_summaries"]["combined"]
    gate = aggregate["combined_vs_current_gate"]

    assert current["citation_completeness"] == 0.0
    assert combined["citation_completeness"] == 0.0
    assert current["citation_precision"] == pytest.approx(0.45)
    assert combined["citation_precision"] == pytest.approx(0.39166666666666666)
    assert current["citation_recall"] == pytest.approx(0.21666666666666665)
    assert combined["citation_recall"] == pytest.approx(0.24166666666666664)
    assert gate["paired_fix_count"] == 0
    assert gate["p95_latency_ratio"] == pytest.approx(1.8590358323863405)
    assert gate["decision"] == "DEVELOPMENT_CANDIDATE_REJECTED"
    assert aggregate["claim_boundary"] == {
        "answer_correctness": "NOT_MEASURED",
        "consumed_cohort": True,
        "development_only": True,
        "fixed_validation_authorized": False,
        "resume_quality_claim_allowed": False,
        "serving_change_authorized": False,
    }


def test_candidate_verifier_rejects_metric_tampering(tmp_path: Path) -> None:
    target = tmp_path / "evidence"
    target.mkdir()
    for source in EVIDENCE.iterdir():
        (target / source.name).write_bytes(source.read_bytes())
    aggregate_path = target / "aggregate_v1.json"
    aggregate = json.loads(aggregate_path.read_bytes())
    aggregate["arm_summaries"]["combined"]["citation_completeness"] = 1.0
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")

    with pytest.raises(ValueError, match="canonical JSON|do not recompute"):
        verify_public_evidence(
            target,
            candidate_protocol_path=PROTOCOL,
            frozen_protocol_path=(
                ROOT
                / "docs"
                / "final_evidence_closure"
                / "evidence"
                / "answer_citation_60_protocol_v1.json"
            ),
        )
