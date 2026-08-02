from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_pairwise_residual_protocol_v1 import (
    load_pairwise_residual_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = (
    ROOT
    / "docs/external_datasets/evidence/finqa_pairwise_residual_protocol_v1.json"
)


def test_e10_protocol_freezes_retrieval_pairwise_and_residual_boundaries() -> None:
    protocol, digest = load_pairwise_residual_protocol_v1(PROTOCOL)

    assert len(digest) == 64
    assert protocol.training_boundary.max_selected_units_per_case == 10
    assert protocol.training_boundary.min_selected_units_observed == 6
    assert protocol.training_boundary.full_gold_evidence_coverage_count == 3014
    assert protocol.model.max_hard_negatives_per_positive == 8
    assert protocol.model.max_e8_score_adjustment == 4.0
    assert "e8_score" in protocol.model.prohibited_features
    assert "candidate_count_log1p" in protocol.model.prohibited_features
    assert protocol.internal_validation.status == "NOT_RUN"
    assert protocol.internal_validation.evaluation_budget == 1
    assert protocol.e9_development_evaluation_status == "CONSUMED_NO_RERUN"


def test_e10_protocol_binds_e9_negative_result_and_postmortem() -> None:
    protocol, _ = load_pairwise_residual_protocol_v1(PROTOCOL)
    sources = {
        "source_e8_result_sha256": "docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json",
        "source_e9_protocol_sha256": "docs/external_datasets/evidence/finqa_learned_ranker_protocol_v1.json",
        "source_e9_cv_sha256": "docs/external_datasets/evidence/finqa_learned_descriptor_cv_public_v1.json",
        "source_e9_development_sha256": "docs/external_datasets/evidence/finqa_learned_descriptor_development_public_v1.json",
        "source_e9_postmortem_sha256": "docs/external_datasets/evidence/finqa_learned_descriptor_postmortem_public_v1.json",
    }
    for field, relative in sources.items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == getattr(protocol, field)
