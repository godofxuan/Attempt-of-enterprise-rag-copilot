from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.external_datasets.finqa_service_adapter_protocol_v1 import (
    load_finqa_service_adapter_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "finqa_service_adapter_protocol_v1.json"


def _sha256(name: str) -> str:
    return hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()


def test_e17_protocol_binds_dark_service_and_isolated_worker() -> None:
    protocol, protocol_sha256 = load_finqa_service_adapter_protocol_v1(
        PROTOCOL
    )

    assert protocol_sha256 == (
        "d8e3433a2449ff7649b535eba416ced3a2a378b1871a640b2ad0a71508c0ea4d"
    )
    assert protocol.source_e16_protocol_sha256 == _sha256(
        "dark_observation_service_protocol_v1.json"
    )
    assert protocol.source_e16_public_evidence_sha256 == _sha256(
        "dark_observation_service_public_v1.json"
    )
    assert protocol.source_e13_protocol_sha256 == _sha256(
        "finqa_shadow_worker_replay_protocol_v1.json"
    )
    assert protocol.source_e13_public_evidence_sha256 == _sha256(
        "finqa_shadow_worker_replay_public_v1.json"
    )
    assert protocol.context_contract.primary_source == "computed_e8_in_adapter"
    assert protocol.challenger_status == "SHADOW_DEFAULT_OFF"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_e17_protocol_forbids_oracle_and_quality_fields() -> None:
    protocol, _ = load_finqa_service_adapter_protocol_v1(PROTOCOL)

    assert set(protocol.context_contract.prohibited_input_fields) == {
        "answer",
        "exe_ans",
        "gold_inds",
        "gold_program",
        "program",
        "program_re",
        "target_labels",
    }
    assert protocol.context_contract.allowed_skeleton_origins == (
        "ONLINE_RULES",
        "ONLINE_MODEL",
    )
    assert protocol.context_contract.allowed_catalog_origins == (
        "RETRIEVED_ADMITTED_EVIDENCE",
    )


def test_e17_protocol_rejects_post_hoc_origin_expansion(tmp_path: Path) -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="ascii"))
    payload["context_contract"]["allowed_skeleton_origins"].append(
        "GOLD_PROGRAM"
    )
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="ascii")

    with pytest.raises(ValidationError, match="online origin boundary changed"):
        load_finqa_service_adapter_protocol_v1(changed)


def test_e17_public_boundary_is_aggregate_only() -> None:
    protocol, _ = load_finqa_service_adapter_protocol_v1(PROTOCOL)

    assert protocol.public_output.per_request_rows_permitted is False
    assert protocol.public_output.raw_errors_permitted is False
    assert {
        "question_text",
        "request_id",
        "descriptor_ids",
        "candidate_ids",
        "evidence_ids",
    } <= set(protocol.public_output.prohibited_content)
