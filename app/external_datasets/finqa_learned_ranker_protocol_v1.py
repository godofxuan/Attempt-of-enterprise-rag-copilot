from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQALearnedRankerFoldV1(_StrictFrozenModel):
    fold_index: int = Field(ge=0, le=4)
    case_count: int = Field(ge=1)
    company_count: int = Field(ge=1)
    company_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinQALearnedRankerTrainingBoundaryV1(_StrictFrozenModel):
    train_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    train_case_count: Literal[6251] = 6251
    train_company_count: Literal[135] = 135
    disclosed_development_company_count: Literal[35] = 35
    disclosed_development_company_ids_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    disclosed_development_question_templates_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    company_disjoint_case_count: Literal[3289] = 3289
    eligible_case_count: Literal[3068] = 3068
    eligible_company_count: Literal[99] = 99
    eligible_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supported_operations: tuple[Literal["add", "subtract", "multiply", "divide"], ...]
    max_program_steps: Literal[4] = 4
    evidence_input: Literal["finqa_qa_model_input"]
    evidence_input_gold_coverage_count: Literal[3068] = 3068
    label_source: Literal["offline_train_gold_program_only"]

    @model_validator(mode="after")
    def validate_supported_operations(
        self,
    ) -> FinQALearnedRankerTrainingBoundaryV1:
        if self.supported_operations != (
            "add",
            "subtract",
            "multiply",
            "divide",
        ):
            raise ValueError("E9 supported-operation boundary changed")
        return self


class FinQALearnedRankerModelContractV1(_StrictFrozenModel):
    model_family: Literal["balanced_l2_ridge_pointwise_ranker_v1"]
    implementation: Literal["numpy_closed_form_linear_solve"]
    l2_penalty: Literal[10.0] = 10.0
    class_weighting: Literal["inverse_frequency_per_training_fold"]
    standardization: Literal["training_fold_zscore_epsilon_1e-12"]
    hyperparameter_search: Literal["NONE"]
    random_state: Literal["NOT_APPLICABLE_DETERMINISTIC"]
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=64)
    prohibited_features: tuple[str, ...] = Field(min_length=1)
    tie_break_rule: Literal[
        "learned_score_desc_then_e8_score_desc_then_descriptor_id_asc"
    ]
    artifact_format: Literal["canonical_json_coefficients_v1"]


class FinQALearnedRankerProgressGatesV1(_StrictFrozenModel):
    min_oof_descriptor_recall_delta_at_4: Literal[0.01] = 0.01
    max_oof_fold_descriptor_recall_stddev: Literal[0.08] = 0.08
    min_development_descriptor_recall_at_4: Literal[0.88] = 0.88
    min_development_descriptor_complete_case_rate_at_4: Literal[0.86] = 0.86
    min_development_candidate_recall_at_8: Literal[
        0.7886178861788617
    ] = 0.7886178861788617
    min_development_candidate_complete_case_rate_at_8: Literal[
        0.7413793103448276
    ] = 0.7413793103448276
    min_development_conditional_candidate_retention_at_8: Literal[
        0.9326923076923077
    ] = 0.9326923076923077
    require_company_disjoint_cross_validation: Literal[True] = True
    require_zero_feature_label_leakage: Literal[True] = True
    require_zero_model_calls: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_guard_scan_before_projection: Literal[True] = True
    require_champion_fallback_verified: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQALearnedRankerProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_learned_ranker_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E9_LEARNED_RANKER_IMPLEMENTATION"]
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    source_e8_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e8_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_case_count: Literal[60] = 60
    development_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_boundary: FinQALearnedRankerTrainingBoundaryV1
    fold_algorithm: Literal["sha256_weighted_greedy_company_kfold_v1"]
    fold_seed: Literal["finqa-e9-company-group-kfold-v1"]
    folds: tuple[FinQALearnedRankerFoldV1, ...] = Field(min_length=5, max_length=5)
    model: FinQALearnedRankerModelContractV1
    progress_gates: FinQALearnedRankerProgressGatesV1
    development_evaluation_budget: Literal[1] = 1
    serving_champion: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_serving_status: Literal["DISABLED"]
    fallback_rule: Literal[
        "any_integrity_or_progress_gate_failure_keeps_e8_champion"
    ]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_folds(self) -> FinQALearnedRankerProtocolV1:
        if tuple(item.fold_index for item in self.folds) != tuple(range(5)):
            raise ValueError("E9 folds must be ordered and complete")
        if sum(item.case_count for item in self.folds) != (
            self.training_boundary.eligible_case_count
        ):
            raise ValueError("E9 fold case counts do not reconcile")
        if sum(item.company_count for item in self.folds) != (
            self.training_boundary.eligible_company_count
        ):
            raise ValueError("E9 fold company counts do not reconcile")
        if len({item.company_ids_sha256 for item in self.folds}) != 5:
            raise ValueError("E9 fold identities are not unique")
        return self


def load_learned_ranker_protocol_v1(
    path: Path,
) -> tuple[FinQALearnedRankerProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQALearnedRankerProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQALearnedRankerProtocolV1",
    "load_learned_ranker_protocol_v1",
]
