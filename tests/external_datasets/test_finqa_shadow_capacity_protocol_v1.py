from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.external_datasets.finqa_shadow_capacity_protocol_v1 import (
    load_shadow_capacity_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "finqa_shadow_capacity_protocol_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e15_protocol_freezes_matrix_sources_and_comparisons() -> None:
    protocol, protocol_sha256 = load_shadow_capacity_protocol_v1(PROTOCOL)

    assert protocol_sha256 == _sha256(PROTOCOL)
    assert protocol.matrix.worker_counts == (1, 2, 4)
    assert protocol.matrix.caller_concurrency == (1, 4, 8)
    assert protocol.matrix.repetitions == 3
    assert protocol.gates.required_trial_count == 27
    assert protocol.source_e14_protocol_sha256 == _sha256(
        EVIDENCE / "finqa_shadow_pool_replay_protocol_v1.json"
    )
    assert protocol.source_e14_public_evidence_sha256 == _sha256(
        EVIDENCE / "finqa_shadow_pool_replay_public_v1.json"
    )
    assert [item.comparison_id for item in protocol.gates.comparisons] == [
        "workers_1_to_2_callers_4",
        "workers_1_to_4_callers_8",
    ]


def test_e15_protocol_rejects_post_hoc_matrix_change(tmp_path: Path) -> None:
    payload = json.loads(PROTOCOL.read_text(encoding="ascii"))
    payload["matrix"]["worker_counts"] = [1, 2, 8]
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="ascii")

    with pytest.raises(ValidationError, match="worker-count matrix changed"):
        load_shadow_capacity_protocol_v1(changed)


def test_e15_protocol_forbids_per_request_public_rows() -> None:
    protocol, _ = load_shadow_capacity_protocol_v1(PROTOCOL)

    assert protocol.public_output.per_request_rows_permitted is False
    assert protocol.public_output.per_trial_aggregate_rows_permitted is True
    assert "per_request_latency" in protocol.public_output.prohibited_content
    assert "per_request_outcome" in protocol.public_output.prohibited_content
    assert protocol.internal_cohort_status == "CONSUMED_NOT_ACCESSED"
    assert protocol.frozen_test_status == "UNTOUCHED"
