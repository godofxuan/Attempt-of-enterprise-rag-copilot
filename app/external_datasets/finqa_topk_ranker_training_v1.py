from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PairwiseRoleGroupV1,
)
from app.external_datasets.finqa_pairwise_residual_training_v1 import (
    PreparedPairwiseCaseV1,
)
from app.external_datasets.finqa_topk_ranker_protocol_v1 import (
    FinQATopKCandidateV1,
    FinQATopKRankerProtocolV1,
)
from app.external_datasets.finqa_topk_ranker_v1 import (
    TopKWeightedRidgeFitV1,
    build_topk_ranker_artifact_v1,
    fit_topk_weighted_ridge_v1,
)


@dataclass(frozen=True)
class TopKEvaluationV1:
    role_count: int
    e8_hits: int
    challenger_hits: int
    retained: int
    regressed: int
    gained: int
    missed_both: int

    @property
    def e8_recall_at_4(self) -> float:
        return self.e8_hits / self.role_count

    @property
    def challenger_recall_at_4(self) -> float:
        return self.challenger_hits / self.role_count

    @property
    def delta_at_4(self) -> float:
        return self.challenger_recall_at_4 - self.e8_recall_at_4


@dataclass(frozen=True)
class TopKInnerCandidateMetricV1:
    config_id: str
    role_count: int
    e8_hits: int
    challenger_hits: int
    regressed: int
    gained: int
    fold_deltas_at_4: tuple[float, ...]


@dataclass(frozen=True)
class TopKOuterSelectionV1:
    outer_fold_index: int
    selected_config_id: str
    candidate_metrics: tuple[TopKInnerCandidateMetricV1, ...]


@dataclass(frozen=True)
class TopKOuterFoldMetricV1:
    fold_index: int
    case_count: int
    company_count: int
    role_count: int
    selected_config_id: str
    e8_descriptor_recall_at_4: float
    challenger_descriptor_recall_at_4: float
    delta_at_4: float
    retained: int
    regressed: int
    gained: int
    missed_both: int


@dataclass(frozen=True)
class TopKNestedCVResultV1:
    outer_folds: tuple[TopKOuterFoldMetricV1, ...]
    outer_selections: tuple[TopKOuterSelectionV1, ...]
    e8_descriptor_recall_at_4: float
    challenger_descriptor_recall_at_4: float
    challenger_delta_at_4: float
    challenger_fold_recall_stddev: float
    min_outer_fold_coefficient_cosine_similarity: float
    retained: int
    regressed: int
    gained: int
    missed_both: int
    selected_config_counts: dict[str, int]
    final_config_id: str
    outer_coefficients: tuple[tuple[float, ...], ...]


def _hit_at_4(
    group: PairwiseRoleGroupV1,
    *,
    fit: TopKWeightedRidgeFitV1 | None,
    config: FinQATopKCandidateV1,
    residual_clip: float,
) -> bool:
    if fit is None:
        scores = group.e8_scores
    else:
        scores = tuple(
            fit.adjusted_score(
                e8_score=e8_score,
                features=features,
                residual_clip=residual_clip,
                max_adjustment=config.max_e8_score_adjustment,
            )[0]
            for e8_score, features in zip(
                group.e8_scores,
                group.features,
                strict=True,
            )
        )
    ranked = sorted(
        range(len(group.descriptor_ids)),
        key=lambda index: (
            -scores[index],
            -group.e8_scores[index],
            group.descriptor_ids[index],
        ),
    )
    return any(group.labels[index] for index in ranked[:4])


def evaluate_topk_groups_v1(
    groups: Sequence[PairwiseRoleGroupV1],
    *,
    fit: TopKWeightedRidgeFitV1,
    config: FinQATopKCandidateV1,
    residual_clip: float,
) -> TopKEvaluationV1:
    if not groups:
        raise ValueError("E11 evaluation has no role groups")
    retained = 0
    regressed = 0
    gained = 0
    missed_both = 0
    for group in groups:
        e8_hit = _hit_at_4(
            group,
            fit=None,
            config=config,
            residual_clip=residual_clip,
        )
        challenger_hit = _hit_at_4(
            group,
            fit=fit,
            config=config,
            residual_clip=residual_clip,
        )
        if e8_hit and challenger_hit:
            retained += 1
        elif e8_hit:
            regressed += 1
        elif challenger_hit:
            gained += 1
        else:
            missed_both += 1
    role_count = len(groups)
    return TopKEvaluationV1(
        role_count=role_count,
        e8_hits=retained + regressed,
        challenger_hits=retained + gained,
        retained=retained,
        regressed=regressed,
        gained=gained,
        missed_both=missed_both,
    )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def nested_company_cross_validate_v1(
    cases: Sequence[PreparedPairwiseCaseV1],
    *,
    company_folds: Mapping[str, int],
    protocol: FinQATopKRankerProtocolV1,
) -> TopKNestedCVResultV1:
    if not cases or set(case.company_id for case in cases) - set(company_folds):
        raise ValueError("E11 company assignment is incomplete")
    fold_count = len(protocol.folds)
    candidates = protocol.model.candidate_configs
    fold_cases = {
        fold_index: tuple(
            case
            for case in cases
            if company_folds[case.company_id] == fold_index
        )
        for fold_index in range(fold_count)
    }
    outer_metrics = []
    outer_selections = []
    outer_coefficients = []
    total = Counter()
    selected_ids = []
    for outer_index in range(fold_count):
        inner_indices = tuple(
            index for index in range(fold_count) if index != outer_index
        )
        candidate_metrics = []
        for candidate in candidates:
            role_count = 0
            e8_hits = 0
            challenger_hits = 0
            regressed = 0
            gained = 0
            fold_deltas = []
            for inner_index in inner_indices:
                train_groups = tuple(
                    group
                    for fold_index in inner_indices
                    if fold_index != inner_index
                    for case in fold_cases[fold_index]
                    for group in case.role_groups
                )
                held_groups = tuple(
                    group
                    for case in fold_cases[inner_index]
                    for group in case.role_groups
                )
                fit = fit_topk_weighted_ridge_v1(
                    train_groups,
                    config=candidate,
                    target_cutoff=protocol.model.target_cutoff,
                    boundary_negative_depth=protocol.model.boundary_negative_depth,
                    miss_pair_weight=protocol.model.miss_pair_weight,
                )
                result = evaluate_topk_groups_v1(
                    held_groups,
                    fit=fit,
                    config=candidate,
                    residual_clip=protocol.model.residual_clip,
                )
                role_count += result.role_count
                e8_hits += result.e8_hits
                challenger_hits += result.challenger_hits
                regressed += result.regressed
                gained += result.gained
                fold_deltas.append(result.delta_at_4)
            candidate_metrics.append(
                TopKInnerCandidateMetricV1(
                    config_id=candidate.config_id,
                    role_count=role_count,
                    e8_hits=e8_hits,
                    challenger_hits=challenger_hits,
                    regressed=regressed,
                    gained=gained,
                    fold_deltas_at_4=tuple(fold_deltas),
                )
            )
        selected_position = max(
            range(len(candidates)),
            key=lambda index: (
                candidate_metrics[index].challenger_hits,
                -candidate_metrics[index].regressed,
                -index,
            ),
        )
        selected = candidates[selected_position]
        selected_ids.append(selected.config_id)
        outer_selections.append(
            TopKOuterSelectionV1(
                outer_fold_index=outer_index,
                selected_config_id=selected.config_id,
                candidate_metrics=tuple(candidate_metrics),
            )
        )
        outer_train_groups = tuple(
            group
            for fold_index in range(fold_count)
            if fold_index != outer_index
            for case in fold_cases[fold_index]
            for group in case.role_groups
        )
        outer_held_cases = fold_cases[outer_index]
        outer_held_groups = tuple(
            group for case in outer_held_cases for group in case.role_groups
        )
        fit = fit_topk_weighted_ridge_v1(
            outer_train_groups,
            config=selected,
            target_cutoff=protocol.model.target_cutoff,
            boundary_negative_depth=protocol.model.boundary_negative_depth,
            miss_pair_weight=protocol.model.miss_pair_weight,
        )
        result = evaluate_topk_groups_v1(
            outer_held_groups,
            fit=fit,
            config=selected,
            residual_clip=protocol.model.residual_clip,
        )
        outer_metrics.append(
            TopKOuterFoldMetricV1(
                fold_index=outer_index,
                case_count=len(outer_held_cases),
                company_count=len(
                    {case.company_id for case in outer_held_cases}
                ),
                role_count=result.role_count,
                selected_config_id=selected.config_id,
                e8_descriptor_recall_at_4=result.e8_recall_at_4,
                challenger_descriptor_recall_at_4=(
                    result.challenger_recall_at_4
                ),
                delta_at_4=result.delta_at_4,
                retained=result.retained,
                regressed=result.regressed,
                gained=result.gained,
                missed_both=result.missed_both,
            )
        )
        outer_coefficients.append(fit.coefficients)
        total.update(
            {
                "roles": result.role_count,
                "e8_hits": result.e8_hits,
                "challenger_hits": result.challenger_hits,
                "retained": result.retained,
                "regressed": result.regressed,
                "gained": result.gained,
                "missed_both": result.missed_both,
            }
        )
    selection_counts = Counter(selected_ids)
    final_position = min(
        range(len(candidates)),
        key=lambda index: (-selection_counts[candidates[index].config_id], index),
    )
    cosine_values = tuple(
        _cosine(outer_coefficients[left], outer_coefficients[right])
        for left in range(fold_count)
        for right in range(left + 1, fold_count)
    )
    e8_recall = total["e8_hits"] / total["roles"]
    challenger_recall = total["challenger_hits"] / total["roles"]
    return TopKNestedCVResultV1(
        outer_folds=tuple(outer_metrics),
        outer_selections=tuple(outer_selections),
        e8_descriptor_recall_at_4=e8_recall,
        challenger_descriptor_recall_at_4=challenger_recall,
        challenger_delta_at_4=challenger_recall - e8_recall,
        challenger_fold_recall_stddev=statistics.pstdev(
            item.challenger_descriptor_recall_at_4 for item in outer_metrics
        ),
        min_outer_fold_coefficient_cosine_similarity=min(cosine_values),
        retained=total["retained"],
        regressed=total["regressed"],
        gained=total["gained"],
        missed_both=total["missed_both"],
        selected_config_counts=dict(sorted(selection_counts.items())),
        final_config_id=candidates[final_position].config_id,
        outer_coefficients=tuple(outer_coefficients),
    )


def build_final_topk_artifact_v1(
    cases: Sequence[PreparedPairwiseCaseV1],
    *,
    protocol: FinQATopKRankerProtocolV1,
    protocol_sha256: str,
    final_config_id: str,
):
    configs = {
        candidate.config_id: candidate
        for candidate in protocol.model.candidate_configs
    }
    if final_config_id not in configs:
        raise ValueError("E11 final configuration is not frozen")
    groups = tuple(group for case in cases for group in case.role_groups)
    fit = fit_topk_weighted_ridge_v1(
        groups,
        config=configs[final_config_id],
        target_cutoff=protocol.model.target_cutoff,
        boundary_negative_depth=protocol.model.boundary_negative_depth,
        miss_pair_weight=protocol.model.miss_pair_weight,
    )
    return build_topk_ranker_artifact_v1(
        fit=fit,
        protocol_sha256=protocol_sha256,
        training_split_sha256=protocol.training_boundary.train_split_sha256,
        retrieval_selection_sha256=(
            protocol.training_boundary.retrieval_selection_sha256
        ),
        selected_config=configs[final_config_id],
        target_cutoff=protocol.model.target_cutoff,
        boundary_negative_depth=protocol.model.boundary_negative_depth,
        miss_pair_weight=protocol.model.miss_pair_weight,
        residual_clip=protocol.model.residual_clip,
        training_group_count=len(groups),
    )


__all__ = [
    "TopKEvaluationV1",
    "TopKNestedCVResultV1",
    "build_final_topk_artifact_v1",
    "evaluate_topk_groups_v1",
    "nested_company_cross_validate_v1",
]
