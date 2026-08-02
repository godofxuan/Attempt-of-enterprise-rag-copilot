from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_retrievable_descriptor_protocol_v1 import (
    load_retrievable_descriptor_protocol_v1,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json"
)


def test_e8_protocol_freezes_layered_baseline_and_long_term_targets() -> None:
    protocol, digest = load_retrievable_descriptor_protocol_v1(PROTOCOL_PATH)

    assert len(digest) == 64
    assert protocol.baseline.descriptor_recall_at_4 == 0.8373983739837398
    assert protocol.baseline.conditional_candidate_retention_at_8 == (
        0.941747572815534
    )
    assert protocol.progress_gates.min_candidate_recall_at_8 == 0.84
    assert protocol.long_term_targets.min_candidate_recall_at_8 == 0.95
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_e8_protocol_binds_exact_e7_source_evidence() -> None:
    protocol, _ = load_retrievable_descriptor_protocol_v1(PROTOCOL_PATH)
    sources = {
        "source_e7_catalog_protocol_sha256": (
            "docs/external_datasets/evidence/finqa_descriptor_catalog_protocol_v1.json"
        ),
        "source_e7_catalog_upper_bound_v2_sha256": (
            "docs/external_datasets/evidence/finqa_descriptor_catalog_upper_bound_public_v2.json"
        ),
        "source_e7_retriever_v2_result_sha256": (
            "docs/external_datasets/evidence/finqa_descriptor_retriever_public_v2.json"
        ),
    }
    for field, relative in sources.items():
        actual = hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest()
        assert actual == getattr(protocol, field)
