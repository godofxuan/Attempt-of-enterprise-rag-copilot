from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROTOCOL_SCHEMA_VERSION = "finqa_v23_paired_calibration_protocol_v1"
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class FinQAV23CalibrationArm(_StrictFrozenModel):
    arm_id: Literal[
        "B0_STORED",
        "B1_V22_STORED",
        "B1_V23_INTERVENTION",
    ]
    source: Literal["sealed_gate_e2", "new_gate_e4_execution"]
    model_calls_allowed: bool


class FinQAV23ProgressGates(_StrictFrozenModel):
    min_coverage: float = Field(ge=0, le=1)
    min_execution_accuracy_delta_vs_v22: float = Field(ge=-1, le=1)
    min_grounded_accuracy_delta_vs_v22: float = Field(ge=-1, le=1)
    max_correct_to_wrong_rate_vs_v22: float = Field(ge=0, le=1)
    min_wrong_to_correct_count_vs_v22: int = Field(ge=0)
    max_protocol_error_rate: float = Field(ge=0, le=1)
    max_latency_mean_multiplier_vs_v22: float = Field(ge=1)
    max_latency_p95_ms: float = Field(gt=0)
    require_gate_e3_input_passed: Literal[True] = True
    require_fail_closed_regression_suite: Literal[True] = True


class FinQAV23AdoptionShadowGates(_StrictFrozenModel):
    min_execution_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    min_grounded_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    max_correct_to_wrong_rate_vs_b0: float = Field(ge=0, le=1)


class FinQAV23PairedCalibrationProtocol(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_v23_paired_calibration_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_V23_MODEL_CALLS"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e2_run_id: Literal[
        "finqa-typed-contract-v2-2-calibration-v1"
    ]
    source_gate_e2_public_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e2_private_details_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e3_run_id: Literal[
        "finqa-numeric-evidence-gate-e3-calibration-v2"
    ]
    source_gate_e3_public_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e3_private_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e3_private_details_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
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
    arms: tuple[FinQAV23CalibrationArm, ...] = Field(min_length=3, max_length=3)
    primary_comparison: Literal["B1_V23_INTERVENTION_vs_B1_V22_STORED"]
    adoption_shadow_comparison: Literal["B1_V23_INTERVENTION_vs_B0_STORED"]
    numeric_extraction_version: Literal["finqa_numeric_candidate_v2"]
    closure_version: Literal["finqa_numeric_evidence_closure_v2"]
    shortlist_version: Literal["finqa_numeric_evidence_shortlist_v2"]
    planner_version: Literal["finqa_typed_planner_v2_2"]
    max_attempts_per_case: Literal[2] = 2
    timeout_seconds: Literal[120.0] = 120.0
    progress_gates: FinQAV23ProgressGates
    adoption_shadow_gates: FinQAV23AdoptionShadowGates
    internal_validation_eligibility_rule: Literal[
        "all_progress_and_adoption_shadow_gates_pass"
    ]
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_arm_contract(self) -> FinQAV23PairedCalibrationProtocol:
        by_id = {arm.arm_id: arm for arm in self.arms}
        if set(by_id) != {
            "B0_STORED",
            "B1_V22_STORED",
            "B1_V23_INTERVENTION",
        }:
            raise ValueError("v2.3 calibration arms are invalid")
        if any(
            by_id[arm_id].source != "sealed_gate_e2"
            or by_id[arm_id].model_calls_allowed
            for arm_id in ("B0_STORED", "B1_V22_STORED")
        ):
            raise ValueError("stored v2.3 comparison arms cannot call a model")
        intervention = by_id["B1_V23_INTERVENTION"]
        if (
            intervention.source != "new_gate_e4_execution"
            or not intervention.model_calls_allowed
        ):
            raise ValueError("v2.3 intervention arm cannot execute")
        return self


def load_v23_calibration_protocol(
    path: Path,
) -> tuple[FinQAV23PairedCalibrationProtocol, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAV23PairedCalibrationProtocol.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQAV23AdoptionShadowGates",
    "FinQAV23CalibrationArm",
    "FinQAV23PairedCalibrationProtocol",
    "FinQAV23ProgressGates",
    "load_v23_calibration_protocol",
]
