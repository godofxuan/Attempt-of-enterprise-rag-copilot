from __future__ import annotations

import json

import pytest

from app.external_datasets.finqa_descriptor_retriever_v5 import (
    DeterministicFinQADescriptorRetrieverV5,
)
from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    FEATURE_NAMES,
    FailClosedFinQADescriptorRetrieverV1,
    FinQALearnedDescriptorRankerArtifactV1,
    LearnedFinQADescriptorRetrieverV1,
    build_learned_descriptor_ranker_artifact_v1,
    descriptor_feature_vector_v1,
    fit_balanced_ridge_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
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


def _descriptor(
    descriptor_id: str,
    *,
    metric: str,
    year: str,
) -> RetrievableSafeCandidateDescriptorV3:
    return RetrievableSafeCandidateDescriptorV3(
        descriptor_id=descriptor_id,
        metric=metric,
        row_header=metric,
        column_header=year,
        local_context_hint=f"{metric} for fiscal year {year}",
        topic_hint="annual financial performance",
        periods=(year,),
        source_kind="table_cell",
        candidate_count=1,
    )


def _catalog(
    descriptors: tuple[RetrievableSafeCandidateDescriptorV3, ...],
) -> RetrievableSafeDescriptorCatalogV3:
    ordered = tuple(sorted(descriptors, key=lambda item: item.descriptor_id))
    payload = {
        "catalog_version": "finqa_safe_descriptor_catalog_v3",
        "source_candidate_count": len(ordered),
        "represented_candidate_count": len(ordered),
        "quarantined_candidate_count": 0,
        "descriptor_count": len(ordered),
        "descriptors": [item.model_dump(mode="json") for item in ordered],
    }
    import hashlib

    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return RetrievableSafeDescriptorCatalogV3(
        **payload,
        catalog_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def test_descriptor_features_do_not_depend_on_ids_or_numeric_values() -> None:
    left = _descriptor("desc-0000000000000001", metric="net revenue", year="2019")
    right = left.model_copy(update={"descriptor_id": "desc-0000000000000002"})
    question = "What was the change in net revenue from 2019 to 2020?"
    role = _skeleton().roles[0]

    assert descriptor_feature_vector_v1(question, role, left) == (
        descriptor_feature_vector_v1(question, role, right)
    )
    assert not {
        "case_id",
        "company_id",
        "gold_program",
        "numeric_value",
    }.intersection(FEATURE_NAMES)


def test_balanced_ridge_fit_is_deterministic_and_finite() -> None:
    negative = tuple(0.0 for _ in FEATURE_NAMES)
    positive = (1.0,) + tuple(0.0 for _ in FEATURE_NAMES[1:])
    features = (negative, positive, negative, positive)
    labels = (False, True, False, True)

    first = fit_balanced_ridge_v1(features, labels, l2_penalty=10.0)
    second = fit_balanced_ridge_v1(features, labels, l2_penalty=10.0)

    assert first == second
    assert first.score(positive) > first.score(negative)


def test_artifact_hash_rejects_tampering() -> None:
    fit = fit_balanced_ridge_v1(
        (
            tuple(0.0 for _ in FEATURE_NAMES),
            tuple(1.0 for _ in FEATURE_NAMES),
        ),
        (False, True),
        l2_penalty=10.0,
    )
    artifact = build_learned_descriptor_ranker_artifact_v1(
        fit=fit,
        protocol_sha256="a" * 64,
        training_split_sha256="b" * 64,
        eligible_case_ids_sha256="c" * 64,
        training_example_count=2,
        positive_example_count=1,
    )
    payload = artifact.model_dump(mode="json")
    payload["coefficients"][0] += 1.0

    with pytest.raises(ValueError, match="artifact hash"):
        FinQALearnedDescriptorRankerArtifactV1.model_validate(payload)


def test_learned_retriever_is_catalog_order_invariant() -> None:
    revenue = _descriptor(
        "desc-0000000000000001", metric="net revenue", year="2019"
    )
    assets = _descriptor(
        "desc-0000000000000002", metric="total assets", year="2019"
    )
    question = "What was the change in net revenue from 2019 to 2020?"
    role = _skeleton().roles[0]
    revenue_features = descriptor_feature_vector_v1(question, role, revenue)
    assets_features = descriptor_feature_vector_v1(question, role, assets)
    fit = fit_balanced_ridge_v1(
        (revenue_features, assets_features),
        (True, False),
        l2_penalty=10.0,
    )
    artifact = build_learned_descriptor_ranker_artifact_v1(
        fit=fit,
        protocol_sha256="a" * 64,
        training_split_sha256="b" * 64,
        eligible_case_ids_sha256="c" * 64,
        training_example_count=2,
        positive_example_count=1,
    )
    retriever = LearnedFinQADescriptorRetrieverV1(artifact)
    forward = _catalog((revenue, assets))
    reverse_payload = forward.model_dump()
    reverse_payload["descriptors"] = tuple(reversed(forward.descriptors))
    reverse_payload["descriptors"] = tuple(
        sorted(reverse_payload["descriptors"], key=lambda item: item.descriptor_id)
    )
    reverse = RetrievableSafeDescriptorCatalogV3.model_validate(reverse_payload)

    first = retriever.select(question=question, skeleton=_skeleton(), catalog=forward)
    second = retriever.select(question=question, skeleton=_skeleton(), catalog=reverse)

    assert first.selections == second.selections
    assert first.rankings == second.rankings
    assert first.selections.selections[0].descriptor_ids[0] == revenue.descriptor_id


def test_missing_challenger_falls_back_to_e8_champion() -> None:
    catalog = _catalog(
        (
            _descriptor(
                "desc-0000000000000001", metric="net revenue", year="2019"
            ),
            _descriptor(
                "desc-0000000000000002", metric="total assets", year="2019"
            ),
        )
    )
    kwargs = {
        "question": "What was the change in net revenue from 2019 to 2020?",
        "skeleton": _skeleton(),
        "catalog": catalog,
    }

    fallback = FailClosedFinQADescriptorRetrieverV1(None).select(**kwargs)
    champion = DeterministicFinQADescriptorRetrieverV5().select(**kwargs)

    assert fallback.selections == champion.selections
    assert fallback.rankings == champion.rankings
    assert fallback.model == champion.model
