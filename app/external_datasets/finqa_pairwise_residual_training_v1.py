from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_learned_descriptor_ranker_v1 import (
    FEATURE_NAMES,
    descriptor_feature_vector_v1,
)
from app.external_datasets.finqa_learned_ranker_training_v1 import (
    finqa_company_id,
    normalize_empty_table_cells_v1,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_pairwise_residual_protocol_v1 import (
    FinQAPairwiseResidualProtocolV1,
)
from app.external_datasets.finqa_pairwise_residual_ranker_v1 import (
    PAIRWISE_FEATURE_NAMES,
    PairwiseRidgeFitV1,
    PairwiseRoleGroupV1,
    build_pairwise_residual_artifact_v1,
    fit_pairwise_ridge_v1,
)
from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    _source_bound_constant_ids,
    _target_retained,
    build_oracle_semantic_program_v2,
)
from app.external_datasets.finqa_safe_descriptor_catalog_v3 import (
    build_retrievable_safe_descriptor_catalog_v3,
)
from app.security.retrieved_content import RetrievedContentGuard


_PAIRWISE_INDICES = tuple(FEATURE_NAMES.index(name) for name in PAIRWISE_FEATURE_NAMES)


def top_retrieved_unit_ids_v1(
    text_rows: Sequence[object],
    table_rows: Sequence[object],
    *,
    limit: int,
) -> tuple[str, ...]:
    if limit < 1 or limit > 64:
        raise ValueError("E10 retrieval limit is invalid")
    ranked = []
    for row in (*text_rows, *table_rows):
        if (
            not isinstance(row, dict)
            or set(row) != {"score", "ind"}
            or not isinstance(row["ind"], str)
            or not row["ind"]
            or isinstance(row["score"], bool)
            or not isinstance(row["score"], (int, float))
            or not math.isfinite(float(row["score"]))
        ):
            raise ValueError("E10 upstream retrieval row is malformed")
        ranked.append((float(row["score"]), row["ind"]))
    ids = [unit_id for _, unit_id in ranked]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("E10 upstream retrieval IDs are invalid")
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(unit_id for _, unit_id in ranked[:limit])


@dataclass(frozen=True)
class PreparedPairwiseCaseV1:
    case_id: str
    company_id: str
    role_groups: tuple[PairwiseRoleGroupV1, ...]
    source_candidate_count: int
    descriptor_count: int
    normalized_empty_table_cell_count: int
    full_gold_evidence_covered: bool
    any_gold_evidence_covered: bool


def prepare_pairwise_training_case_v1(
    case: FinQACase,
    *,
    guard: RetrievedContentGuard,
    selected_unit_limit: int,
) -> PreparedPairwiseCaseV1:
    selected_ids = top_retrieved_unit_ids_v1(
        case.text_retrieved_all,
        case.table_retrieved_all,
        limit=selected_unit_limit,
    )
    extraction_case, normalized_empty_cells = normalize_empty_table_cells_v1(case)
    oracle = build_oracle_semantic_program_v2(
        question=case.qa.question,
        program=case.qa.program,
        source_bound_constant_ids=_source_bound_constant_ids(case),
    )
    if oracle.skeleton is None:
        raise ValueError("eligible E10 case did not produce a typed skeleton")
    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=selected_ids,
    )
    admission = admit_finqa_numeric_evidence_closure_v2(
        case,
        closure=closure,
        guard=guard,
    )
    admitted_ids = set(admission.admitted_unit_ids)
    candidates = tuple(
        candidate
        for candidate in extract_finqa_numeric_candidates_v2(
            extraction_case,
            admitted_evidence_ids=admitted_ids,
        ).candidates
        if candidate.role == "operand"
    )
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    context = {
        unit_id: units[unit_id].text for unit_id in admission.admitted_unit_ids
    }
    catalog_build = build_retrievable_safe_descriptor_catalog_v3(
        candidates=candidates,
        admitted_evidence_ids=admitted_ids,
        evidence_context_by_id=context,
        guard=guard,
    )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    target_by_role = {target.role_id: target for target in oracle.evidence_targets}
    groups = []
    for role in oracle.skeleton.roles:
        target = target_by_role[role.role_id]
        descriptor_ids = tuple(
            descriptor.descriptor_id for descriptor in catalog_build.catalog.descriptors
        )
        labels = tuple(
            any(
                _target_retained(target, (candidate_by_id[candidate_id],))
                for candidate_id in catalog_build.candidate_ids_by_descriptor[
                    descriptor_id
                ]
            )
            for descriptor_id in descriptor_ids
        )
        if not any(labels) or all(labels):
            continue
        full_features = tuple(
            descriptor_feature_vector_v1(case.qa.question, role, descriptor)
            for descriptor in catalog_build.catalog.descriptors
        )
        groups.append(
            PairwiseRoleGroupV1(
                descriptor_ids=descriptor_ids,
                e8_scores=tuple(
                    feature[FEATURE_NAMES.index("e8_score")]
                    for feature in full_features
                ),
                features=tuple(
                    tuple(feature[index] for index in _PAIRWISE_INDICES)
                    for feature in full_features
                ),
                labels=labels,
            )
        )
    gold_ids = set(case.qa.gold_inds)
    selected_set = set(selected_ids)
    return PreparedPairwiseCaseV1(
        case_id=case.id,
        company_id=finqa_company_id(case.filename),
        role_groups=tuple(groups),
        source_candidate_count=len(candidates),
        descriptor_count=catalog_build.catalog.descriptor_count,
        normalized_empty_table_cell_count=normalized_empty_cells,
        full_gold_evidence_covered=gold_ids.issubset(selected_set),
        any_gold_evidence_covered=bool(gold_ids & selected_set),
    )


@dataclass(frozen=True)
class PairwiseFoldMetricV1:
    fold_index: int
    case_count: int
    company_count: int
    role_count: int
    e8_descriptor_recall_at_4: float
    residual_descriptor_recall_at_4: float
    delta_at_4: float


@dataclass(frozen=True)
class PairwiseCrossValidationResultV1:
    folds: tuple[PairwiseFoldMetricV1, ...]
    e8_descriptor_recall_at_4: float
    residual_descriptor_recall_at_4: float
    residual_delta_at_4: float
    residual_fold_recall_stddev: float
    min_fold_coefficient_cosine_similarity: float
    fold_coefficients: tuple[tuple[float, ...], ...]


def _hit_at_4(
    group: PairwiseRoleGroupV1,
    *,
    fit: PairwiseRidgeFitV1 | None,
    residual_clip: float,
    max_adjustment: float,
) -> bool:
    if fit is None:
        scores = group.e8_scores
    else:
        scores = tuple(
            fit.adjusted_score(
                e8_score=e8_score,
                features=features,
                residual_clip=residual_clip,
                max_adjustment=max_adjustment,
            )[0]
            for e8_score, features in zip(
                group.e8_scores, group.features, strict=True
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


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def pairwise_grouped_cross_validate_v1(
    cases: Sequence[PreparedPairwiseCaseV1],
    *,
    company_folds: Mapping[str, int],
    fold_count: int,
    protocol: FinQAPairwiseResidualProtocolV1,
) -> PairwiseCrossValidationResultV1:
    if not cases or set(case.company_id for case in cases) - set(company_folds):
        raise ValueError("E10 cross-validation company assignment is incomplete")
    fold_metrics = []
    fold_coefficients = []
    total_e8_hits = 0
    total_residual_hits = 0
    total_roles = 0
    for fold_index in range(fold_count):
        train_groups = tuple(
            group
            for case in cases
            if company_folds[case.company_id] != fold_index
            for group in case.role_groups
        )
        held_cases = tuple(
            case
            for case in cases
            if company_folds[case.company_id] == fold_index
        )
        held_groups = tuple(group for case in held_cases for group in case.role_groups)
        fit = fit_pairwise_ridge_v1(
            train_groups,
            l2_penalty=protocol.model.l2_penalty,
            max_hard_negatives_per_positive=(
                protocol.model.max_hard_negatives_per_positive
            ),
        )
        e8_hits = sum(
            _hit_at_4(
                group,
                fit=None,
                residual_clip=protocol.model.residual_clip,
                max_adjustment=protocol.model.max_e8_score_adjustment,
            )
            for group in held_groups
        )
        residual_hits = sum(
            _hit_at_4(
                group,
                fit=fit,
                residual_clip=protocol.model.residual_clip,
                max_adjustment=protocol.model.max_e8_score_adjustment,
            )
            for group in held_groups
        )
        role_count = len(held_groups)
        if role_count == 0:
            raise ValueError("E10 cross-validation fold has no labelable roles")
        e8_recall = e8_hits / role_count
        residual_recall = residual_hits / role_count
        fold_metrics.append(
            PairwiseFoldMetricV1(
                fold_index=fold_index,
                case_count=len(held_cases),
                company_count=len({case.company_id for case in held_cases}),
                role_count=role_count,
                e8_descriptor_recall_at_4=e8_recall,
                residual_descriptor_recall_at_4=residual_recall,
                delta_at_4=residual_recall - e8_recall,
            )
        )
        fold_coefficients.append(fit.coefficients)
        total_e8_hits += e8_hits
        total_residual_hits += residual_hits
        total_roles += role_count
    cosine_values = tuple(
        _cosine(fold_coefficients[left], fold_coefficients[right])
        for left in range(fold_count)
        for right in range(left + 1, fold_count)
    )
    e8_recall = total_e8_hits / total_roles
    residual_recall = total_residual_hits / total_roles
    return PairwiseCrossValidationResultV1(
        folds=tuple(fold_metrics),
        e8_descriptor_recall_at_4=e8_recall,
        residual_descriptor_recall_at_4=residual_recall,
        residual_delta_at_4=residual_recall - e8_recall,
        residual_fold_recall_stddev=statistics.pstdev(
            item.residual_descriptor_recall_at_4 for item in fold_metrics
        ),
        min_fold_coefficient_cosine_similarity=min(cosine_values),
        fold_coefficients=tuple(fold_coefficients),
    )


def build_final_pairwise_artifact_v1(
    cases: Sequence[PreparedPairwiseCaseV1],
    *,
    protocol: FinQAPairwiseResidualProtocolV1,
    protocol_sha256: str,
):
    groups = tuple(group for case in cases for group in case.role_groups)
    fit = fit_pairwise_ridge_v1(
        groups,
        l2_penalty=protocol.model.l2_penalty,
        max_hard_negatives_per_positive=(
            protocol.model.max_hard_negatives_per_positive
        ),
    )
    return build_pairwise_residual_artifact_v1(
        fit=fit,
        protocol_sha256=protocol_sha256,
        training_split_sha256=protocol.training_boundary.train_split_sha256,
        retrieval_selection_sha256=(
            protocol.training_boundary.retrieval_selection_sha256
        ),
        l2_penalty=protocol.model.l2_penalty,
        max_hard_negatives_per_positive=(
            protocol.model.max_hard_negatives_per_positive
        ),
        residual_clip=protocol.model.residual_clip,
        max_e8_score_adjustment=protocol.model.max_e8_score_adjustment,
        training_group_count=len(groups),
    )


__all__ = [
    "PreparedPairwiseCaseV1",
    "build_final_pairwise_artifact_v1",
    "pairwise_grouped_cross_validate_v1",
    "prepare_pairwise_training_case_v1",
    "top_retrieved_unit_ids_v1",
]
