from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_role_compatibility_protocol import (
    load_role_compatibility_protocol,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_protocol_v1.json"
)
E5_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_protocol_v1.json"
)
E5_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_public_v1.json"
)


def test_gate_e6_protocol_binds_rejected_gate_e5() -> None:
    protocol, digest = load_role_compatibility_protocol(PROTOCOL)

    assert len(digest) == 64
    assert protocol.source_gate_e5_protocol_sha256 == hashlib.sha256(
        E5_PROTOCOL.read_bytes()
    ).hexdigest()
    assert protocol.source_gate_e5_public_sha256 == hashlib.sha256(
        E5_PUBLIC.read_bytes()
    ).hexdigest()
    assert protocol.calibration_case_count == 60
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_gate_e6_protocol_separates_runtime_inputs_from_gold_diagnostics() -> None:
    protocol, _ = load_role_compatibility_protocol(PROTOCOL)

    assert protocol.diagnostic_skeleton_source == (
        "gold_program_offline_diagnostic_only"
    )
    assert set(protocol.runtime_inputs) == {
        "question",
        "question_intent",
        "semantic_skeleton",
        "admitted_numeric_candidates",
        "admitted_evidence_context",
    }
    assert protocol.model_call_count == 0
    assert protocol.live_model_gate_rule == (
        "no_gate_e6_model_run_unless_input_gate_passes"
    )


def test_gate_e6_protocol_pre_registers_bounded_input_gates() -> None:
    protocol, _ = load_role_compatibility_protocol(PROTOCOL)

    assert protocol.max_global_candidates == 24
    assert protocol.max_candidates_per_role == 8
    assert protocol.diagnostic_cutoffs == (4, 8)
    assert protocol.gates.min_hard_filter_gold_role_retention == 0.98
    assert protocol.gates.min_gold_role_recall_at_4 == 0.90
    assert protocol.gates.min_gold_role_recall_at_8 == 0.95
    assert protocol.gates.min_complete_case_rate_at_8 == 0.90
    assert protocol.gates.min_role_candidate_edge_reduction_rate == 0.50
    assert protocol.gates.require_no_gold_runtime_input
    assert protocol.gates.require_input_order_invariance
    assert protocol.gates.require_zero_silent_global_fallbacks
    assert protocol.gates.require_role_exact_parser_enforcement
