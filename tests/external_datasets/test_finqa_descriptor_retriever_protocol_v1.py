from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_descriptor_retriever_protocol_v1 import (
    load_descriptor_retriever_protocol_v1,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_descriptor_retriever_protocol_is_frozen_and_model_free() -> None:
    protocol, digest = load_descriptor_retriever_protocol_v1(
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v1.json"
    )

    assert len(digest) == 64
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"
    assert protocol.gates.max_model_requests_per_typed_case == 0
    assert protocol.gates.min_role_recall_at_8 == 0.95
    assert protocol.gates.require_serving_route_disabled is True
