from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_descriptor_shadow_protocol_v1 import (
    load_descriptor_shadow_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"


def _sha256(name: str) -> str:
    return hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()


def test_e12_protocol_is_frozen_before_implementation_and_default_off() -> None:
    protocol, protocol_sha256 = load_descriptor_shadow_protocol_v1(
        EVIDENCE / "finqa_descriptor_shadow_protocol_v1.json"
    )

    assert protocol_sha256 == (
        "20323918a34ca062eb4bfbf015dabd3b21b935bd12028516936c2600e4011ec5"
    )
    assert protocol.status == "FROZEN_BEFORE_E12_IMPLEMENTATION"
    assert protocol.runtime.default_mode == "OFF"
    assert protocol.runtime.primary_must_complete_before_shadow is True
    assert protocol.runtime.challenger_replacement_permitted is False
    assert protocol.runtime.challenger_model_calls_permitted is False
    assert protocol.runtime.hard_preemption_claimed is False
    assert protocol.serving_route_status == "DISABLED"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_e12_protocol_binds_the_complete_e11_authorization_chain() -> None:
    protocol, _ = load_descriptor_shadow_protocol_v1(
        EVIDENCE / "finqa_descriptor_shadow_protocol_v1.json"
    )

    assert protocol.source_e8_protocol_sha256 == _sha256(
        "finqa_retrievable_descriptor_protocol_v1.json"
    )
    assert protocol.source_e11_protocol_sha256 == _sha256(
        "finqa_topk_ranker_protocol_v1.json"
    )
    assert protocol.source_e11_cv_sha256 == _sha256(
        "finqa_topk_nested_cv_public_v1.json"
    )
    assert protocol.source_e11_artifact_file_sha256 == _sha256(
        "finqa_topk_ranker_artifact_v1.json"
    )
    assert protocol.source_e11_internal_sha256 == _sha256(
        "finqa_topk_internal_validation_public_v1.json"
    )
    assert protocol.source_e11_postmortem_sha256 == _sha256(
        "finqa_topk_internal_postmortem_public_v1.json"
    )
    assert protocol.telemetry.per_request_persistence_permitted is False
    assert protocol.telemetry.aggregate_counters_only is True
    assert "question_text" in protocol.telemetry.prohibited_content
    assert "descriptor_ids" in protocol.telemetry.prohibited_content
