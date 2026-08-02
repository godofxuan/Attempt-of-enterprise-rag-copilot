from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_descriptor_retriever_v1 import (
    DescriptorRankV1,
    DeterministicDescriptorRetrieverResultV1,
    RoleDescriptorRankingV1,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    FEATURE_NAMES,
    descriptor_feature_vector_v1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleSpecV2,
)


RANKER_VERSION = "finqa_pairwise_residual_ranker_v1"
ARTIFACT_SCHEMA_VERSION = "finqa_pairwise_residual_artifact_v1"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
MAX_ARTIFACT_BYTES = 1024 * 1024
_EPSILON = 1e-12
PAIRWISE_FEATURE_NAMES = tuple(
    name
    for name in FEATURE_NAMES
    if name not in {"e8_score", "candidate_count_log1p"}
)
_PAIRWISE_INDICES = tuple(FEATURE_NAMES.index(name) for name in PAIRWISE_FEATURE_NAMES)


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def pairwise_feature_vector_v1(
    question: str,
    role: SemanticRoleSpecV2,
    descriptor: RetrievableSafeCandidateDescriptorV3,
) -> tuple[float, ...]:
    full = descriptor_feature_vector_v1(question, role, descriptor)
    values = tuple(full[index] for index in _PAIRWISE_INDICES)
    if len(values) != len(PAIRWISE_FEATURE_NAMES):
        raise ValueError("E10 pairwise feature contract changed")
    return values


@dataclass(frozen=True)
class PairwiseRoleGroupV1:
    descriptor_ids: tuple[str, ...]
    e8_scores: tuple[float, ...]
    features: tuple[tuple[float, ...], ...]
    labels: tuple[bool, ...]

    def __post_init__(self) -> None:
        count = len(self.descriptor_ids)
        if (
            count == 0
            or len(self.e8_scores) != count
            or len(self.features) != count
            or len(self.labels) != count
            or len(set(self.descriptor_ids)) != count
            or not any(self.labels)
            or all(self.labels)
            or any(len(item) != len(PAIRWISE_FEATURE_NAMES) for item in self.features)
        ):
            raise ValueError("E10 pairwise role group is invalid")


@dataclass(frozen=True)
class PairwiseRidgeFitV1:
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    training_pair_count: int

    def utility(self, features: Sequence[float]) -> float:
        if len(features) != len(self.coefficients):
            raise ValueError("E10 pairwise feature count changed")
        result = sum(
            coefficient * ((float(value) - mean) / scale)
            for value, mean, scale, coefficient in zip(
                features,
                self.feature_means,
                self.feature_scales,
                self.coefficients,
                strict=True,
            )
        )
        if not math.isfinite(result):
            raise ValueError("E10 pairwise utility is not finite")
        return result

    def adjusted_score(
        self,
        *,
        e8_score: float,
        features: Sequence[float],
        residual_clip: float,
        max_adjustment: float,
    ) -> tuple[float, float]:
        if residual_clip <= 0 or max_adjustment <= 0:
            raise ValueError("E10 residual boundary is invalid")
        utility = self.utility(features)
        adjustment = (
            max(-residual_clip, min(residual_clip, utility))
            / residual_clip
            * max_adjustment
        )
        score = float(e8_score) + adjustment
        if not math.isfinite(score):
            raise ValueError("E10 adjusted score is not finite")
        return score, adjustment


def fit_pairwise_ridge_v1(
    groups: Sequence[PairwiseRoleGroupV1],
    *,
    l2_penalty: float,
    max_hard_negatives_per_positive: int,
) -> PairwiseRidgeFitV1:
    if (
        not groups
        or not math.isfinite(l2_penalty)
        or l2_penalty <= 0
        or max_hard_negatives_per_positive < 1
        or max_hard_negatives_per_positive > 64
    ):
        raise ValueError("E10 pairwise fit inputs are invalid")
    all_features = np.asarray(
        [feature for group in groups for feature in group.features],
        dtype=np.float64,
    )
    if (
        all_features.ndim != 2
        or all_features.shape[1] != len(PAIRWISE_FEATURE_NAMES)
        or not np.isfinite(all_features).all()
    ):
        raise ValueError("E10 pairwise feature matrix is invalid")
    means = all_features.mean(axis=0)
    scales = all_features.std(axis=0)
    scales = np.where(scales < _EPSILON, 1.0, scales)
    differences = []
    for group in groups:
        standardized = (
            np.asarray(group.features, dtype=np.float64) - means
        ) / scales
        negatives = sorted(
            (index for index, label in enumerate(group.labels) if not label),
            key=lambda index: (-group.e8_scores[index], group.descriptor_ids[index]),
        )[:max_hard_negatives_per_positive]
        for positive in (
            index for index, label in enumerate(group.labels) if label
        ):
            differences.extend(
                standardized[positive] - standardized[negative]
                for negative in negatives
            )
    matrix = np.asarray(differences, dtype=np.float64)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(PAIRWISE_FEATURE_NAMES)
        or len(matrix) < 1
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("E10 pairwise difference matrix is invalid")
    system = matrix.T @ matrix + np.eye(matrix.shape[1]) * l2_penalty
    rhs = matrix.T @ np.ones(len(matrix), dtype=np.float64)
    coefficients = np.linalg.solve(system, rhs)
    if not np.isfinite(coefficients).all():
        raise ValueError("E10 pairwise fit produced non-finite coefficients")
    return PairwiseRidgeFitV1(
        feature_means=tuple(float(value) for value in means),
        feature_scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        training_pair_count=len(matrix),
    )


class FinQAPairwiseResidualArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    ranker_version: str = RANKER_VERSION
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    l2_penalty: float = Field(gt=0)
    max_hard_negatives_per_positive: int = Field(ge=1, le=64)
    residual_clip: float = Field(gt=0)
    max_e8_score_adjustment: float = Field(gt=0)
    training_group_count: int = Field(ge=1)
    training_pair_count: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_artifact(self) -> FinQAPairwiseResidualArtifactV1:
        size = len(PAIRWISE_FEATURE_NAMES)
        if (
            self.feature_names != PAIRWISE_FEATURE_NAMES
            or len(self.feature_means) != size
            or len(self.feature_scales) != size
            or len(self.coefficients) != size
            or any(value <= 0 for value in self.feature_scales)
        ):
            raise ValueError("E10 pairwise artifact contract changed")
        payload = self.model_dump(mode="json", exclude={"artifact_sha256"})
        if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != (
            self.artifact_sha256
        ):
            raise ValueError("E10 pairwise artifact hash is invalid")
        return self

    def fit(self) -> PairwiseRidgeFitV1:
        return PairwiseRidgeFitV1(
            feature_means=self.feature_means,
            feature_scales=self.feature_scales,
            coefficients=self.coefficients,
            training_pair_count=self.training_pair_count,
        )


def build_pairwise_residual_artifact_v1(
    *,
    fit: PairwiseRidgeFitV1,
    protocol_sha256: str,
    training_split_sha256: str,
    retrieval_selection_sha256: str,
    l2_penalty: float,
    max_hard_negatives_per_positive: int,
    residual_clip: float,
    max_e8_score_adjustment: float,
    training_group_count: int,
) -> FinQAPairwiseResidualArtifactV1:
    payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "ranker_version": RANKER_VERSION,
        "protocol_sha256": protocol_sha256,
        "training_split_sha256": training_split_sha256,
        "retrieval_selection_sha256": retrieval_selection_sha256,
        "feature_names": PAIRWISE_FEATURE_NAMES,
        "feature_means": fit.feature_means,
        "feature_scales": fit.feature_scales,
        "coefficients": fit.coefficients,
        "l2_penalty": l2_penalty,
        "max_hard_negatives_per_positive": max_hard_negatives_per_positive,
        "residual_clip": residual_clip,
        "max_e8_score_adjustment": max_e8_score_adjustment,
        "training_group_count": training_group_count,
        "training_pair_count": fit.training_pair_count,
    }
    return FinQAPairwiseResidualArtifactV1(
        **payload,
        artifact_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )


def load_pairwise_residual_artifact_v1(
    path: Path,
) -> FinQAPairwiseResidualArtifactV1:
    content = path.resolve().read_bytes()
    if not content or len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError("E10 pairwise artifact is outside byte budget")
    return FinQAPairwiseResidualArtifactV1.model_validate_json(content)


class PairwiseResidualFinQADescriptorRetrieverV1:
    model = "pairwise-ridge-bounded-e8-residual-v1"

    def __init__(self, artifact: FinQAPairwiseResidualArtifactV1) -> None:
        self._artifact = artifact
        self._fit = artifact.fit()

    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> DeterministicDescriptorRetrieverResultV1:
        normalized = " ".join(question.split())
        if not normalized or len(normalized) > MAX_QUESTION_CHARS:
            raise ValueError("E10 pairwise question is outside budget")
        started = time.perf_counter()
        rankings = []
        selections = []
        for role in skeleton.roles:
            scored = []
            for descriptor in catalog.descriptors:
                full = descriptor_feature_vector_v1(normalized, role, descriptor)
                e8_score = full[FEATURE_NAMES.index("e8_score")]
                features = tuple(full[index] for index in _PAIRWISE_INDICES)
                score, adjustment = self._fit.adjusted_score(
                    e8_score=e8_score,
                    features=features,
                    residual_clip=self._artifact.residual_clip,
                    max_adjustment=self._artifact.max_e8_score_adjustment,
                )
                scored.append(
                    (
                        score,
                        e8_score,
                        descriptor.descriptor_id,
                        (
                            "e8_champion_score",
                            "bounded_pairwise_residual",
                            f"adjustment:{adjustment:.6f}",
                        ),
                    )
                )
            scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
            ranked = tuple(
                DescriptorRankV1(
                    descriptor_id=descriptor_id,
                    score=score,
                    score_reasons=reasons,
                )
                for score, _, descriptor_id, reasons in scored
            )
            rankings.append(
                RoleDescriptorRankingV1(
                    role_id=role.role_id,
                    ranked_descriptors=ranked,
                )
            )
            selections.append(
                RoleDescriptorSelectionV1(
                    role_id=role.role_id,
                    descriptor_ids=tuple(
                        item.descriptor_id
                        for item in ranked[:MAX_DESCRIPTOR_REFS_PER_ROLE]
                    ),
                )
            )
        return DeterministicDescriptorRetrieverResultV1(
            retriever_version=RANKER_VERSION,
            model=self.model,
            selections=DescriptorSelectionsV1(selections=tuple(selections)),
            rankings=tuple(rankings),
            generation_calls=0,
            latency_ms=(time.perf_counter() - started) * 1_000,
        )


__all__ = [
    "PAIRWISE_FEATURE_NAMES",
    "FinQAPairwiseResidualArtifactV1",
    "PairwiseResidualFinQADescriptorRetrieverV1",
    "PairwiseRidgeFitV1",
    "PairwiseRoleGroupV1",
    "build_pairwise_residual_artifact_v1",
    "fit_pairwise_ridge_v1",
    "load_pairwise_residual_artifact_v1",
    "pairwise_feature_vector_v1",
]
