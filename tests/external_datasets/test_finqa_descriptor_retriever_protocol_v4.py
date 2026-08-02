from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_descriptor_retriever_protocol_v4 import (
    load_descriptor_retriever_protocol_v4,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_structured_retriever_protocol_keeps_quality_gate_and_zero_model_calls() -> None:
    protocol, digest = load_descriptor_retriever_protocol_v4(
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v4.json"
    )

    assert len(digest) == 64
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.structural_bonus == 120.0
    assert protocol.gates.min_role_recall_at_8 == 0.95
    assert protocol.gates.max_model_requests_per_typed_case == 0
