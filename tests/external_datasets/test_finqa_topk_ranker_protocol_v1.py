from __future__ import annotations

import hashlib
from pathlib import Path

from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    load_topk_ranker_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "docs/external_datasets/evidence/finqa_topk_ranker_protocol_v1.json"


def test_e11_protocol_freezes_nested_top4_and_holdout_boundaries() -> None:
    protocol, digest = load_topk_ranker_protocol_v1(PROTOCOL)

    assert len(digest) == 64
    assert protocol.model.target_cutoff == 4
    assert len(protocol.model.candidate_configs) == 18
    assert protocol.model.candidate_configs[0].config_id == "adj02-l2-100-p100"
    assert protocol.model.candidate_configs[-1].config_id == "adj08-l2-001-p025"
    assert protocol.model.dependency_boundary == "numpy_only_no_new_ml_dependency"
    assert protocol.training_boundary.prior_train_oof_reuse.startswith("DISCLOSED")
    assert protocol.internal_validation.status == "NOT_RUN"
    assert protocol.internal_validation.evaluation_budget == 1
    assert protocol.frozen_test_status == "UNTOUCHED"


def test_e11_protocol_binds_e10_negative_decision_files() -> None:
    protocol, _ = load_topk_ranker_protocol_v1(PROTOCOL)
    sources = {
        "source_e10_protocol_sha256": "docs/external_datasets/evidence/finqa_pairwise_residual_protocol_v1.json",
        "source_e10_cv_sha256": "docs/external_datasets/evidence/finqa_pairwise_residual_cv_public_v1.json",
        "source_e10_artifact_file_sha256": "docs/external_datasets/evidence/finqa_pairwise_residual_ranker_artifact_v1.json",
        "source_e10_postmortem_sha256": "docs/external_datasets/evidence/finqa_pairwise_residual_postmortem_public_v1.json",
        "source_e10_erratum_sha256": "docs/external_datasets/evidence/finqa_pairwise_residual_protocol_erratum_v1.json",
    }
    for field, relative in sources.items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == getattr(protocol, field)
