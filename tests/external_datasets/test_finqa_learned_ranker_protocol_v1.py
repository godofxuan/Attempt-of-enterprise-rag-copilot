from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_learned_ranker_protocol_v1 import (
    load_learned_ranker_protocol_v1,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "docs/external_datasets/evidence/finqa_learned_ranker_protocol_v1.json"
)


def test_e9_protocol_freezes_company_disjoint_training_and_folds() -> None:
    protocol, digest = load_learned_ranker_protocol_v1(PROTOCOL_PATH)

    assert len(digest) == 64
    assert protocol.training_boundary.eligible_case_count == 3068
    assert protocol.training_boundary.eligible_company_count == 99
    assert [fold.case_count for fold in protocol.folds] == [614, 615, 613, 613, 613]
    assert [fold.company_count for fold in protocol.folds] == [18, 21, 20, 20, 20]
    assert protocol.model.hyperparameter_search == "NONE"
    assert protocol.development_evaluation_budget == 1
    assert protocol.internal_validation_status == "NOT_RUN"
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_e9_protocol_binds_immutable_e8_sources() -> None:
    protocol, _ = load_learned_ranker_protocol_v1(PROTOCOL_PATH)
    sources = {
        "source_e8_protocol_sha256": (
            "docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json"
        ),
        "source_e8_result_sha256": (
            "docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json"
        ),
    }
    for field, relative in sources.items():
        actual = hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest()
        assert actual == getattr(protocol, field)


def test_e9_protocol_prohibits_identity_and_gold_runtime_features() -> None:
    protocol, _ = load_learned_ranker_protocol_v1(PROTOCOL_PATH)

    prohibited = set(protocol.model.prohibited_features)
    assert {"case_id", "company_id", "gold_program", "numeric_value"} <= prohibited
    assert not prohibited.intersection(protocol.model.feature_names)
    assert protocol.challenger_serving_status == "DISABLED"
    assert "keeps_e8_champion" in protocol.fallback_rule
