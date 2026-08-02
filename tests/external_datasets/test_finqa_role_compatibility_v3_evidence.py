from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "docs" / "external_datasets" / "evidence"
PUBLIC = EVIDENCE / "finqa_role_compatibility_v3_upper_bound_public_v1.json"
PROTOCOL = EVIDENCE / "finqa_role_compatibility_protocol_v3.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_upper_bound_evidence_is_bound_and_non_serving() -> None:
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))

    assert payload["decision"] == "UPPER_BOUND_INPUT_GATE_PASSED"
    assert payload["protocol_sha256"] == _sha256(PROTOCOL)
    assert payload["model_call_count"] == 0
    assert payload["serving_route_status"] == "DISABLED"
    assert payload["no_gold_runtime_input_verified"]
    assert payload["claim"] == "OFFLINE_GOLD_DESCRIPTOR_UPPER_BOUND_ONLY"
    assert "not planner quality" in payload["non_claims"]


def test_v3_upper_bound_evidence_binds_implementation_bytes() -> None:
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))

    for relative, expected in payload["implementation_sha256"].items():
        assert _sha256(REPOSITORY_ROOT / relative) == expected


def test_v3_upper_bound_passes_frozen_coverage_thresholds() -> None:
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))

    assert payload["role_recall_at_4"] >= 0.85
    assert payload["role_recall_at_8"] >= 0.95
    assert payload["complete_typed_case_rate_at_8"] >= 0.90
    assert payload["edge_reduction_rate"] >= 0.70
