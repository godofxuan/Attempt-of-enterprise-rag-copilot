from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_diagnostics import (
    parse_finqa_gold_program,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticCalibrationSummary,
    FinQASemanticPlanningCase,
    SemanticInterventionArmId,
    verify_semantic_calibration_run,
)
from app.external_datasets.finqa_semantic_planning_protocol import (
    FinQASemanticPlanningCalibrationProtocol,
)
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationArmSummary,
)
from app.external_datasets.finqa_typed_retrospective import FrozenModelIdentity


PUBLIC_SCHEMA_VERSION = "finqa_semantic_planning_calibration_public_v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinQASemanticComplexitySlice(_StrictModel):
    label: Literal["single_step", "multi_step"]
    case_count: int = Field(ge=1, le=60)
    answered_count: int = Field(ge=0, le=60)
    strict_correct_count: int = Field(ge=0, le=60)
    grounded_correct_count: int = Field(ge=0, le=60)
    protocol_error_count: int = Field(ge=0, le=60)

    @model_validator(mode="after")
    def validate_counts(self) -> FinQASemanticComplexitySlice:
        if (
            self.answered_count > self.case_count
            or self.strict_correct_count > self.answered_count
            or self.grounded_correct_count > self.answered_count
            or self.protocol_error_count > self.case_count
            or self.answered_count + self.protocol_error_count
            > self.case_count
        ):
            raise ValueError("semantic complexity counts do not reconcile")
        return self


class FinQASemanticAblation(_StrictModel):
    coverage_delta_demo_vs_no_demo: float = Field(ge=-1, le=1)
    execution_accuracy_delta_demo_vs_no_demo: float = Field(ge=-1, le=1)
    grounded_accuracy_delta_demo_vs_no_demo: float = Field(ge=-1, le=1)
    protocol_error_count_delta_demo_vs_no_demo: int = Field(ge=-60, le=60)
    latency_mean_multiplier_demo_vs_no_demo: float = Field(ge=0)


class FinQASemanticPlanningDiagnostics(_StrictModel):
    case_count: Literal[60] = 60
    demo_count_per_case: Literal[3] = 3
    unique_demo_payload_count: int = Field(ge=1, le=60)
    execution_order_counts: dict[str, int]
    arm_metrics: dict[str, FinQATypedCalibrationArmSummary]
    answered_wrong_counts: dict[str, int]
    conditional_execution_accuracy: dict[str, float]
    dynamic_demo_by_gold_complexity: tuple[
        FinQASemanticComplexitySlice,
        FinQASemanticComplexitySlice,
    ]
    demo_ablation: FinQASemanticAblation
    primary_bottleneck: Literal[
        "ROLE_TO_CANDIDATE_BINDING_AND_PROGRAM_SEMANTICS"
    ] = "ROLE_TO_CANDIDATE_BINDING_AND_PROGRAM_SEMANTICS"

    @model_validator(mode="after")
    def validate_totals(self) -> FinQASemanticPlanningDiagnostics:
        expected_arms = {
            "B1_V23_STORED",
            "B2_MULTI_STEP_DIRECT",
            "B3_ROLE_DECOMPOSED",
            "B4_ROLE_DYNAMIC_DEMOS",
        }
        if (
            set(self.arm_metrics) != expected_arms
            or set(self.answered_wrong_counts) != expected_arms
            or set(self.conditional_execution_accuracy) != expected_arms
            or sum(self.execution_order_counts.values()) != self.case_count
            or set(self.execution_order_counts.values()) != {20}
            or sum(
                item.case_count
                for item in self.dynamic_demo_by_gold_complexity
            )
            != self.case_count
            or {
                item.label for item in self.dynamic_demo_by_gold_complexity
            }
            != {"single_step", "multi_step"}
        ):
            raise ValueError("semantic diagnostic totals do not reconcile")
        for arm_id, metrics in self.arm_metrics.items():
            answered_wrong = (
                metrics.answered_count
                - round(metrics.execution_accuracy * self.case_count)
            )
            conditional = (
                round(metrics.execution_accuracy * self.case_count)
                / metrics.answered_count
                if metrics.answered_count
                else 0.0
            )
            if (
                self.answered_wrong_counts[arm_id] != answered_wrong
                or self.conditional_execution_accuracy[arm_id]
                != conditional
            ):
                raise ValueError(
                    "semantic conditional accuracy is inconsistent"
                )
        return self


class FinQASemanticPlanningPublicEvidence(_StrictModel):
    schema_version: Literal[
        "finqa_semantic_planning_calibration_public_v1"
    ] = PUBLIC_SCHEMA_VERSION
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e4_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e4_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demo_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demo_index_count: int = Field(ge=100)
    answer_model: FrozenModelIdentity
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_file_sha256: dict[str, str] = Field(min_length=1)
    private_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    private_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: FinQASemanticCalibrationSummary
    diagnostics: FinQASemanticPlanningDiagnostics
    content_exclusions: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    next_action: Literal[
        "GATE_E6_ROLE_CANDIDATE_COMPATIBILITY_CALIBRATION_REQUIRED"
    ]

    @model_validator(mode="after")
    def validate_claim_boundary(
        self,
    ) -> FinQASemanticPlanningPublicEvidence:
        if (
            self.summary.decision != "CALIBRATION_REJECTED"
            or self.summary.selected_arm is not None
            or self.summary.internal_validation_status != "NOT_RUN"
            or self.summary.frozen_test_status != "UNTOUCHED"
            or self.diagnostics.arm_metrics["B1_V23_STORED"]
            != self.summary.b1_v23_stored
            or self.diagnostics.arm_metrics["B2_MULTI_STEP_DIRECT"]
            != self.summary.candidates["B2_MULTI_STEP_DIRECT"].metrics
            or self.diagnostics.arm_metrics["B3_ROLE_DECOMPOSED"]
            != self.summary.candidates["B3_ROLE_DECOMPOSED"].metrics
            or self.diagnostics.arm_metrics["B4_ROLE_DYNAMIC_DEMOS"]
            != self.summary.candidates["B4_ROLE_DYNAMIC_DEMOS"].metrics
        ):
            raise ValueError("semantic public claim boundary is invalid")
        return self


def _complexity_slice(
    *,
    label: Literal["single_step", "multi_step"],
    rows: Sequence[FinQASemanticPlanningCase],
) -> FinQASemanticComplexitySlice:
    arms = [row.b4_dynamic_demos for row in rows]
    return FinQASemanticComplexitySlice(
        label=label,
        case_count=len(rows),
        answered_count=sum(arm.status == "ANSWERED" for arm in arms),
        strict_correct_count=sum(arm.strict_execution_match for arm in arms),
        grounded_correct_count=sum(
            arm.grounded_execution_match for arm in arms
        ),
        protocol_error_count=sum(
            arm.status == "PROTOCOL_ERROR" for arm in arms
        ),
    )


def build_semantic_public_evidence(
    *,
    run_dir: Path,
    protocol: FinQASemanticPlanningCalibrationProtocol,
    protocol_sha256: str,
    cases_by_id: Mapping[str, FinQACase],
) -> FinQASemanticPlanningPublicEvidence:
    manifest = verify_semantic_calibration_run(
        run_dir,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
    )
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    details_bytes = (run_dir / "details.jsonl").read_bytes()
    rows = tuple(
        FinQASemanticPlanningCase.model_validate_json(line)
        for line in details_bytes.splitlines()
        if line
    )
    if set(row.case_id for row in rows) - set(cases_by_id):
        raise ValueError("semantic public evidence lacks source cases")
    by_complexity: dict[str, list[FinQASemanticPlanningCase]] = {
        "single_step": [],
        "multi_step": [],
    }
    for row in rows:
        operation_count = len(
            parse_finqa_gold_program(
                cases_by_id[row.case_id].qa.program
            ).operations
        )
        by_complexity[
            "single_step" if operation_count == 1 else "multi_step"
        ].append(row)

    summary = manifest.summary
    arm_metrics = {
        "B1_V23_STORED": summary.b1_v23_stored,
        **{
            arm_id: summary.candidates[arm_id].metrics
            for arm_id in (
                "B2_MULTI_STEP_DIRECT",
                "B3_ROLE_DECOMPOSED",
                "B4_ROLE_DYNAMIC_DEMOS",
            )
        },
    }
    answered_wrong = {
        arm_id: metrics.answered_count
        - round(metrics.execution_accuracy * 60)
        for arm_id, metrics in arm_metrics.items()
    }
    conditional = {
        arm_id: (
            round(metrics.execution_accuracy * 60) / metrics.answered_count
            if metrics.answered_count
            else 0.0
        )
        for arm_id, metrics in arm_metrics.items()
    }
    roles = arm_metrics["B3_ROLE_DECOMPOSED"]
    demos = arm_metrics["B4_ROLE_DYNAMIC_DEMOS"]
    diagnostics = FinQASemanticPlanningDiagnostics(
        unique_demo_payload_count=len(
            {
                row.b4_demo_payload_sha256
                for row in rows
                if row.b4_demo_payload_sha256 is not None
            }
        ),
        execution_order_counts=dict(
            sorted(
                Counter(
                    ">".join(row.arm_order) for row in rows
                ).items()
            )
        ),
        arm_metrics=arm_metrics,
        answered_wrong_counts=answered_wrong,
        conditional_execution_accuracy=conditional,
        dynamic_demo_by_gold_complexity=(
            _complexity_slice(
                label="single_step",
                rows=by_complexity["single_step"],
            ),
            _complexity_slice(
                label="multi_step",
                rows=by_complexity["multi_step"],
            ),
        ),
        demo_ablation=FinQASemanticAblation(
            coverage_delta_demo_vs_no_demo=(
                demos.coverage - roles.coverage
            ),
            execution_accuracy_delta_demo_vs_no_demo=(
                demos.execution_accuracy - roles.execution_accuracy
            ),
            grounded_accuracy_delta_demo_vs_no_demo=(
                demos.grounded_execution_accuracy
                - roles.grounded_execution_accuracy
            ),
            protocol_error_count_delta_demo_vs_no_demo=(
                demos.protocol_error_count - roles.protocol_error_count
            ),
            latency_mean_multiplier_demo_vs_no_demo=(
                demos.latency_ms_mean / roles.latency_ms_mean
                if roles.latency_ms_mean
                else 0.0
            ),
        ),
    )
    return FinQASemanticPlanningPublicEvidence(
        claim_label=protocol.claim_label,
        run_id=manifest.run_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e4_manifest_sha256=(
            manifest.source_gate_e4_manifest_sha256
        ),
        source_gate_e4_details_sha256=(
            manifest.source_gate_e4_details_sha256
        ),
        development_split_sha256=manifest.development_split_sha256,
        training_split_sha256=manifest.training_split_sha256,
        selected_case_ids_sha256=manifest.selected_case_ids_sha256,
        demo_index_sha256=manifest.demo_index_sha256,
        demo_index_count=manifest.demo_index_count,
        answer_model=manifest.answer_model,
        execution_code_revision=manifest.execution_code_revision,
        implementation_file_sha256=manifest.implementation_file_sha256,
        private_manifest_sha256=hashlib.sha256(
            manifest_bytes
        ).hexdigest(),
        private_details_sha256=hashlib.sha256(details_bytes).hexdigest(),
        summary=summary,
        diagnostics=diagnostics,
        content_exclusions=(
            "case_ids",
            "questions",
            "answers",
            "gold_program_text",
            "evidence_text",
            "candidate_ids",
            "generated_program_text",
            "demonstration_payloads",
        ),
        limitations=(
            "disclosed 60-case development calibration only",
            "the 40-case internal-validation cohort was not consumed",
            "the frozen test was not consumed",
            "dynamic demonstrations improved validity more than correctness",
            "no intervention arm passed every frozen progress and shadow gate",
            "all typed routes remain disabled",
        ),
        next_action=(
            "GATE_E6_ROLE_CANDIDATE_COMPATIBILITY_CALIBRATION_REQUIRED"
        ),
    )


__all__ = [
    "PUBLIC_SCHEMA_VERSION",
    "FinQASemanticAblation",
    "FinQASemanticComplexitySlice",
    "FinQASemanticPlanningDiagnostics",
    "FinQASemanticPlanningPublicEvidence",
    "build_semantic_public_evidence",
]
