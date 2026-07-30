from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_semantic_planning_protocol import (
    load_semantic_planning_protocol,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_protocol_v1.json"
)
E4_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_v23_paired_calibration_public_v1.json"
)


def test_gate_e5_protocol_binds_gate_e4_and_sealed_cohorts() -> None:
    protocol, digest = load_semantic_planning_protocol(PROTOCOL)

    assert len(digest) == 64
    assert protocol.source_gate_e4_public_sha256 == hashlib.sha256(
        E4_PUBLIC.read_bytes()
    ).hexdigest()
    assert protocol.calibration_case_count == 60
    assert protocol.internal_validation_case_count == 40
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_gate_e5_protocol_isolates_dynamic_demonstrations() -> None:
    protocol, _ = load_semantic_planning_protocol(PROTOCOL)

    assert protocol.dynamic_demo_source == "pinned_train_split_only"
    assert protocol.dynamic_demo_count == 3
    assert protocol.dynamic_demo_payload == (
        "question_plus_value_free_operation_skeleton"
    )
    assert protocol.training_split_sha256 == (
        "49f237eb9779b569473b26b08048867d04635a7cc39ad6a7a5664c55bb428db6"
    )


def test_gate_e5_protocol_freezes_three_intervention_arms() -> None:
    protocol, _ = load_semantic_planning_protocol(PROTOCOL)
    arms = {arm.arm_id: arm for arm in protocol.arms}

    assert not arms["B1_V23_STORED"].model_calls_allowed
    assert arms["B2_MULTI_STEP_DIRECT"].model_calls_allowed
    assert not arms["B2_MULTI_STEP_DIRECT"].role_decomposition
    assert arms["B3_ROLE_DECOMPOSED"].role_decomposition
    assert not arms["B3_ROLE_DECOMPOSED"].dynamic_demonstrations
    assert arms["B4_ROLE_DYNAMIC_DEMOS"].dynamic_demonstrations
    assert protocol.max_program_steps == 3
    assert protocol.max_semantic_roles == 6


def test_gate_e5_protocol_requires_progress_and_b0_shadow() -> None:
    protocol, _ = load_semantic_planning_protocol(PROTOCOL)

    assert (
        protocol.progress_gates.min_execution_accuracy_delta_vs_v23
        == 0.1
    )
    assert protocol.progress_gates.max_protocol_error_rate == 0.15
    assert (
        protocol.adoption_shadow_gates.min_execution_accuracy_delta_vs_b0
        == -0.05
    )
