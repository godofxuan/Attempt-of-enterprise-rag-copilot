from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROTOCOL_SCHEMA_VERSION = (
    "finqa_semantic_planning_calibration_protocol_v1"
)
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class FinQASemanticPlanningArm(_StrictFrozenModel):
    arm_id: Literal[
        "B1_V23_STORED",
        "B2_MULTI_STEP_DIRECT",
        "B3_ROLE_DECOMPOSED",
        "B4_ROLE_DYNAMIC_DEMOS",
    ]
    source: Literal["sealed_gate_e4", "new_gate_e5_execution"]
    model_calls_allowed: bool
    dynamic_demonstrations: bool
    role_decomposition: bool


class FinQASemanticPlanningProgressGates(_StrictFrozenModel):
    min_coverage: float = Field(ge=0, le=1)
    min_execution_accuracy_delta_vs_v23: float = Field(ge=-1, le=1)
    min_grounded_accuracy_delta_vs_v23: float = Field(ge=-1, le=1)
    max_correct_to_wrong_rate_vs_v23: float = Field(ge=0, le=1)
    min_wrong_to_correct_count_vs_v23: int = Field(ge=0, le=60)
    max_protocol_error_rate: float = Field(ge=0, le=1)
    max_latency_mean_multiplier_vs_v23: float = Field(ge=1)
    max_latency_p95_ms: float = Field(gt=0)
    require_demo_isolation_suite: Literal[True] = True
    require_fail_closed_regression_suite: Literal[True] = True


class FinQASemanticPlanningShadowGates(_StrictFrozenModel):
    min_execution_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    min_grounded_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    max_correct_to_wrong_rate_vs_b0: float = Field(ge=0, le=1)


class FinQASemanticPlanningCalibrationProtocol(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_semantic_planning_calibration_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_GATE_E5_IMPLEMENTATION"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e4_run_id: Literal[
        "finqa-v23-paired-calibration-v1"
    ]
    source_gate_e4_public_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e4_private_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e4_private_details_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    development_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    internal_validation_case_count: Literal[40] = 40
    internal_validation_case_ids_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    answer_model_name: Literal["qwen3:8b"]
    answer_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    temperature: Literal[0] = 0
    arm_order_policy: Literal["cyclic_latin_square_v1"]
    arms: tuple[FinQASemanticPlanningArm, ...] = Field(
        min_length=4,
        max_length=4,
    )
    max_program_steps: Literal[3] = 3
    max_semantic_roles: Literal[6] = 6
    max_candidate_count: Literal[24] = 24
    dynamic_demo_count: Literal[3] = 3
    dynamic_demo_source: Literal["pinned_train_split_only"]
    dynamic_demo_retriever: Literal[
        "deterministic_idf_token_overlap_v1"
    ]
    dynamic_demo_payload: Literal[
        "question_plus_value_free_operation_skeleton"
    ]
    max_attempts_per_stage: Literal[2] = 2
    timeout_seconds_per_call: Literal[120.0] = 120.0
    progress_gates: FinQASemanticPlanningProgressGates
    adoption_shadow_gates: FinQASemanticPlanningShadowGates
    selected_arm_rule: Literal[
        "eligible_then_strict_grounded_coverage_protocol_latency"
    ]
    internal_validation_eligibility_rule: Literal[
        "selected_arm_passes_all_progress_and_adoption_shadow_gates"
    ]
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_arms(self) -> FinQASemanticPlanningCalibrationProtocol:
        by_id = {arm.arm_id: arm for arm in self.arms}
        if set(by_id) != {
            "B1_V23_STORED",
            "B2_MULTI_STEP_DIRECT",
            "B3_ROLE_DECOMPOSED",
            "B4_ROLE_DYNAMIC_DEMOS",
        }:
            raise ValueError("Gate E5 arms are invalid")
        stored = by_id["B1_V23_STORED"]
        if (
            stored.source != "sealed_gate_e4"
            or stored.model_calls_allowed
            or stored.role_decomposition
            or stored.dynamic_demonstrations
        ):
            raise ValueError("Gate E5 stored arm is invalid")
        direct = by_id["B2_MULTI_STEP_DIRECT"]
        if (
            direct.source != "new_gate_e5_execution"
            or not direct.model_calls_allowed
            or direct.role_decomposition
            or direct.dynamic_demonstrations
        ):
            raise ValueError("Gate E5 direct arm is invalid")
        decomposed = by_id["B3_ROLE_DECOMPOSED"]
        if (
            decomposed.source != "new_gate_e5_execution"
            or not decomposed.model_calls_allowed
            or not decomposed.role_decomposition
            or decomposed.dynamic_demonstrations
        ):
            raise ValueError("Gate E5 decomposed arm is invalid")
        demos = by_id["B4_ROLE_DYNAMIC_DEMOS"]
        if (
            demos.source != "new_gate_e5_execution"
            or not demos.model_calls_allowed
            or not demos.role_decomposition
            or not demos.dynamic_demonstrations
        ):
            raise ValueError("Gate E5 demo arm is invalid")
        return self


def load_semantic_planning_protocol(
    path: Path,
) -> tuple[FinQASemanticPlanningCalibrationProtocol, str]:
    content = path.resolve().read_bytes()
    protocol = FinQASemanticPlanningCalibrationProtocol.model_validate_json(
        content
    )
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQASemanticPlanningArm",
    "FinQASemanticPlanningCalibrationProtocol",
    "FinQASemanticPlanningProgressGates",
    "FinQASemanticPlanningShadowGates",
    "load_semantic_planning_protocol",
]
