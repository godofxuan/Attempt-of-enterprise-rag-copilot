from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field, ValidationError, field_serializer

from app.external_datasets import finqa_typed_contract_v2 as v22
from app.external_datasets import finqa_typed_program as v1
from app.external_datasets.finqa_numeric_evidence_v2 import (
    EXTRACTION_VERSION_V2,
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_typed_program import (
    FinancialScale,
    FinancialUnit,
    StepRef,
    TypedProgram,
)


VALIDATOR_VERSION = "finqa_typed_program_validator_v2_3"
COMPILER_VERSION = "finqa_typed_program_compiler_v2_3"


class ValidatedTypedProgramV23(v22._StrictFrozenModel):
    program: TypedProgram
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validator_version: Literal[
        "finqa_typed_program_validator_v2_3"
    ] = VALIDATOR_VERSION


class TypedProgramDiagnosticsV23(v22._StrictFrozenModel):
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_count: int = Field(ge=1, le=v1.MAX_PROGRAM_STEPS)
    candidate_count: int = Field(ge=1, le=v1.MAX_PROGRAM_CANDIDATES)
    evidence_count: int = Field(ge=1, le=v1.MAX_PROGRAM_CANDIDATES)
    decimal_precision: Literal[50] = v1.PROGRAM_DECIMAL_PRECISION
    presentation_scale: FinancialScale
    presentation_scale_applied: bool
    warnings: tuple[str, ...] = ()


class TypedProgramResultV23(v22._StrictFrozenModel):
    value: Decimal
    canonical_value: Decimal
    unit: FinancialUnit
    output_step_id: str = Field(pattern=r"^step-0[1-8]$")
    step_values: Mapping[str, Decimal]
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    program_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: TypedProgramDiagnosticsV23
    validator_version: Literal[
        "finqa_typed_program_validator_v2_3"
    ] = VALIDATOR_VERSION
    compiler_version: Literal[
        "finqa_typed_program_compiler_v2_3"
    ] = COMPILER_VERSION

    @field_serializer("step_values")
    def serialize_step_values(
        self,
        value: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        return dict(value)


@dataclass(frozen=True)
class _ValidatedExecutionV23:
    validated: ValidatedTypedProgramV23
    step_states: dict[str, v1._ValueState]
    candidate_by_id: dict[str, NumericCandidateV2]


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _expected_candidate_id(candidate: NumericCandidateV2) -> str:
    payload = {
        "column_header": candidate.column_header,
        "evidence_id": candidate.evidence_id,
        "extraction_version": EXTRACTION_VERSION_V2,
        "normalized_value": _canonical_decimal(candidate.normalized_value),
        "provenance": candidate.provenance_span.model_dump(mode="json"),
        "role": candidate.role,
        "row_header": candidate.row_header,
        "scale": candidate.scale,
        "sign": candidate.sign,
        "source_id": candidate.source_id,
        "source_kind": candidate.source_kind,
        "table_id": candidate.table_id,
        "unit": candidate.unit,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return f"num-{digest[:20]}"


def _validated_candidates_v23(
    candidates: Sequence[NumericCandidateV2],
) -> dict[str, NumericCandidateV2]:
    if len(candidates) > v1.MAX_PROGRAM_CANDIDATES:
        v1._raise_validation(
            "budget_exceeded",
            "candidate set exceeds the v2.3 validator budget",
        )
    by_id: dict[str, NumericCandidateV2] = {}
    identity_fingerprints: set[bytes] = set()
    for candidate in candidates:
        try:
            checked = NumericCandidateV2.model_validate(
                candidate.model_dump(mode="python")
            )
        except (AttributeError, ValidationError, ValueError) as exc:
            v1._raise_validation(
                "missing_provenance",
                "v2.3 candidate provenance is invalid",
            )
            raise AssertionError from exc
        expected_sign = (
            -1
            if checked.normalized_value < 0
            else (1 if checked.normalized_value > 0 else 0)
        )
        provenance = checked.provenance_span
        if (
            checked.sign != expected_sign
            or provenance.end - provenance.start != len(checked.raw_text)
            or provenance.text_sha256
            != hashlib.sha256(checked.raw_text.encode("utf-8")).hexdigest()
        ):
            v1._raise_validation(
                "missing_provenance",
                "v2.3 candidate span or sign is invalid",
            )
        try:
            reconstructed = extract_numeric_candidates_v2(
                source_id=checked.source_id,
                evidence_id=checked.evidence_id,
                text=checked.raw_text,
                kind=checked.source_kind,
                table_id=checked.table_id,
                row_header=checked.row_header,
                column_header=checked.column_header,
                unit_hint=None if checked.unit == "unknown" else checked.unit,
            )
        except ValueError as exc:
            v1._raise_validation(
                "missing_provenance",
                "v2.3 candidate cannot be reconstructed",
            )
            raise AssertionError from exc
        exact = next(
            (
                item
                for item in reconstructed
                if item.provenance_span.start == 0
                and item.provenance_span.end == len(checked.raw_text)
            ),
            None,
        )
        if (
            exact is None
            or exact.normalized_value != checked.normalized_value
            or exact.unit != checked.unit
            or exact.scale != checked.scale
            or exact.sign != checked.sign
        ):
            v1._raise_validation(
                "missing_provenance",
                "v2.3 candidate value does not match its source span",
            )
        fingerprint = v1._canonical_json_bytes(
            {
                "column_header": checked.column_header,
                "evidence_id": checked.evidence_id,
                "extraction_version": checked.extraction_version,
                "normalized_value": _canonical_decimal(
                    checked.normalized_value
                ),
                "provenance": checked.provenance_span.model_dump(mode="json"),
                "role": checked.role,
                "row_header": checked.row_header,
                "scale": checked.scale,
                "sign": checked.sign,
                "source_id": checked.source_id,
                "source_kind": checked.source_kind,
                "table_id": checked.table_id,
                "unit": checked.unit,
            }
        )
        if fingerprint in identity_fingerprints:
            v1._raise_validation(
                "duplicate_candidate",
                "v2.3 candidate set contains duplicate source identities",
            )
        identity_fingerprints.add(fingerprint)
        if checked.candidate_id != _expected_candidate_id(checked):
            v1._raise_validation(
                "missing_provenance",
                "v2.3 candidate ID is not source-bound",
            )
        if checked.candidate_id in by_id:
            v1._raise_validation(
                "duplicate_candidate",
                "v2.3 candidate set contains duplicate IDs",
            )
        by_id[checked.candidate_id] = checked
    return by_id


def _validate_and_execute_v23(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: v22.FinancialQuestionIntentV2,
) -> _ValidatedExecutionV23:
    try:
        checked_intent = v22.FinancialQuestionIntentV2.model_validate(
            intent.model_dump(mode="python")
        )
    except (AttributeError, ValidationError, ValueError) as exc:
        v1._raise_validation(
            "ambiguous_intent",
            "question intent does not satisfy the v2.3 runtime contract",
        )
        raise AssertionError from exc
    program = v1._parse_typed_program(planner_payload)
    candidate_by_id = _validated_candidates_v23(candidates)
    candidate_ids, evidence_ids = v1._static_program_closure(
        program,
        candidate_by_id,
    )
    v22._validate_candidate_contracts_v2(
        candidate_ids=candidate_ids,
        candidate_by_id=candidate_by_id,
        admitted_evidence_ids=set(admitted_evidence_ids),
        intent=checked_intent,
    )
    v22._validate_program_structure_v2(program)
    v22._validate_program_shape_v2(program, checked_intent)

    step_states: dict[str, v1._ValueState] = {}
    with localcontext() as decimal_context:
        decimal_context.prec = v1.PROGRAM_DECIMAL_PRECISION
        for step in program.steps:
            states = tuple(
                (
                    step_states[argument.step_id]
                    if isinstance(argument, StepRef)
                    else v1._candidate_state(
                        candidate_by_id[argument.candidate_id]
                    )
                )
                for argument in step.arguments
            )
            step_states[step.step_id] = v22._execute_step_v2(
                operation=step.operation,
                states=states,
                intent=checked_intent,
            )
    output = step_states[program.output_step_id]
    if (
        checked_intent.requested_unit != "unknown"
        and output.unit != checked_intent.requested_unit
    ):
        v1._raise_validation(
            "unit_mismatch",
            "program output unit does not match the v2.3 intent",
        )
    validation_payload = {
        "admitted_evidence_ids": sorted(admitted_evidence_ids),
        "candidates": [
            candidate_by_id[candidate_id].model_dump(mode="json")
            for candidate_id in candidate_ids
        ],
        "intent": checked_intent.model_dump(mode="json"),
        "program": program.model_dump(mode="json"),
        "validator_version": VALIDATOR_VERSION,
    }
    validated = ValidatedTypedProgramV23(
        program=program,
        candidate_ids=candidate_ids,
        evidence_ids=evidence_ids,
        validation_sha256=hashlib.sha256(
            v1._canonical_json_bytes(validation_payload)
        ).hexdigest(),
    )
    return _ValidatedExecutionV23(
        validated=validated,
        step_states=step_states,
        candidate_by_id=candidate_by_id,
    )


def compile_and_execute_typed_program_v23(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: v22.FinancialQuestionIntentV2,
) -> TypedProgramResultV23:
    execution = _validate_and_execute_v23(
        planner_payload=planner_payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=intent,
    )
    program = execution.validated.program
    output = execution.step_states[program.output_step_id]
    presented, scale_applied, warnings = v22._presentation_value(
        output=output,
        candidate_by_id=execution.candidate_by_id,
        requested_scale=intent.requested_scale,
    )
    return TypedProgramResultV23(
        value=presented,
        canonical_value=output.value,
        unit=output.unit,
        output_step_id=program.output_step_id,
        step_values={
            step.step_id: execution.step_states[step.step_id].value
            for step in program.steps
        },
        candidate_ids=output.candidate_ids,
        evidence_ids=output.evidence_ids,
        program_sha256=hashlib.sha256(
            v1._canonical_json_bytes(program.model_dump(mode="json"))
        ).hexdigest(),
        diagnostics=TypedProgramDiagnosticsV23(
            validation_sha256=execution.validated.validation_sha256,
            step_count=len(program.steps),
            candidate_count=len(output.candidate_ids),
            evidence_count=len(output.evidence_ids),
            presentation_scale=intent.requested_scale,
            presentation_scale_applied=scale_applied,
            warnings=warnings,
        ),
    )


__all__ = [
    "COMPILER_VERSION",
    "VALIDATOR_VERSION",
    "TypedProgramDiagnosticsV23",
    "TypedProgramResultV23",
    "ValidatedTypedProgramV23",
    "compile_and_execute_typed_program_v23",
]
