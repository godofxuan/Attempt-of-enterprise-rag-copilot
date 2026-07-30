from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_program import TypedProgram
from app.external_datasets.finqa_typed_retrospective import FrozenModelIdentity
from app.external_datasets.finqa_v23_calibration_protocol import (
    FinQAV23PairedCalibrationProtocol,
)
from app.external_datasets.finqa_v23_calibration_run import (
    FinQAV23CalibrationCase,
    FinQAV23CalibrationRunManifest,
    FinQAV23CalibrationSummary,
    verify_v23_calibration_run,
)


PUBLIC_SCHEMA_VERSION = "finqa_v23_paired_calibration_public_v1"
_GOLD_OPERATION = re.compile(r"([A-Za-z_]+)\(")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinQAV23DiagnosticSlice(_StrictModel):
    label: str = Field(min_length=1, max_length=128)
    case_count: int = Field(ge=1, le=60)
    answered_count: int = Field(ge=0, le=60)
    strict_correct_count: int = Field(ge=0, le=60)
    grounded_correct_count: int = Field(ge=0, le=60)
    protocol_error_count: int = Field(ge=0, le=60)

    @model_validator(mode="after")
    def validate_counts(self) -> FinQAV23DiagnosticSlice:
        if (
            self.answered_count > self.case_count
            or self.strict_correct_count > self.answered_count
            or self.grounded_correct_count > self.answered_count
            or self.protocol_error_count > self.case_count
            or self.answered_count + self.protocol_error_count
            > self.case_count
        ):
            raise ValueError("v2.3 diagnostic slice counts do not reconcile")
        return self


class FinQAV23CalibrationDiagnostics(_StrictModel):
    case_count: Literal[60] = 60
    input_complete_case_count: int = Field(ge=0, le=60)
    input_complete_rate: float = Field(ge=0, le=1)
    answered_count: int = Field(ge=0, le=60)
    strict_correct_count: int = Field(ge=0, le=60)
    grounded_correct_count: int = Field(ge=0, le=60)
    answered_wrong_count: int = Field(ge=0, le=60)
    protocol_error_count: int = Field(ge=0, le=60)
    gold_single_step_count: int = Field(ge=0, le=60)
    gold_multi_step_count: int = Field(ge=0, le=60)
    by_gold_output_operation: tuple[FinQAV23DiagnosticSlice, ...]
    by_intent_family: tuple[FinQAV23DiagnosticSlice, ...]
    predicted_output_operation_counts: dict[str, int]
    protocol_failure_reason_counts: dict[str, int]
    primary_bottleneck: Literal[
        "semantic_operation_and_operand_planning"
    ] = "semantic_operation_and_operand_planning"

    @model_validator(mode="after")
    def validate_totals(self) -> FinQAV23CalibrationDiagnostics:
        if (
            self.input_complete_rate
            != self.input_complete_case_count / self.case_count
            or self.answered_wrong_count
            != self.answered_count - self.strict_correct_count
            or self.gold_single_step_count + self.gold_multi_step_count
            != self.case_count
            or sum(
                item.case_count for item in self.by_gold_output_operation
            )
            != self.case_count
            or sum(item.case_count for item in self.by_intent_family)
            != self.case_count
            or sum(self.predicted_output_operation_counts.values())
            != self.answered_count
            or sum(self.protocol_failure_reason_counts.values())
            != self.protocol_error_count
        ):
            raise ValueError("v2.3 diagnostic totals do not reconcile")
        return self


class FinQAV23PublicEvidence(_StrictModel):
    schema_version: Literal[
        "finqa_v23_paired_calibration_public_v1"
    ] = PUBLIC_SCHEMA_VERSION
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e2_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e3_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    answer_model: FrozenModelIdentity
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    private_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    private_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: FinQAV23CalibrationSummary
    diagnostics: FinQAV23CalibrationDiagnostics
    content_exclusions: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    next_action: Literal[
        "GATE_E5_SEMANTIC_PLANNING_CALIBRATION_REQUIRED"
    ]

    @model_validator(mode="after")
    def validate_claim_boundary(self) -> FinQAV23PublicEvidence:
        arm = self.summary.b1_v23_intervention
        diagnostics = self.diagnostics
        if (
            self.summary.decision != "CALIBRATION_REJECTED"
            or self.summary.internal_validation_status != "NOT_RUN"
            or self.summary.frozen_test_status != "UNTOUCHED"
            or diagnostics.answered_count != arm.answered_count
            or diagnostics.strict_correct_count
            != round(arm.execution_accuracy * diagnostics.case_count)
            or diagnostics.grounded_correct_count
            != round(
                arm.grounded_execution_accuracy * diagnostics.case_count
            )
            or diagnostics.protocol_error_count
            != arm.protocol_error_count
        ):
            raise ValueError("v2.3 public claim boundary is invalid")
        return self


def _slice(
    label: str,
    rows: Sequence[FinQAV23CalibrationCase],
) -> FinQAV23DiagnosticSlice:
    arm = [row.b1_v23_intervention for row in rows]
    return FinQAV23DiagnosticSlice(
        label=label,
        case_count=len(rows),
        answered_count=sum(item.status == "ANSWERED" for item in arm),
        strict_correct_count=sum(item.strict_execution_match for item in arm),
        grounded_correct_count=sum(
            item.grounded_execution_match for item in arm
        ),
        protocol_error_count=sum(
            item.status == "PROTOCOL_ERROR" for item in arm
        ),
    )


def _gold_program_shape(case: FinQACase) -> tuple[str, ...]:
    operations = tuple(
        match.group(1).casefold()
        for match in _GOLD_OPERATION.finditer(case.qa.program)
    )
    if not operations:
        raise ValueError("FinQA gold program has no operation")
    return operations


def build_v23_diagnostics(
    *,
    rows: Sequence[FinQAV23CalibrationCase],
    cases_by_id: Mapping[str, FinQACase],
    input_complete_case_count: int,
) -> FinQAV23CalibrationDiagnostics:
    if len(rows) != 60 or len({row.case_id for row in rows}) != 60:
        raise ValueError("v2.3 diagnostics require 60 unique rows")
    if set(row.case_id for row in rows) - set(cases_by_id):
        raise ValueError("v2.3 diagnostics are missing source cases")

    by_gold: dict[str, list[FinQAV23CalibrationCase]] = {}
    by_intent: dict[str, list[FinQAV23CalibrationCase]] = {}
    predicted_operations: Counter[str] = Counter()
    single_step_count = 0
    for row in rows:
        case = cases_by_id[row.case_id]
        shape = _gold_program_shape(case)
        single_step_count += len(shape) == 1
        by_gold.setdefault(shape[-1], []).append(row)
        family = extract_financial_question_intent_v2(
            case.qa.question
        ).operation_family
        by_intent.setdefault(family, []).append(row)
        if row.b1_v23_intervention.status == "ANSWERED":
            program = TypedProgram.model_validate_json(
                row.b1_v23_intervention.calculation
            )
            output = next(
                step
                for step in program.steps
                if step.step_id == program.output_step_id
            )
            predicted_operations[output.operation] += 1

    arm = [row.b1_v23_intervention for row in rows]
    answered_count = sum(item.status == "ANSWERED" for item in arm)
    strict_correct_count = sum(item.strict_execution_match for item in arm)
    return FinQAV23CalibrationDiagnostics(
        input_complete_case_count=input_complete_case_count,
        input_complete_rate=input_complete_case_count / 60,
        answered_count=answered_count,
        strict_correct_count=strict_correct_count,
        grounded_correct_count=sum(
            item.grounded_execution_match for item in arm
        ),
        answered_wrong_count=answered_count - strict_correct_count,
        protocol_error_count=sum(
            item.status == "PROTOCOL_ERROR" for item in arm
        ),
        gold_single_step_count=single_step_count,
        gold_multi_step_count=60 - single_step_count,
        by_gold_output_operation=tuple(
            _slice(label, values)
            for label, values in sorted(by_gold.items())
        ),
        by_intent_family=tuple(
            _slice(label, values)
            for label, values in sorted(by_intent.items())
        ),
        predicted_output_operation_counts=dict(
            sorted(predicted_operations.items())
        ),
        protocol_failure_reason_counts=dict(
            sorted(
                Counter(
                    item.failure_reason
                    for item in arm
                    if item.status == "PROTOCOL_ERROR"
                    and item.failure_reason is not None
                ).items()
            )
        ),
    )


def build_v23_public_evidence(
    *,
    run_dir: Path,
    protocol: FinQAV23PairedCalibrationProtocol,
    protocol_sha256: str,
    cases_by_id: Mapping[str, FinQACase],
    input_complete_case_count: int,
) -> FinQAV23PublicEvidence:
    manifest = verify_v23_calibration_run(run_dir, protocol=protocol)
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    details_bytes = (run_dir / "details.jsonl").read_bytes()
    rows = tuple(
        FinQAV23CalibrationCase.model_validate_json(line)
        for line in details_bytes.splitlines()
        if line
    )
    if (
        manifest.protocol_sha256 != protocol_sha256
        or manifest.source_gate_e2_details_sha256
        != protocol.source_gate_e2_private_details_sha256
        or manifest.source_gate_e3_manifest_sha256
        != protocol.source_gate_e3_private_manifest_sha256
    ):
        raise ValueError("v2.3 public source bindings are invalid")
    return FinQAV23PublicEvidence(
        claim_label=protocol.claim_label,
        run_id=manifest.run_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        dataset_sha256=protocol.dataset_sha256,
        selected_case_ids_sha256=manifest.selected_case_ids_sha256,
        source_gate_e2_details_sha256=(
            manifest.source_gate_e2_details_sha256
        ),
        source_gate_e3_manifest_sha256=(
            manifest.source_gate_e3_manifest_sha256
        ),
        answer_model=manifest.answer_model,
        execution_code_revision=manifest.execution_code_revision,
        private_manifest_sha256=hashlib.sha256(
            manifest_bytes
        ).hexdigest(),
        private_details_sha256=hashlib.sha256(details_bytes).hexdigest(),
        summary=manifest.summary,
        diagnostics=build_v23_diagnostics(
            rows=rows,
            cases_by_id=cases_by_id,
            input_complete_case_count=input_complete_case_count,
        ),
        content_exclusions=(
            "case_ids",
            "questions",
            "answers",
            "gold_program_text",
            "evidence_text",
            "candidate_ids",
            "generated_program_text",
        ),
        limitations=(
            "disclosed 60-case development calibration only",
            "the 40-case internal-validation cohort was not consumed",
            "the frozen test was not consumed",
            "aggregate diagnostics are mechanical, not human root-cause labels",
            "the rejected v2.3 route remains disabled",
        ),
        next_action="GATE_E5_SEMANTIC_PLANNING_CALIBRATION_REQUIRED",
    )


__all__ = [
    "PUBLIC_SCHEMA_VERSION",
    "FinQAV23CalibrationDiagnostics",
    "FinQAV23DiagnosticSlice",
    "FinQAV23PublicEvidence",
    "build_v23_diagnostics",
    "build_v23_public_evidence",
]
