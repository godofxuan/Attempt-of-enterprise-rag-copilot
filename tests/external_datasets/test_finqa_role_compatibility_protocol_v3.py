from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_role_compatibility_protocol_v3 import (
    load_role_compatibility_protocol_v3,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "docs" / "external_datasets" / "evidence"
PROTOCOL = EVIDENCE / "finqa_role_compatibility_protocol_v3.json"
V2_PROTOCOL = EVIDENCE / "finqa_role_compatibility_protocol_v2.json"
V2_PUBLIC = EVIDENCE / "finqa_role_compatibility_v2_calibration_public_v4.json"


def test_gate_e6_v3_protocol_binds_authoritative_failed_v2() -> None:
    protocol, digest = load_role_compatibility_protocol_v3(PROTOCOL)

    assert len(digest) == 64
    assert protocol.source_gate_e6_v2_protocol_sha256 == hashlib.sha256(
        V2_PROTOCOL.read_bytes()
    ).hexdigest()
    assert protocol.source_gate_e6_v2_public_sha256 == hashlib.sha256(
        V2_PUBLIC.read_bytes()
    ).hexdigest()
    assert protocol.source_gate_e6_v2_run_id.endswith("audit-v4")


def test_gate_e6_v3_freezes_role_query_without_weakening_safety() -> None:
    protocol, _ = load_role_compatibility_protocol_v3(PROTOCOL)

    assert protocol.role_query_source == "planner_generated_from_question_only"
    assert protocol.max_role_query_chars == 160
    assert protocol.allow_explicit_role_period
    assert protocol.gates.min_evidence_role_recall_at_8 == 0.95
    assert protocol.gates.min_complete_typed_case_rate_at_8 == 0.90
    assert protocol.gates.require_no_gold_runtime_input
    assert protocol.gates.require_serving_route_disabled
