from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_descriptor_retriever_protocol_v2 import (
    load_descriptor_retriever_protocol_v2,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_retriever_v2_protocol_preserves_v1_gate_thresholds() -> None:
    protocol, digest = load_descriptor_retriever_protocol_v2(
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v2.json"
    )

    assert len(digest) == 64
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.gates.min_role_recall_at_4 == 0.85
    assert protocol.gates.min_role_recall_at_8 == 0.95
    assert protocol.gates.max_model_requests_per_typed_case == 0
    assert len(protocol.interventions) == 3
