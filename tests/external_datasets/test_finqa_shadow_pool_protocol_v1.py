from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_shadow_pool_protocol_v1 import (
    load_shadow_pool_replay_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "finqa_shadow_pool_replay_protocol_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e14_protocol_freezes_bounded_pool_and_e13_evidence_chain() -> None:
    protocol, protocol_sha256 = load_shadow_pool_replay_protocol_v1(PROTOCOL)

    assert protocol_sha256 == (
        "c92c4e99a189620a70a5600433f1bc0e3e21e5338dd21bbbc7da3ec5bcf5272b"
    )
    assert protocol.source_e13_protocol_sha256 == _sha256(
        EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
    )
    assert protocol.source_e13_public_evidence_sha256 == _sha256(
        EVIDENCE / "finqa_shadow_worker_replay_public_v1.json"
    )
    assert protocol.pool.worker_count == 2
    assert protocol.pool.queue_capacity == 4
    assert protocol.pool.overload_policy == "reject_newest"
    assert protocol.pool.late_result_policy == (
        "discard_without_primary_mutation"
    )
    assert protocol.challenger_status == "SHADOW_DEFAULT_OFF"
    assert protocol.internal_cohort_status == "CONSUMED_NOT_ACCESSED"
    assert protocol.frozen_test_status == "UNTOUCHED"
    assert protocol.public_output.per_request_rows_permitted is False
