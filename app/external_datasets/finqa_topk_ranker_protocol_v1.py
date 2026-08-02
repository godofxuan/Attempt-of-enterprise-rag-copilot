from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQATopKFoldV1(_StrictFrozenModel):
    fold_index: int = Field(ge=0, le=4)
    case_count: int = Field(ge=1)
    company_count: int = Field(ge=1)
    company_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinQATopKTrainingBoundaryV1(_StrictFrozenModel):
    train_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_case_count: Literal[3068] = 3068
    eligible_company_count: Literal[99] = 99
    eligible_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_source: Literal[
        "finqa_retrieved_all_score_sorted_top10_or_all_without_gold_injection"
    ]
    retrieval_selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_selected_units_per_case: Literal[10] = 10
    min_selected_units_observed: Literal[6] = 6
    prior_train_oof_reuse: Literal[
        "DISCLOSED_DESIGN_REUSE_NOT_INDEPENDENT_CONFIRMATION"
    ]


class FinQATopKCandidateV1(_StrictFrozenModel):
    config_id: str = Field(pattern=r"^adj(?:02|04|08)-l2-(?:001|010|100)-p(?:025|100)$")
    max_e8_score_adjustment: Literal[2.0, 4.0, 8.0]
    l2_penalty: Literal[1.0, 10.0, 100.0]
    preservation_weight: Literal[0.25, 1.0]


class FinQATopKModelContractV1(_StrictFrozenModel):
    model_family: Literal["linear_top4_swap_weighted_ridge_v1"]
    implementation: Literal["numpy_closed_form_weighted_pairwise_solve"]
    target_cutoff: Literal[4] = 4
    boundary_negative_depth: Literal[4] = 4
    miss_pair_weight: Literal[1.0] = 1.0
    residual_clip: Literal[1.0] = 1.0
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=64)
    prohibited_features: tuple[str, ...] = Field(min_length=1)
    candidate_configs: tuple[FinQATopKCandidateV1, ...] = Field(
        min_length=18,
        max_length=18,
    )
    inner_selection_metric: Literal[
        "descriptor_recall_at_4_desc_then_regressions_asc_then_safety_order"
    ]
    final_config_rule: Literal[
        "outer_selection_frequency_desc_then_candidate_order"
    ]
    tie_break_rule: Literal[
        "bounded_residual_score_desc_then_e8_score_desc_then_descriptor_id_asc"
    ]
    dependency_boundary: Literal["numpy_only_no_new_ml_dependency"]


class FinQATopKCVGatesV1(_StrictFrozenModel):
    min_preparation_success_rate: Literal[0.90] = 0.90
    min_labelable_case_rate: Literal[0.90] = 0.90
    min_outer_oof_descriptor_recall_delta_at_4: Literal[0.01] = 0.01
    max_outer_fold_descriptor_recall_stddev: Literal[0.05] = 0.05
    require_no_regressed_outer_fold: Literal[True] = True
    min_outer_fold_coefficient_cosine_similarity: Literal[0.60] = 0.60
    require_nested_company_disjoint_selection: Literal[True] = True
    require_zero_feature_label_leakage: Literal[True] = True
    require_zero_model_calls: Literal[True] = True


class FinQATopKInternalBoundaryV1(_StrictFrozenModel):
    case_count: Literal[40] = 40
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_private_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_retrospective_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_units_per_case: Literal[10] = 10
    evaluation_budget: Literal[1] = 1
    status: Literal["NOT_RUN"]


class FinQATopKInternalGatesV1(_StrictFrozenModel):
    min_descriptor_recall_delta_at_4: Literal[0.0] = 0.0
    min_descriptor_complete_case_delta_at_4: Literal[0.0] = 0.0
    min_candidate_recall_delta_at_8: Literal[0.0] = 0.0
    min_candidate_complete_case_delta_at_8: Literal[0.0] = 0.0
    min_conditional_retention_delta_at_8: Literal[-0.01] = -0.01
    require_zero_model_calls: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_guard_scan_before_projection: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQATopKRankerProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_topk_ranker_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E11_NESTED_CV_OUTCOME"]
    claim_label: Literal[
        "TRAIN_DEVELOPMENT_NESTED_CV_THEN_SINGLE_INTERNAL_VALIDATION"
    ]
    source_e10_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e10_cv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e10_artifact_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e10_postmortem_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e10_erratum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_boundary: FinQATopKTrainingBoundaryV1
    outer_fold_algorithm: Literal["reuse_frozen_e9_company_folds"]
    inner_fold_algorithm: Literal[
        "each_remaining_outer_fold_is_one_inner_validation_fold"
    ]
    folds: tuple[FinQATopKFoldV1, ...] = Field(min_length=5, max_length=5)
    model: FinQATopKModelContractV1
    cv_gates: FinQATopKCVGatesV1
    internal_validation: FinQATopKInternalBoundaryV1
    internal_gates: FinQATopKInternalGatesV1
    serving_champion: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_serving_status: Literal["DISABLED"]
    e9_development_status: Literal["CONSUMED_NO_RERUN"]
    e10_internal_status: Literal["NOT_RUN_NOT_AUTHORIZED"]
    frozen_test_status: Literal["UNTOUCHED"]
    design_sources: tuple[str, ...] = Field(min_length=2)
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_protocol(self) -> FinQATopKRankerProtocolV1:
        if tuple(fold.fold_index for fold in self.folds) != tuple(range(5)):
            raise ValueError("E11 folds must be ordered and complete")
        if sum(fold.case_count for fold in self.folds) != (
            self.training_boundary.eligible_case_count
        ):
            raise ValueError("E11 fold case counts do not reconcile")
        if sum(fold.company_count for fold in self.folds) != (
            self.training_boundary.eligible_company_count
        ):
            raise ValueError("E11 fold company counts do not reconcile")
        expected = tuple(
            (
                f"adj{int(adjustment):02d}-l2-{int(l2):03d}-"
                f"p{int(preservation * 100):03d}",
                adjustment,
                l2,
                preservation,
            )
            for adjustment in (2.0, 4.0, 8.0)
            for l2 in (100.0, 10.0, 1.0)
            for preservation in (1.0, 0.25)
        )
        actual = tuple(
            (
                item.config_id,
                item.max_e8_score_adjustment,
                item.l2_penalty,
                item.preservation_weight,
            )
            for item in self.model.candidate_configs
        )
        if actual != expected:
            raise ValueError("E11 candidate grid or safety order changed")
        if set(self.model.feature_names).intersection(
            self.model.prohibited_features
        ):
            raise ValueError("E11 learned features contain a prohibited field")
        return self


def load_topk_ranker_protocol_v1(
    path: Path,
) -> tuple[FinQATopKRankerProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQATopKRankerProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQATopKCandidateV1",
    "FinQATopKRankerProtocolV1",
    "load_topk_ranker_protocol_v1",
]
