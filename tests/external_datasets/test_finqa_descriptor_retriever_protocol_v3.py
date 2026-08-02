from __future__ import annotations

from pathlib import Path

from app.external_datasets.finqa_descriptor_retriever_protocol_v3 import (
    load_descriptor_retriever_protocol_v3,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_hybrid_retriever_protocol_pins_model_and_request_budget() -> None:
    protocol, digest = load_descriptor_retriever_protocol_v3(
        REPOSITORY_ROOT
        / "docs/external_datasets/evidence/finqa_descriptor_retriever_protocol_v3.json"
    )

    assert len(digest) == 64
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.embedding_dimension == 1024
    assert len(protocol.embedding_model_sha256) == 64
    assert protocol.gates.max_embedding_requests_per_typed_case == 1
    assert protocol.gates.max_generation_requests_per_typed_case == 0
    assert protocol.gates.require_safe_descriptor_only_embedding_payload is True
