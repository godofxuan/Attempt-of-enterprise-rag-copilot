from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    load_topk_ranker_protocol_v1,
)
from app.external_datasets.finqa_topk_ranker_v1 import (
    load_topk_ranker_artifact_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"


def _load(name: str) -> dict[str, object]:
    payload = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_e11_nested_cv_authorization_chain_is_complete() -> None:
    protocol, protocol_sha256 = load_topk_ranker_protocol_v1(
        EVIDENCE / "finqa_topk_ranker_protocol_v1.json"
    )
    artifact = load_topk_ranker_artifact_v1(
        EVIDENCE / "finqa_topk_ranker_artifact_v1.json"
    )
    cv = _load("finqa_topk_nested_cv_public_v1.json")

    assert cv["protocol_sha256"] == protocol_sha256 == artifact.protocol_sha256
    assert cv["artifact_sha256"] == artifact.artifact_sha256
    assert cv["decision"] == (
        "E11_OUTER_CV_AUTHORIZED_FOR_SINGLE_INTERNAL_VALIDATION"
    )
    assert all(cv["gate_checks"].values())
    assert cv["nested_cross_validation"]["challenger_delta_at_4"] >= 0.01
    assert all(
        fold["delta_at_4"] > 0
        for fold in cv["nested_cross_validation"]["outer_folds"]
    )
    assert all(
        len(selection["candidate_metrics"])
        == len(protocol.model.candidate_configs)
        for selection in cv["nested_cross_validation"]["outer_selections"]
    )
    for relative, expected in cv["implementation_sha256"].items():
        assert _sha256(relative) == expected


def test_e11_one_shot_internal_result_passes_without_serving_activation() -> None:
    result = _load("finqa_topk_internal_validation_public_v1.json")
    descriptor = result["descriptor_recall_at_4_transitions"]
    candidate = result["candidate_recall_at_8_transitions"]

    assert result["decision"] == (
        "E11_INTERNAL_GATE_PASSED_ELIGIBLE_FOR_NEXT_STAGE"
    )
    assert result["evaluation_ordinal"] == result["evaluation_budget"] == 1
    assert all(result["gate_checks"].values())
    assert sum(descriptor.values()) == sum(candidate.values()) == 76
    assert descriptor["regressed"] == candidate["regressed"] == 0
    assert descriptor["gained"] == candidate["gained"] == 2
    assert result["serving_route_status"] == "DISABLED"
    assert result["frozen_test_status"] == "UNTOUCHED"
    for relative, expected in result["implementation_sha256"].items():
        assert _sha256(relative) == expected


def test_e11_incident_and_postmortem_limit_the_claim() -> None:
    result = _load("finqa_topk_internal_validation_public_v1.json")
    incident = _load("finqa_topk_internal_execution_incident_v1.json")
    postmortem = _load("finqa_topk_internal_postmortem_public_v1.json")

    assert result["source_execution_incident_sha256"] == _sha256(
        "docs/external_datasets/evidence/finqa_topk_internal_execution_incident_v1.json"
    )
    assert incident["artifact_or_result_written"] is False
    assert postmortem["source_internal_result_sha256"] == _sha256(
        "docs/external_datasets/evidence/finqa_topk_internal_validation_public_v1.json"
    )
    assert postmortem["evaluated_typed_case_count"] == 37
    assert postmortem["fallback_case_count"] == 3
    assert postmortem["mcnemar_exact_two_sided_p"] == 0.5
    assert postmortem["serving_route_status"] == "DISABLED"
