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
from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PAIRWISE_FEATURE_NAMES,
    PairwiseRoleGroupV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    FinQATopKCandidateV1,
)


RANKER_VERSION = "finqa_top4_boundary_ranker_v1"
ARTIFACT_SCHEMA_VERSION = "finqa_top4_boundary_ranker_artifact_v1"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
MAX_ARTIFACT_BYTES = 1024 * 1024
_EPSILON = 1e-12
_PAIRWISE_INDICES = tuple(FEATURE_NAMES.index(name) for name in PAIRWISE_FEATURE_NAMES)


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@dataclass(frozen=True)
class TopKPairStatsV1:
    miss_group_count: int
    preservation_group_count: int
    redundant_hit_group_count: int
    pair_count: int
    effective_pair_weight: float


@dataclass(frozen=True)
class TopKWeightedRidgeFitV1:
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    pair_stats: TopKPairStatsV1

    def utility(self, features: Sequence[float]) -> float:
        if len(features) != len(self.coefficients):
            raise ValueError("E11 top-k feature count changed")
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
            raise ValueError("E11 top-k utility is not finite")
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
            raise ValueError("E11 residual boundary is invalid")
        utility = self.utility(features)
        adjustment = (
            max(-residual_clip, min(residual_clip, utility))
            / residual_clip
            * max_adjustment
        )
        score = float(e8_score) + adjustment
        if not math.isfinite(score):
            raise ValueError("E11 adjusted score is not finite")
        return score, adjustment


def _e8_order(group: PairwiseRoleGroupV1) -> tuple[int, ...]:
    return tuple(
        sorted(
            range(len(group.descriptor_ids)),
            key=lambda index: (
                -group.e8_scores[index],
                group.descriptor_ids[index],
            ),
        )
    )


def fit_topk_weighted_ridge_v1(
    groups: Sequence[PairwiseRoleGroupV1],
    *,
    config: FinQATopKCandidateV1,
    target_cutoff: int,
    boundary_negative_depth: int,
    miss_pair_weight: float,
) -> TopKWeightedRidgeFitV1:
    if (
        not groups
        or target_cutoff < 1
        or boundary_negative_depth < 1
        or not math.isfinite(miss_pair_weight)
        or miss_pair_weight <= 0
    ):
        raise ValueError("E11 top-k fit inputs are invalid")
    all_features = np.asarray(
        [feature for group in groups for feature in group.features],
        dtype=np.float64,
    )
    if (
        all_features.ndim != 2
        or all_features.shape[1] != len(PAIRWISE_FEATURE_NAMES)
        or not np.isfinite(all_features).all()
    ):
        raise ValueError("E11 top-k feature matrix is invalid")
    means = all_features.mean(axis=0)
    scales = all_features.std(axis=0)
    scales = np.where(scales < _EPSILON, 1.0, scales)

    differences = []
    weights = []
    miss_groups = 0
    preservation_groups = 0
    redundant_hits = 0
    for group in groups:
        standardized = (
            np.asarray(group.features, dtype=np.float64) - means
        ) / scales
        order = _e8_order(group)
        cutoff = min(target_cutoff, len(order))
        top = order[:cutoff]
        top_positives = tuple(index for index in top if group.labels[index])
        if not top_positives:
            target = next(index for index in order if group.labels[index])
            opponents = tuple(
                index for index in top if not group.labels[index]
            )[:boundary_negative_depth]
            group_weight = miss_pair_weight
            miss_groups += 1
        elif len(top_positives) == 1:
            target = top_positives[0]
            opponents = tuple(
                index
                for index in order[cutoff:]
                if not group.labels[index]
            )[:boundary_negative_depth]
            group_weight = config.preservation_weight
            preservation_groups += 1
        else:
            redundant_hits += 1
            continue
        if not opponents:
            continue
        pair_weight = group_weight / len(opponents)
        for opponent in opponents:
            differences.append(standardized[target] - standardized[opponent])
            weights.append(pair_weight)

    matrix = np.asarray(differences, dtype=np.float64)
    pair_weights = np.asarray(weights, dtype=np.float64)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(PAIRWISE_FEATURE_NAMES)
        or len(matrix) < 1
        or pair_weights.shape != (len(matrix),)
        or not np.isfinite(matrix).all()
        or not np.isfinite(pair_weights).all()
        or np.any(pair_weights <= 0)
    ):
        raise ValueError("E11 top-k pair matrix is invalid")
    weighted = matrix * pair_weights[:, None]
    system = matrix.T @ weighted + np.eye(matrix.shape[1]) * config.l2_penalty
    rhs = matrix.T @ pair_weights
    coefficients = np.linalg.solve(system, rhs)
    if not np.isfinite(coefficients).all():
        raise ValueError("E11 top-k fit produced non-finite coefficients")
    return TopKWeightedRidgeFitV1(
        feature_means=tuple(float(value) for value in means),
        feature_scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        pair_stats=TopKPairStatsV1(
            miss_group_count=miss_groups,
            preservation_group_count=preservation_groups,
            redundant_hit_group_count=redundant_hits,
            pair_count=len(matrix),
            effective_pair_weight=float(pair_weights.sum()),
        ),
    )


class FinQATopKRankerArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    ranker_version: str = RANKER_VERSION
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_config: FinQATopKCandidateV1
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    target_cutoff: int = Field(ge=1, le=16)
    boundary_negative_depth: int = Field(ge=1, le=16)
    miss_pair_weight: float = Field(gt=0)
    residual_clip: float = Field(gt=0)
    training_group_count: int = Field(ge=1)
    miss_group_count: int = Field(ge=1)
    preservation_group_count: int = Field(ge=0)
    redundant_hit_group_count: int = Field(ge=0)
    training_pair_count: int = Field(ge=1)
    effective_pair_weight: float = Field(gt=0)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_artifact(self) -> FinQATopKRankerArtifactV1:
        size = len(PAIRWISE_FEATURE_NAMES)
        if (
            self.feature_names != PAIRWISE_FEATURE_NAMES
            or len(self.feature_means) != size
            or len(self.feature_scales) != size
            or len(self.coefficients) != size
            or any(value <= 0 for value in self.feature_scales)
        ):
            raise ValueError("E11 top-k artifact contract changed")
        payload = self.model_dump(mode="json", exclude={"artifact_sha256"})
        if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != (
            self.artifact_sha256
        ):
            raise ValueError("E11 top-k artifact hash is invalid")
        return self

    def fit(self) -> TopKWeightedRidgeFitV1:
        return TopKWeightedRidgeFitV1(
            feature_means=self.feature_means,
            feature_scales=self.feature_scales,
            coefficients=self.coefficients,
            pair_stats=TopKPairStatsV1(
                miss_group_count=self.miss_group_count,
                preservation_group_count=self.preservation_group_count,
                redundant_hit_group_count=self.redundant_hit_group_count,
                pair_count=self.training_pair_count,
                effective_pair_weight=self.effective_pair_weight,
            ),
        )


def build_topk_ranker_artifact_v1(
    *,
    fit: TopKWeightedRidgeFitV1,
    protocol_sha256: str,
    training_split_sha256: str,
    retrieval_selection_sha256: str,
    selected_config: FinQATopKCandidateV1,
    target_cutoff: int,
    boundary_negative_depth: int,
    miss_pair_weight: float,
    residual_clip: float,
    training_group_count: int,
) -> FinQATopKRankerArtifactV1:
    payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "ranker_version": RANKER_VERSION,
        "protocol_sha256": protocol_sha256,
        "training_split_sha256": training_split_sha256,
        "retrieval_selection_sha256": retrieval_selection_sha256,
        "selected_config": selected_config.model_dump(mode="json"),
        "feature_names": PAIRWISE_FEATURE_NAMES,
        "feature_means": fit.feature_means,
        "feature_scales": fit.feature_scales,
        "coefficients": fit.coefficients,
        "target_cutoff": target_cutoff,
        "boundary_negative_depth": boundary_negative_depth,
        "miss_pair_weight": miss_pair_weight,
        "residual_clip": residual_clip,
        "training_group_count": training_group_count,
        "miss_group_count": fit.pair_stats.miss_group_count,
        "preservation_group_count": fit.pair_stats.preservation_group_count,
        "redundant_hit_group_count": fit.pair_stats.redundant_hit_group_count,
        "training_pair_count": fit.pair_stats.pair_count,
        "effective_pair_weight": fit.pair_stats.effective_pair_weight,
    }
    return FinQATopKRankerArtifactV1(
        **payload,
        artifact_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )


def load_topk_ranker_artifact_v1(path: Path) -> FinQATopKRankerArtifactV1:
    content = path.resolve().read_bytes()
    if not content or len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError("E11 top-k artifact is outside byte budget")
    return FinQATopKRankerArtifactV1.model_validate_json(content)


class TopKBoundaryFinQADescriptorRetrieverV1:
    model = "linear-top4-boundary-bounded-e8-residual-v1"

    def __init__(self, artifact: FinQATopKRankerArtifactV1) -> None:
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
            raise ValueError("E11 top-k question is outside budget")
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
                    max_adjustment=(
                        self._artifact.selected_config.max_e8_score_adjustment
                    ),
                )
                scored.append(
                    (
                        score,
                        e8_score,
                        descriptor.descriptor_id,
                        (
                            "e8_champion_score",
                            "top4_boundary_residual",
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
    "FinQATopKRankerArtifactV1",
    "TopKBoundaryFinQADescriptorRetrieverV1",
    "TopKPairStatsV1",
    "TopKWeightedRidgeFitV1",
    "build_topk_ranker_artifact_v1",
    "fit_topk_weighted_ridge_v1",
    "load_topk_ranker_artifact_v1",
]
