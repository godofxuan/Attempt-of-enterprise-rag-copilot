from __future__ import annotations

import json

import pytest

from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PAIRWISE_FEATURE_NAMES,
    PairwiseRoleGroupV1,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    FinQATopKCandidateV1,
)
from app.external_datasets.finqa_topk_ranker_v1 import (
    FinQATopKRankerArtifactV1,
    build_topk_ranker_artifact_v1,
    fit_topk_weighted_ridge_v1,
)


def _config() -> FinQATopKCandidateV1:
    return FinQATopKCandidateV1(
        config_id="adj04-l2-010-p100",
        max_e8_score_adjustment=4.0,
        l2_penalty=10.0,
        preservation_weight=1.0,
    )


def _features(value: float) -> tuple[float, ...]:
    return (value,) + tuple(0.0 for _ in PAIRWISE_FEATURE_NAMES[1:])


def _miss_group() -> PairwiseRoleGroupV1:
    return PairwiseRoleGroupV1(
        descriptor_ids=tuple(f"desc-{index:016x}" for index in range(5)),
        e8_scores=(4.0, 3.0, 2.0, 1.0, 0.0),
        features=tuple(_features(1.0 if index == 4 else 0.0) for index in range(5)),
        labels=(False, False, False, False, True),
    )


def _preservation_group() -> PairwiseRoleGroupV1:
    return PairwiseRoleGroupV1(
        descriptor_ids=tuple(f"desc-{index:016x}" for index in range(5, 10)),
        e8_scores=(4.0, 3.0, 2.0, 1.0, 0.0),
        features=tuple(_features(1.0 if index == 0 else 0.0) for index in range(5)),
        labels=(True, False, False, False, False),
    )


def test_topk_fit_builds_miss_and_preservation_pairs() -> None:
    fit = fit_topk_weighted_ridge_v1(
        (_miss_group(), _preservation_group()),
        config=_config(),
        target_cutoff=4,
        boundary_negative_depth=4,
        miss_pair_weight=1.0,
    )

    assert fit.pair_stats.miss_group_count == 1
    assert fit.pair_stats.preservation_group_count == 1
    assert fit.pair_stats.pair_count == 5
    assert fit.pair_stats.effective_pair_weight == pytest.approx(2.0)
    assert fit.utility(_features(1.0)) > fit.utility(_features(0.0))


def test_topk_group_with_two_top4_positives_needs_no_single_swap_pair() -> None:
    redundant = PairwiseRoleGroupV1(
        descriptor_ids=tuple(f"desc-{index:016x}" for index in range(10, 15)),
        e8_scores=(4.0, 3.0, 2.0, 1.0, 0.0),
        features=tuple(_features(float(index % 2)) for index in range(5)),
        labels=(True, True, False, False, False),
    )
    fit = fit_topk_weighted_ridge_v1(
        (_miss_group(), redundant),
        config=_config(),
        target_cutoff=4,
        boundary_negative_depth=4,
        miss_pair_weight=1.0,
    )

    assert fit.pair_stats.redundant_hit_group_count == 1
    assert fit.pair_stats.pair_count == 4


def test_topk_artifact_rejects_coefficient_tampering() -> None:
    fit = fit_topk_weighted_ridge_v1(
        (_miss_group(), _preservation_group()),
        config=_config(),
        target_cutoff=4,
        boundary_negative_depth=4,
        miss_pair_weight=1.0,
    )
    artifact = build_topk_ranker_artifact_v1(
        fit=fit,
        protocol_sha256="a" * 64,
        training_split_sha256="b" * 64,
        retrieval_selection_sha256="c" * 64,
        selected_config=_config(),
        target_cutoff=4,
        boundary_negative_depth=4,
        miss_pair_weight=1.0,
        residual_clip=1.0,
        training_group_count=2,
    )
    payload = json.loads(artifact.model_dump_json())
    payload["coefficients"][0] += 1.0

    with pytest.raises(ValueError, match="artifact hash"):
        FinQATopKRankerArtifactV1.model_validate(payload)
