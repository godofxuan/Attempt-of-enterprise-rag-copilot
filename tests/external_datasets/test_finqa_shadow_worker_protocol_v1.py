from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_shadow_worker_protocol_v1 import (
    load_shadow_worker_replay_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"


def _sha256(name: str) -> str:
    return hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()


def test_e13_protocol_is_frozen_and_binds_e12() -> None:
    protocol, protocol_sha256 = load_shadow_worker_replay_protocol_v1(
        EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
    )

    assert protocol_sha256 == (
        "4604572c065d69d8d79f7287cfb206143c01e1ea11c4a6ec85c0bea4ee845f97"
    )
    assert protocol.status == "FROZEN_BEFORE_E13_IMPLEMENTATION"
    assert protocol.source_e12_protocol_sha256 == _sha256(
        "finqa_descriptor_shadow_protocol_v1.json"
    )
    assert protocol.source_e12_mechanism_sha256 == _sha256(
        "finqa_descriptor_shadow_mechanism_public_v1.json"
    )
    assert protocol.challenger_status == "SHADOW_DEFAULT_OFF"
    assert protocol.internal_cohort_status == "CONSUMED_NOT_ACCESSED"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_e13_protocol_freezes_process_and_unlabeled_replay_boundaries() -> None:
    protocol, _ = load_shadow_worker_replay_protocol_v1(
        EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
    )

    assert protocol.dataset.split == "train"
    assert protocol.dataset.selected_case_count == 128
    assert protocol.dataset.selected_company_count == 71
    assert protocol.dataset.typed_input_source == "gold_program_structure_only"
    assert protocol.worker.start_method == "spawn"
    assert protocol.worker.restart_after_timeout is True
    assert protocol.worker.restart_after_crash is True
    assert protocol.worker.os_network_sandbox_claimed is False
    assert protocol.public_output.per_request_rows_permitted is False
    assert "per_request_latency" in protocol.public_output.prohibited_content
