from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQAPairwiseFoldV1(_StrictFrozenModel):
    fold_index: int = Field(ge=0, le=4)
    case_count: int = Field(ge=1)
    company_count: int = Field(ge=1)
    company_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinQAPairwiseTrainBoundaryV1(_StrictFrozenModel):
    train_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_case_count: Literal[3068] = 3068
    eligible_company_count: Literal[99] = 99
    eligible_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_source: Literal[
        "finqa_retrieved_all_score_sorted_top10_without_gold_injection"
    ]
    max_selected_units_per_case: Literal[10] = 10
    min_selected_units_observed: Literal[6] = 6
    selected_unit_count_distribution: dict[str, int]
    retrieval_selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    full_gold_evidence_coverage_count: Literal[3014] = 3014
    any_gold_evidence_coverage_count: Literal[3067] = 3067


class FinQAPairwiseModelContractV1(_StrictFrozenModel):
    model_family: Literal["l2_pairwise_ridge_bounded_e8_residual_v1"]
    implementation: Literal["numpy_closed_form_pairwise_margin_solve"]
    l2_penalty: Literal[10.0] = 10.0
    max_hard_negatives_per_positive: Literal[8] = 8
    hard_negative_order: Literal["e8_score_desc_then_descriptor_id_asc"]
    residual_clip: Literal[1.0] = 1.0
    max_e8_score_adjustment: Literal[4.0] = 4.0
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=64)
    prohibited_features: tuple[str, ...] = Field(min_length=1)
    hyperparameter_search: Literal["NONE"]
    tie_break_rule: Literal[
        "bounded_residual_score_desc_then_e8_score_desc_then_descriptor_id_asc"
    ]


class FinQAPairwiseCVGatesV1(_StrictFrozenModel):
    min_preparation_success_rate: Literal[0.90] = 0.90
    min_labelable_case_rate: Literal[0.90] = 0.90
    min_oof_descriptor_recall_delta_at_4: Literal[0.01] = 0.01
    max_oof_fold_descriptor_recall_stddev: Literal[0.05] = 0.05
    require_no_regressed_fold: Literal[True] = True
    min_fold_coefficient_cosine_similarity: Literal[0.60] = 0.60
    require_zero_model_calls: Literal[True] = True
    require_company_disjoint_folds: Literal[True] = True
    require_zero_feature_label_leakage: Literal[True] = True


class FinQAPairwiseInternalBoundaryV1(_StrictFrozenModel):
    source_retrospective_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_private_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: Literal[40] = 40
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_units_per_case: Literal[10] = 10
    evaluation_budget: Literal[1] = 1
    status: Literal["NOT_RUN"]


class FinQAPairwiseInternalGatesV1(_StrictFrozenModel):
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


class FinQAPairwiseResidualProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_pairwise_residual_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E10_PAIRWISE_RESIDUAL_IMPLEMENTATION"]
    claim_label: Literal["TRAIN_ONLY_THEN_SINGLE_INTERNAL_VALIDATION"]
    source_e8_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e9_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e9_cv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e9_development_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e9_postmortem_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    e9_development_evaluation_status: Literal["CONSUMED_NO_RERUN"]
    training_boundary: FinQAPairwiseTrainBoundaryV1
    fold_algorithm: Literal["sha256_weighted_greedy_company_kfold_v1"]
    fold_seed: Literal["finqa-e9-company-group-kfold-v1"]
    folds: tuple[FinQAPairwiseFoldV1, ...] = Field(min_length=5, max_length=5)
    model: FinQAPairwiseModelContractV1
    cv_gates: FinQAPairwiseCVGatesV1
    internal_validation: FinQAPairwiseInternalBoundaryV1
    internal_gates: FinQAPairwiseInternalGatesV1
    serving_champion: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_serving_status: Literal["DISABLED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_folds_and_features(
        self,
    ) -> FinQAPairwiseResidualProtocolV1:
        if tuple(item.fold_index for item in self.folds) != tuple(range(5)):
            raise ValueError("E10 folds must be ordered and complete")
        if sum(item.case_count for item in self.folds) != (
            self.training_boundary.eligible_case_count
        ):
            raise ValueError("E10 fold case counts do not reconcile")
        if sum(item.company_count for item in self.folds) != (
            self.training_boundary.eligible_company_count
        ):
            raise ValueError("E10 fold company counts do not reconcile")
        if set(self.model.feature_names).intersection(
            self.model.prohibited_features
        ):
            raise ValueError("E10 learned features contain a prohibited field")
        if self.training_boundary.selected_unit_count_distribution != {
            "6": 12,
            "7": 21,
            "8": 11,
            "9": 22,
            "10": 3002,
        }:
            raise ValueError("E10 retrieval input count distribution changed")
        return self


def load_pairwise_residual_protocol_v1(
    path: Path,
) -> tuple[FinQAPairwiseResidualProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAPairwiseResidualProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQAPairwiseResidualProtocolV1",
    "load_pairwise_residual_protocol_v1",
]
