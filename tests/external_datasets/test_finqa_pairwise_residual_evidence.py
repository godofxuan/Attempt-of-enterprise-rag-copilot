from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa_pairwise_residual_protocol_v1 import (
    load_pairwise_residual_protocol_v1,
)
from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    load_pairwise_residual_artifact_v1,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPOSITORY_ROOT / "docs/external_datasets/evidence"


def _load(name: str) -> dict[str, object]:
    payload = json.loads((EVIDENCE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(relative: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest()


def test_e10_artifact_and_cv_are_bound_to_the_frozen_protocol() -> None:
    protocol, protocol_sha256 = load_pairwise_residual_protocol_v1(
        EVIDENCE_ROOT / "finqa_pairwise_residual_protocol_v1.json"
    )
    artifact = load_pairwise_residual_artifact_v1(
        EVIDENCE_ROOT / "finqa_pairwise_residual_ranker_artifact_v1.json"
    )
    cv = _load("finqa_pairwise_residual_cv_public_v1.json")

    assert cv["protocol_sha256"] == protocol_sha256 == artifact.protocol_sha256
    assert cv["artifact_sha256"] == artifact.artifact_sha256
    assert cv["retrieval_selection_sha256"] == (
        artifact.retrieval_selection_sha256
    )
    assert artifact.retrieval_selection_sha256 == (
        protocol.training_boundary.retrieval_selection_sha256
    )
    for relative, expected in cv["implementation_sha256"].items():
        assert _sha256(relative) == expected


def test_e10_failed_the_frozen_progress_gate_and_did_not_spend_holdout() -> None:
    cv = _load("finqa_pairwise_residual_cv_public_v1.json")
    metrics = cv["cross_validation"]
    checks = cv["gate_checks"]

    assert cv["decision"] == (
        "E10_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED"
    )
    assert metrics["residual_delta_at_4"] < 0.01
    assert checks["oof_descriptor_recall_delta_at_4"] is False
    assert all(
        passed
        for name, passed in checks.items()
        if name != "oof_descriptor_recall_delta_at_4"
    )
    assert all(fold["delta_at_4"] > 0 for fold in metrics["folds"])
    assert cv["internal_validation_status"] == "NOT_RUN"
    assert cv["frozen_test_status"] == "UNTOUCHED"


def test_e10_incident_and_postmortem_preserve_the_negative_decision() -> None:
    incident = _load("finqa_pairwise_residual_protocol_erratum_v1.json")
    postmortem = _load("finqa_pairwise_residual_postmortem_public_v1.json")

    assert incident["successful_training_runs_before_erratum"] == 0
    assert incident["artifact_or_cv_evidence_written_before_erratum"] is False
    assert incident["corrected_protocol_sha256"] == _sha256(
        "docs/external_datasets/evidence/finqa_pairwise_residual_protocol_v1.json"
    )
    assert postmortem["source_cv_sha256"] == _sha256(
        "docs/external_datasets/evidence/finqa_pairwise_residual_cv_public_v1.json"
    )
    assert postmortem["serving_champion_after_gate"] == (
        "finqa_deterministic_descriptor_retriever_v5"
    )
    assert postmortem["next_data_budget_status"] == "NOT_AUTHORIZED"
