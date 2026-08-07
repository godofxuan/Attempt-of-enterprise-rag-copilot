from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.external_datasets.finqa_admitted_context_protocol_v1 import (
    load_finqa_admitted_context_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "external_datasets" / "evidence"
PROTOCOL = EVIDENCE / "finqa_admitted_context_protocol_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e18_protocol_preserves_historical_guard_binding() -> None:
    protocol, digest = load_finqa_admitted_context_protocol_v1(PROTOCOL)

    assert len(digest) == 64
    assert protocol.source_e17_protocol_sha256 == _sha256(
        EVIDENCE / "finqa_service_adapter_protocol_v1.json"
    )
    assert protocol.source_e17_public_evidence_sha256 == _sha256(
        EVIDENCE / "finqa_service_adapter_public_v1.json"
    )
    assert protocol.source_guard_sha256 == (
        "78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2"
    )
    assert protocol.source_guard_sha256 != _sha256(
        ROOT / "app" / "security" / "retrieved_content.py"
    )


def test_e18_protocol_freezes_no_reretrieval_no_model_and_cleanup() -> None:
    protocol, _ = load_finqa_admitted_context_protocol_v1(PROTOCOL)

    assert protocol.input_contract.secondary_retrieval_calls == 0
    assert protocol.planning_contract.planner_model_calls == 0
    assert protocol.primary_isolation.same_response_object_required is True
    assert protocol.primary_isolation.default_mode == "OFF"
    assert set(protocol.admission_contract.discard_offer_outcomes) == {
        "BACKPRESSURE",
        "CLOSED",
        "DISABLED",
        "SAMPLE_SKIPPED",
        "UNAVAILABLE",
    }
    assert protocol.standard_fastapi_route_status == (
        "DISABLED_PENDING_VERSIONED_WIRING"
    )


def test_e18_protocol_rejects_boundary_drift(tmp_path: Path) -> None:
    changed = PROTOCOL.read_text(encoding="ascii").replace(
        '"secondary_retrieval_calls":0',
        '"secondary_retrieval_calls":1',
        1,
    )
    path = tmp_path / "changed.json"
    path.write_text(changed, encoding="ascii")

    with pytest.raises(ValidationError):
        load_finqa_admitted_context_protocol_v1(path)
