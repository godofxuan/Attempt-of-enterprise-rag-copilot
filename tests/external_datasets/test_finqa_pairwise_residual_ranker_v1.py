from __future__ import annotations

import json
import hashlib

import pytest

from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PAIRWISE_FEATURE_NAMES,
    FinQAPairwiseResidualArtifactV1,
    PairwiseResidualFinQADescriptorRetrieverV1,
    PairwiseRoleGroupV1,
    build_pairwise_residual_artifact_v1,
    fit_pairwise_ridge_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


def _group() -> PairwiseRoleGroupV1:
    zero = tuple(0.0 for _ in PAIRWISE_FEATURE_NAMES)
    one = (1.0,) + tuple(0.0 for _ in PAIRWISE_FEATURE_NAMES[1:])
    return PairwiseRoleGroupV1(
        descriptor_ids=("desc-0000000000000001", "desc-0000000000000002"),
        e8_scores=(0.0, 0.0),
        features=(one, zero),
        labels=(True, False),
    )


def test_pairwise_features_exclude_e9_distribution_risk_fields() -> None:
    assert "e8_score" not in PAIRWISE_FEATURE_NAMES
    assert "candidate_count_log1p" not in PAIRWISE_FEATURE_NAMES


def test_pairwise_fit_prefers_positive_descriptor_and_bounds_adjustment() -> None:
    group = _group()
    fit = fit_pairwise_ridge_v1(
        (group,),
        l2_penalty=10.0,
        max_hard_negatives_per_positive=8,
    )

    assert fit.utility(group.features[0]) > fit.utility(group.features[1])
    _, high = fit.adjusted_score(
        e8_score=100.0,
        features=tuple(1e9 for _ in PAIRWISE_FEATURE_NAMES),
        residual_clip=1.0,
        max_adjustment=4.0,
    )
    _, low = fit.adjusted_score(
        e8_score=100.0,
        features=tuple(-1e9 for _ in PAIRWISE_FEATURE_NAMES),
        residual_clip=1.0,
        max_adjustment=4.0,
    )
    assert high == 4.0
    assert low == -4.0


def test_pairwise_artifact_rejects_coefficient_tampering() -> None:
    fit = fit_pairwise_ridge_v1(
        (_group(),),
        l2_penalty=10.0,
        max_hard_negatives_per_positive=8,
    )
    artifact = build_pairwise_residual_artifact_v1(
        fit=fit,
        protocol_sha256="a" * 64,
        training_split_sha256="b" * 64,
        retrieval_selection_sha256="c" * 64,
        l2_penalty=10.0,
        max_hard_negatives_per_positive=8,
        residual_clip=1.0,
        max_e8_score_adjustment=4.0,
        training_group_count=1,
    )
    payload = json.loads(artifact.model_dump_json())
    payload["coefficients"][0] += 1.0

    with pytest.raises(ValueError, match="artifact hash"):
        FinQAPairwiseResidualArtifactV1.model_validate(payload)


def test_pairwise_retriever_executes_with_hash_valid_artifact() -> None:
    fit = fit_pairwise_ridge_v1(
        (_group(),),
        l2_penalty=10.0,
        max_hard_negatives_per_positive=8,
    )
    artifact = build_pairwise_residual_artifact_v1(
        fit=fit,
        protocol_sha256="a" * 64,
        training_split_sha256="b" * 64,
        retrieval_selection_sha256="c" * 64,
        l2_penalty=10.0,
        max_hard_negatives_per_positive=8,
        residual_clip=1.0,
        max_e8_score_adjustment=4.0,
        training_group_count=1,
    )
    descriptors = tuple(
        RetrievableSafeCandidateDescriptorV3(
            descriptor_id=f"desc-{index:016x}",
            metric=metric,
            row_header=metric,
            column_header="2019",
            local_context_hint=f"{metric} in 2019",
            topic_hint="financial performance",
            periods=("2019",),
            source_kind="table_cell",
            candidate_count=1,
        )
        for index, metric in ((1, "net revenue"), (2, "total assets"))
    )
    catalog_payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": 2,
        "represented_candidate_count": 2,
        "quarantined_candidate_count": 0,
        "descriptor_count": 2,
        "descriptors": [item.model_dump(mode="json") for item in descriptors],
    }
    canonical = json.dumps(
        catalog_payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    catalog = RetrievableSafeDescriptorCatalogV3(
        **catalog_payload,
        catalog_sha256=hashlib.sha256(canonical).hexdigest(),
    )
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "comparison_left",
                    "period_role": "start",
                }
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"constant_id": "const_100"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )

    result = PairwiseResidualFinQADescriptorRetrieverV1(artifact).select(
        question="What was the change in net revenue from 2019 to 2020?",
        skeleton=skeleton,
        catalog=catalog,
    )

    assert result.generation_calls == 0
    assert len(result.rankings) == 1
    assert result.rankings[0].ranked_descriptors[0].score_reasons[1] == (
        "bounded_pairwise_residual"
    )
