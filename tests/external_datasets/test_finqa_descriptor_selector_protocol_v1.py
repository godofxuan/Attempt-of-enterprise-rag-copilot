from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_descriptor_selector_protocol_v1 import (
    load_descriptor_selector_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    ROOT
    / "docs/external_datasets/evidence/finqa_descriptor_selector_protocol_v1.json"
)


def test_live_descriptor_selector_protocol_is_frozen() -> None:
    protocol, digest = load_descriptor_selector_protocol_v1(PROTOCOL)

    assert len(digest) == 64
    assert protocol.model == "qwen3:8b"
    assert protocol.model_digest == "500a1f067a9f"
    assert protocol.temperature == 0
    assert protocol.think is False
    assert protocol.gates.min_role_recall_at_8 == 0.95
    assert protocol.gates.min_complete_typed_case_rate_at_8 == 0.9
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"
