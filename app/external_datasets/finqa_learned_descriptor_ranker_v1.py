from __future__ import annotations

import hashlib
import json
import math
import re
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
from app.external_datasets.finqa_descriptor_retriever_v2 import (
    _financial_tokens,
    _role_anchor_tokens_v2,
)
from app.external_datasets.finqa_descriptor_retriever_v5 import (
    DeterministicFinQADescriptorRetrieverV5,
    _score_descriptor_v5,
)
from app.external_datasets.finqa_descriptor_selector_v1 import (
    DescriptorSelectionsV1,
    RoleDescriptorSelectionV1,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    RetrievableSafeCandidateDescriptorV3,
    RetrievableSafeDescriptorCatalogV3,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleSpecV2,
)


RANKER_VERSION = "finqa_learned_descriptor_ranker_v1"
ARTIFACT_SCHEMA_VERSION = "finqa_learned_descriptor_ranker_artifact_v1"
MAX_DESCRIPTOR_REFS_PER_ROLE = 4
MAX_QUESTION_CHARS = 2_000
MAX_ARTIFACT_BYTES = 1024 * 1024
_EPSILON = 1e-12
_PERIOD = re.compile(r"\b(?:19|20)\d{2}\b")

FEATURE_NAMES = (
    "e8_score",
    "question_primary_overlap_count",
    "question_primary_overlap_ratio",
    "anchor_primary_overlap_count",
    "anchor_primary_overlap_ratio",
    "question_local_overlap_count",
    "anchor_local_overlap_count",
    "question_topic_overlap_count",
    "anchor_topic_overlap_count",
    "question_period_overlap_count",
    "question_period_conflict",
    "exact_primary_phrase",
    "candidate_count_log1p",
    "metric_present",
    "entity_present",
    "row_header_present",
    "column_header_present",
    "local_hint_present",
    "topic_hint_present",
    "source_kind_table",
    "period_role_start",
    "period_role_end",
    "period_role_target",
)


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _primary_text(descriptor: RetrievableSafeCandidateDescriptorV3) -> str:
    return " ".join(
        value
        for value in (
            descriptor.metric,
            descriptor.entity,
            descriptor.row_header,
            descriptor.column_header,
        )
        if value
    )


def descriptor_feature_vector_v1(
    question: str,
    role: SemanticRoleSpecV2,
    descriptor: RetrievableSafeCandidateDescriptorV3,
) -> tuple[float, ...]:
    normalized_question = " ".join(question.casefold().split())
    if not normalized_question or len(normalized_question) > MAX_QUESTION_CHARS:
        raise ValueError("learned descriptor question is outside budget")
    question_tokens = _financial_tokens(normalized_question)
    anchor_tokens = _role_anchor_tokens_v2(
        normalized_question,
        role.semantic_role,
    )
    primary_tokens = _financial_tokens(_primary_text(descriptor))
    local_tokens = _financial_tokens(descriptor.local_context_hint)
    topic_tokens = _financial_tokens(descriptor.topic_hint)
    question_periods = frozenset(_PERIOD.findall(normalized_question))
    descriptor_periods = frozenset(descriptor.periods)
    e8_score, _ = _score_descriptor_v5(
        question=normalized_question,
        question_tokens=question_tokens,
        anchor_tokens=anchor_tokens,
        semantic_role=role.semantic_role,
        question_periods=question_periods,
        descriptor=descriptor,
    )
    question_primary = question_tokens & primary_tokens
    anchor_primary = anchor_tokens & primary_tokens
    exact_phrase = any(
        field is not None
        and len(_financial_tokens(field)) >= 2
        and field.casefold() in normalized_question
        for field in (
            descriptor.metric,
            descriptor.entity,
            descriptor.row_header,
            descriptor.column_header,
        )
    )
    values = (
        e8_score,
        float(len(question_primary)),
        len(question_primary) / max(1, len(primary_tokens)),
        float(len(anchor_primary)),
        len(anchor_primary) / max(1, len(anchor_tokens)),
        float(len(question_tokens & local_tokens)),
        float(len(anchor_tokens & local_tokens)),
        float(len(question_tokens & topic_tokens)),
        float(len(anchor_tokens & topic_tokens)),
        float(len(question_periods & descriptor_periods)),
        float(bool(question_periods and descriptor_periods and not (
            question_periods & descriptor_periods
        ))),
        float(exact_phrase),
        math.log1p(descriptor.candidate_count),
        float(descriptor.metric is not None),
        float(descriptor.entity is not None),
        float(descriptor.row_header is not None),
        float(descriptor.column_header is not None),
        float(descriptor.local_context_hint is not None),
        float(descriptor.topic_hint is not None),
        float(descriptor.source_kind.startswith("table")),
        float(role.period_role == "start"),
        float(role.period_role == "end"),
        float(role.period_role == "target"),
    )
    if len(values) != len(FEATURE_NAMES) or any(
        not math.isfinite(value) for value in values
    ):
        raise ValueError("learned descriptor features are invalid")
    return values


@dataclass(frozen=True)
class BalancedRidgeFitV1:
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float

    def score(self, features: Sequence[float]) -> float:
        if len(features) != len(self.coefficients):
            raise ValueError("learned descriptor feature count changed")
        standardized = (
            (float(value) - mean) / scale
            for value, mean, scale in zip(
                features,
                self.feature_means,
                self.feature_scales,
                strict=True,
            )
        )
        result = self.intercept + sum(
            coefficient * value
            for coefficient, value in zip(
                self.coefficients,
                standardized,
                strict=True,
            )
        )
        if not math.isfinite(result):
            raise ValueError("learned descriptor score is not finite")
        return result


def fit_balanced_ridge_v1(
    features: Sequence[Sequence[float]],
    labels: Sequence[bool],
    *,
    l2_penalty: float,
) -> BalancedRidgeFitV1:
    if (
        not features
        or len(features) != len(labels)
        or len(features) > 2_000_000
        or not math.isfinite(l2_penalty)
        or l2_penalty <= 0
    ):
        raise ValueError("learned descriptor training inputs are invalid")
    matrix = np.asarray(features, dtype=np.float64)
    target = np.asarray(labels, dtype=np.float64)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(FEATURE_NAMES)
        or not np.isfinite(matrix).all()
        or not np.isin(target, (0.0, 1.0)).all()
    ):
        raise ValueError("learned descriptor training matrix is invalid")
    positive_count = int(target.sum())
    negative_count = len(target) - positive_count
    if positive_count == 0 or negative_count == 0:
        raise ValueError("learned descriptor training requires both classes")
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales = np.where(scales < _EPSILON, 1.0, scales)
    standardized = (matrix - means) / scales
    design = np.column_stack((np.ones(len(target)), standardized))
    weights = np.where(
        target == 1.0,
        len(target) / (2.0 * positive_count),
        len(target) / (2.0 * negative_count),
    )
    weighted_design = design * weights[:, None]
    regularizer = np.diag((0.0,) + (l2_penalty,) * len(FEATURE_NAMES))
    system = design.T @ weighted_design + regularizer
    rhs = design.T @ (weights * target)
    solved = np.linalg.solve(system, rhs)
    values = np.concatenate((means, scales, solved))
    if not np.isfinite(values).all():
        raise ValueError("learned descriptor fit produced non-finite values")
    return BalancedRidgeFitV1(
        feature_means=tuple(float(value) for value in means),
        feature_scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in solved[1:]),
        intercept=float(solved[0]),
    )


class FinQALearnedDescriptorRankerArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    ranker_version: str = RANKER_VERSION
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_family: str = "balanced_l2_ridge_pointwise_ranker_v1"
    l2_penalty: float = Field(gt=0)
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    training_example_count: int = Field(ge=2)
    positive_example_count: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_artifact(self) -> FinQALearnedDescriptorRankerArtifactV1:
        size = len(FEATURE_NAMES)
        if (
            self.feature_names != FEATURE_NAMES
            or len(self.feature_means) != size
            or len(self.feature_scales) != size
            or len(self.coefficients) != size
            or any(value <= 0 for value in self.feature_scales)
            or self.positive_example_count >= self.training_example_count
        ):
            raise ValueError("learned descriptor artifact contract changed")
        payload = self.model_dump(mode="json", exclude={"artifact_sha256"})
        if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != (
            self.artifact_sha256
        ):
            raise ValueError("learned descriptor artifact hash is invalid")
        return self

    def fit(self) -> BalancedRidgeFitV1:
        return BalancedRidgeFitV1(
            feature_means=self.feature_means,
            feature_scales=self.feature_scales,
            coefficients=self.coefficients,
            intercept=self.intercept,
        )


def build_learned_descriptor_ranker_artifact_v1(
    *,
    fit: BalancedRidgeFitV1,
    protocol_sha256: str,
    training_split_sha256: str,
    eligible_case_ids_sha256: str,
    training_example_count: int,
    positive_example_count: int,
    l2_penalty: float = 10.0,
) -> FinQALearnedDescriptorRankerArtifactV1:
    payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "ranker_version": RANKER_VERSION,
        "protocol_sha256": protocol_sha256,
        "training_split_sha256": training_split_sha256,
        "eligible_case_ids_sha256": eligible_case_ids_sha256,
        "model_family": "balanced_l2_ridge_pointwise_ranker_v1",
        "l2_penalty": l2_penalty,
        "feature_names": FEATURE_NAMES,
        "feature_means": fit.feature_means,
        "feature_scales": fit.feature_scales,
        "coefficients": fit.coefficients,
        "intercept": fit.intercept,
        "training_example_count": training_example_count,
        "positive_example_count": positive_example_count,
    }
    return FinQALearnedDescriptorRankerArtifactV1(
        **payload,
        artifact_sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    )


def load_learned_descriptor_ranker_artifact_v1(
    path: Path,
) -> FinQALearnedDescriptorRankerArtifactV1:
    content = path.resolve().read_bytes()
    if not content or len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError("learned descriptor artifact is outside byte budget")
    return FinQALearnedDescriptorRankerArtifactV1.model_validate_json(content)


class LearnedFinQADescriptorRetrieverV1:
    model = "balanced-l2-ridge-descriptor-ranker-v1"

    def __init__(self, artifact: FinQALearnedDescriptorRankerArtifactV1) -> None:
        self._artifact = artifact
        self._fit = artifact.fit()

    def select(
        self,
        *,
        question: str,
        skeleton: SemanticProgramSkeletonV2,
        catalog: RetrievableSafeDescriptorCatalogV3,
    ) -> DeterministicDescriptorRetrieverResultV1:
        normalized_question = " ".join(question.split())
        if not normalized_question or len(normalized_question) > MAX_QUESTION_CHARS:
            raise ValueError("learned descriptor question is outside budget")
        started = time.perf_counter()
        rankings = []
        selections = []
        for role in skeleton.roles:
            scored = []
            for descriptor in catalog.descriptors:
                features = descriptor_feature_vector_v1(
                    normalized_question,
                    role,
                    descriptor,
                )
                score = self._fit.score(features)
                e8_score = features[0]
                standardized = tuple(
                    (value - mean) / scale
                    for value, mean, scale in zip(
                        features,
                        self._fit.feature_means,
                        self._fit.feature_scales,
                        strict=True,
                    )
                )
                contributions = sorted(
                    (
                        (abs(coefficient * value), name)
                        for name, coefficient, value in zip(
                            FEATURE_NAMES,
                            self._fit.coefficients,
                            standardized,
                            strict=True,
                        )
                        if coefficient and value
                    ),
                    key=lambda item: (-item[0], item[1]),
                )
                reasons = ("learned_linear_score",) + tuple(
                    f"feature:{name}" for _, name in contributions[:3]
                )
                scored.append((score, e8_score, descriptor.descriptor_id, reasons))
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


class FailClosedFinQADescriptorRetrieverV1:
    def __init__(
        self,
        challenger: LearnedFinQADescriptorRetrieverV1 | None,
    ) -> None:
        self._challenger = challenger
        self._champion = DeterministicFinQADescriptorRetrieverV5()

    def select(self, **kwargs: object) -> DeterministicDescriptorRetrieverResultV1:
        if self._challenger is not None:
            try:
                return self._challenger.select(**kwargs)
            except (ArithmeticError, TypeError, ValueError):
                pass
        return self._champion.select(**kwargs)


__all__ = [
    "FEATURE_NAMES",
    "FailClosedFinQADescriptorRetrieverV1",
    "FinQALearnedDescriptorRankerArtifactV1",
    "LearnedFinQADescriptorRetrieverV1",
    "RANKER_VERSION",
    "build_learned_descriptor_ranker_artifact_v1",
    "descriptor_feature_vector_v1",
    "fit_balanced_ridge_v1",
    "load_learned_descriptor_ranker_artifact_v1",
]
