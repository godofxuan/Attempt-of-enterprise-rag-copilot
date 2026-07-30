from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_v23_calibration_protocol import (
    load_v23_calibration_protocol,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_v23_paired_calibration_protocol_v1.json"
)
E2_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_public_v1.json"
)
E3_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_calibration_public_v1.json"
)


def test_v23_protocol_binds_public_sources_and_sealed_cohorts():
    protocol, digest = load_v23_calibration_protocol(PROTOCOL)

    assert len(digest) == 64
    assert protocol.source_gate_e2_public_sha256 == hashlib.sha256(
        E2_PUBLIC.read_bytes()
    ).hexdigest()
    assert protocol.source_gate_e3_public_sha256 == hashlib.sha256(
        E3_PUBLIC.read_bytes()
    ).hexdigest()
    assert protocol.calibration_case_count == 60
    assert protocol.internal_validation_case_count == 40
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_v23_protocol_allows_model_calls_only_for_intervention():
    protocol, _ = load_v23_calibration_protocol(PROTOCOL)
    arms = {arm.arm_id: arm for arm in protocol.arms}

    assert not arms["B0_STORED"].model_calls_allowed
    assert not arms["B1_V22_STORED"].model_calls_allowed
    assert arms["B1_V23_INTERVENTION"].model_calls_allowed
    assert protocol.max_attempts_per_case == 2


def test_v23_protocol_requires_both_progress_and_b0_shadow_gates():
    protocol, _ = load_v23_calibration_protocol(PROTOCOL)

    assert protocol.progress_gates.min_execution_accuracy_delta_vs_v22 == 0.05
    assert protocol.progress_gates.max_correct_to_wrong_rate_vs_v22 == 0.05
    assert protocol.adoption_shadow_gates.min_execution_accuracy_delta_vs_b0 == -0.05
    assert (
        protocol.internal_validation_eligibility_rule
        == "all_progress_and_adoption_shadow_gates_pass"
    )
