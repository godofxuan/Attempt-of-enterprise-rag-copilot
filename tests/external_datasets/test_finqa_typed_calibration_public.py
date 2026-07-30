from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.finqa_typed_calibration_public import (
    CalibrationShadowGate,
    FinQATypedCalibrationPublicEvidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_EVIDENCE = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_public_v1.json"
)
FORBIDDEN_RAW_KEYS = {
    "case_id",
    "case_ids",
    "question",
    "answer",
    "answers",
    "evidence_text",
    "gold_program",
    "selected_candidate_ids",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_tracked_public_calibration_evidence_is_aggregate_and_reconciled():
    raw = json.loads(PUBLIC_EVIDENCE.read_text(encoding="utf-8"))
    evidence = FinQATypedCalibrationPublicEvidence.model_validate(raw)

    assert evidence.decision == "CALIBRATION_REJECTED"
    assert evidence.internal_validation_status == "NOT_RUN"
    assert evidence.multi_program_status == "NOT_RUN"
    assert evidence.best_iteration == "v2_2"
    assert evidence.calibration_case_count == 60
    assert all(
        iteration.summary.case_count == evidence.calibration_case_count
        for iteration in evidence.iterations
    )
    assert (
        sum(
            evidence.candidate_shortlist_audit
            .best_iteration_outcome_by_operand_availability.values()
        )
        == evidence.calibration_case_count
    )
    assert not (set(_walk_keys(raw)) & FORBIDDEN_RAW_KEYS)


def test_tracked_public_calibration_evidence_preserves_failed_gates():
    evidence = FinQATypedCalibrationPublicEvidence.model_validate_json(
        PUBLIC_EVIDENCE.read_bytes()
    )
    gates = {
        gate.metric: gate for gate in evidence.best_iteration_shadow_gates
    }

    assert not gates["execution_accuracy_delta_vs_b0"].passed
    assert not gates["grounded_accuracy_delta_vs_b0"].passed
    assert not gates["correct_to_wrong_rate"].passed
    assert not gates["protocol_error_rate"].passed
    assert gates["coverage"].passed
    assert gates["latency_p95_ms"].passed


def test_public_shadow_gate_rejects_a_forged_pass():
    with pytest.raises(
        ValueError,
        match="shadow gate result contradicts observed threshold",
    ):
        CalibrationShadowGate(
            metric="coverage",
            observed=0.40,
            required=0.50,
            passed=True,
        )
