from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_descriptor_catalog_protocol_v1 import (
    load_descriptor_catalog_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_descriptor_catalog_protocol_v1.json"
)


def test_e7_protocol_freezes_safe_descriptor_boundary() -> None:
    protocol, digest = load_descriptor_catalog_protocol_v1(PROTOCOL)

    assert len(digest) == 64
    assert protocol.status == "FROZEN_BEFORE_GATE_E7_IMPLEMENTATION"
    assert protocol.max_catalog_descriptors == 64
    assert protocol.max_descriptor_refs_per_role == 4
    assert "normalized_value" in protocol.forbidden_prompt_fields
    assert "candidate_id" in protocol.forbidden_prompt_fields
    assert "evidence_id" in protocol.forbidden_prompt_fields
    assert protocol.gates.require_guard_scan_before_prompt
    assert protocol.gates.require_exact_descriptor_enum_output
    assert protocol.gates.require_serving_route_disabled


def test_e7_protocol_preserves_unseen_evaluation_boundaries() -> None:
    protocol, _ = load_descriptor_catalog_protocol_v1(PROTOCOL)

    assert protocol.claim_label == "DISCLOSED_DEVELOPMENT_CALIBRATION"
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"
    assert protocol.oracle_gate_rule.startswith("no_live_descriptor")
