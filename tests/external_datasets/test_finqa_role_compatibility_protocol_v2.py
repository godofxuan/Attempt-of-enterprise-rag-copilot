from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_role_compatibility_protocol_v2 import (
    load_role_compatibility_protocol_v2,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_protocol_v2.json"
)
V1_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_protocol_v1.json"
)
V1_PUBLIC_V3 = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_calibration_public_v3.json"
)


def test_gate_e6_v2_protocol_binds_authoritative_v1_diagnosis() -> None:
    protocol, digest = load_role_compatibility_protocol_v2(PROTOCOL)

    assert len(digest) == 64
    assert protocol.source_gate_e6_v1_protocol_sha256 == hashlib.sha256(
        V1_PROTOCOL.read_bytes()
    ).hexdigest()
    assert protocol.source_gate_e6_v1_public_sha256 == hashlib.sha256(
        V1_PUBLIC_V3.read_bytes()
    ).hexdigest()
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_gate_e6_v2_protocol_freezes_structural_changes() -> None:
    protocol, _ = load_role_compatibility_protocol_v2(PROTOCOL)

    assert protocol.runtime_source_pool == (
        "guard_admitted_operand_candidates_before_global_shortlist"
    )
    assert protocol.max_source_candidates == 128
    assert protocol.max_evidence_candidates_per_role == 8
    assert protocol.max_unique_exposed_candidate_ids == 32
    assert protocol.max_program_steps == 5
    assert protocol.max_semantic_roles == 8
    assert protocol.controlled_constant_registry == (
        "const_1",
        "const_2",
        "const_3",
        "const_4",
        "const_5",
        "const_10",
        "const_100",
        "const_1000",
    )


def test_gate_e6_v2_protocol_keeps_coverage_and_safety_shadow_gates() -> None:
    protocol, _ = load_role_compatibility_protocol_v2(PROTOCOL)
    gates = protocol.gates

    assert gates.min_typed_eligible_case_rate == 0.95
    assert gates.min_runtime_capability_route_accuracy == 0.95
    assert gates.min_evidence_role_source_recall == 0.98
    assert gates.min_evidence_role_recall_at_8 == 0.95
    assert gates.min_complete_typed_case_rate_at_8 == 0.90
    assert gates.require_controlled_constant_enum_enforcement
    assert gates.require_serving_route_disabled
