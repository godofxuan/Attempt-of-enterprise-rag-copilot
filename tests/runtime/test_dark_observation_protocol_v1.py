from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.runtime.dark_observation_protocol_v1 import (
    load_dark_observation_service_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "dark_observation_service_protocol_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e16_protocol_freezes_sources_runtime_and_data_boundary() -> None:
    protocol, protocol_sha256 = load_dark_observation_service_protocol_v1(
        PROTOCOL
    )

    assert protocol_sha256 == _sha256(PROTOCOL)
    assert protocol.source_e15_protocol_sha256 == _sha256(
        EVIDENCE / "finqa_shadow_capacity_protocol_v1.json"
    )
    assert protocol.source_e15_public_evidence_sha256 == _sha256(
        EVIDENCE / "finqa_shadow_capacity_public_v1.json"
    )
    assert protocol.runtime_contract.default_mode == "OFF"
    assert protocol.runtime_contract.primary_mutation_permitted is False
    assert protocol.data_boundary.aggregate_metrics_only is True
    assert protocol.finqa_adapter_status.startswith("NOT_IMPLEMENTED")


def test_e16_protocol_rejects_post_hoc_audit_threshold_change(
    tmp_path: Path,
) -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="ascii"))
    payload["audit_profile"]["max_offer_latency_p95_ms"] = 20.0
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="ascii")

    with pytest.raises(ValidationError, match="frozen audit profile changed"):
        load_dark_observation_service_protocol_v1(changed)


def test_e16_protocol_forbids_sensitive_and_per_request_public_data() -> None:
    protocol, _ = load_dark_observation_service_protocol_v1(PROTOCOL)

    prohibited = set(protocol.public_output.prohibited_content)
    assert {"question_text", "answer_text", "tenant_id", "trace"} <= prohibited
    assert {"per_request_latency", "per_request_outcome"} <= prohibited
    assert protocol.internal_cohort_status == "CONSUMED_NOT_ACCESSED"
    assert protocol.frozen_test_status == "UNTOUCHED"
