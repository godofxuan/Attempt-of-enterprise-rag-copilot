from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPOSITORY_ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE_ROOT / "finqa_retrievable_descriptor_protocol_v1.json"
RESULT = EVIDENCE_ROOT / "finqa_retrievable_descriptor_public_v1.json"
ABLATION = (
    EVIDENCE_ROOT / "finqa_retrievable_descriptor_ablation_public_v1.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e8_public_result_matches_bound_implementation_and_protocol() -> None:
    result = json.loads(RESULT.read_text(encoding="ascii"))

    assert result["protocol_sha256"] == _sha256(PROTOCOL)
    assert result["progress_decision"] == "E8_DEVELOPMENT_PROGRESS_GATE_FAILED"
    assert result["long_term_target_status"] == "LONG_TERM_TARGETS_NOT_MET"
    assert result["serving_route_status"] == "DISABLED"
    assert result["internal_validation_status"] == "NOT_RUN"
    assert result["frozen_test_status"] == "UNTOUCHED"
    for relative, expected in result["implementation_sha256"].items():
        assert _sha256(REPOSITORY_ROOT / relative) == expected


def test_e8_ablation_preserves_negative_runs_and_selected_configuration() -> None:
    ablation = json.loads(ABLATION.read_text(encoding="ascii"))

    assert ablation["protocol_sha256"] == _sha256(PROTOCOL)
    assert ablation["selected_configuration"] == {
        "descriptor_priority_step": 0.0,
        "candidate_local_weight": 1.0,
        "reason": (
            "all positive descriptor-priority steps reduced candidate Recall@8; "
            "local context preserved Recall@8 and improved complete-case and "
            "Oracle retention versus local weight zero"
        ),
    }
    assert ablation["runs"][0]["public_result_sha256"] == _sha256(RESULT)
    priority_runs = {
        item["descriptor_priority_step"]: item
        for item in ablation["runs"]
        if item["candidate_local_weight"] == 1.0
    }
    assert set(priority_runs) == {0.0, 1.0, 2.0, 4.0, 8.0}
    assert all(
        priority_runs[step]["candidate_recall_at_8"]
        < priority_runs[0.0]["candidate_recall_at_8"]
        for step in (1.0, 2.0, 4.0, 8.0)
    )
    assert ablation["serving_route_status"] == "DISABLED"
