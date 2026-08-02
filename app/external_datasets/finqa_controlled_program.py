from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field, ValidationError, field_serializer

from app.external_datasets import finqa_typed_contract_v2 as v22
from app.external_datasets import finqa_typed_contract_v23 as v23
from app.external_datasets import finqa_typed_program as v1
from app.external_datasets.finqa_numeric_evidence_v2 import NumericCandidateV2
from app.external_datasets.finqa_typed_program import (
    CandidateRef,
    FinancialScale,
    FinancialUnit,
    StepRef,
    TypedFinancialOperation,
)


DSL_VERSION = "finqa_controlled_financial_dsl_v1"
VALIDATOR_VERSION = "finqa_controlled_program_validator_v1"
COMPILER_VERSION = "finqa_controlled_program_compiler_v1"
MAX_PROGRAM_STEPS = 5
MAX_PROGRAM_ARGUMENTS = 8
ControlledConstantId = Literal[
    "const_1",
    "const_2",
    "const_3",
    "const_4",
    "const_5",
    "const_10",
    "const_100",
    "const_1000",
]
CONTROLLED_CONSTANT_VALUES: dict[ControlledConstantId, Decimal] = {
    "const_1": Decimal("1"),
    "const_2": Decimal("2"),
    "const_3": Decimal("3"),
    "const_4": Decimal("4"),
    "const_5": Decimal("5"),
    "const_10": Decimal("10"),
    "const_100": Decimal("100"),
    "const_1000": Decimal("1000"),
}


class ControlledConstantRef(v22._StrictFrozenModel):
    constant_id: ControlledConstantId


ControlledOperandRef = CandidateRef | ControlledConstantRef | StepRef


class ControlledProgramStep(v22._StrictFrozenModel):
    step_id: str = Field(pattern=r"^step-0[1-5]$")
    operation: TypedFinancialOperation
    arguments: tuple[ControlledOperandRef, ...] = Field(
        min_length=2,
        max_length=MAX_PROGRAM_ARGUMENTS,
    )


class ControlledTypedProgram(v22._StrictFrozenModel):
    dsl_version: Literal[
        "finqa_controlled_financial_dsl_v1"
    ] = DSL_VERSION
    steps: tuple[ControlledProgramStep, ...] = Field(
        min_length=1,
        max_length=MAX_PROGRAM_STEPS,
    )
    output_step_id: str = Field(pattern=r"^step-0[1-5]$")


class ValidatedControlledProgram(v22._StrictFrozenModel):
    program: ControlledTypedProgram
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    controlled_constant_ids: tuple[ControlledConstantId, ...]
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validator_version: Literal[
        "finqa_controlled_program_validator_v1"
    ] = VALIDATOR_VERSION


class ControlledProgramDiagnostics(v22._StrictFrozenModel):
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_count: int = Field(ge=1, le=MAX_PROGRAM_STEPS)
    candidate_count: int = Field(ge=1, le=v1.MAX_PROGRAM_CANDIDATES)
    evidence_count: int = Field(ge=1, le=v1.MAX_PROGRAM_CANDIDATES)
    controlled_constant_count: int = Field(
        ge=0,
        le=len(CONTROLLED_CONSTANT_VALUES),
    )
    decimal_precision: Literal[50] = v1.PROGRAM_DECIMAL_PRECISION
    presentation_scale: FinancialScale
    presentation_scale_applied: bool
    warnings: tuple[str, ...] = ()


class ControlledProgramResult(v22._StrictFrozenModel):
    value: Decimal
    canonical_value: Decimal
    unit: FinancialUnit
    output_step_id: str = Field(pattern=r"^step-0[1-5]$")
    step_values: Mapping[str, Decimal]
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    controlled_constant_ids: tuple[ControlledConstantId, ...]
    program_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: ControlledProgramDiagnostics
    validator_version: Literal[
        "finqa_controlled_program_validator_v1"
    ] = VALIDATOR_VERSION
    compiler_version: Literal[
        "finqa_controlled_program_compiler_v1"
    ] = COMPILER_VERSION

    @field_serializer("step_values")
    def serialize_step_values(
        self,
        value: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        return dict(value)


@dataclass(frozen=True)
class _ValidatedExecution:
    validated: ValidatedControlledProgram
    step_states: dict[str, v1._ValueState]
    candidate_by_id: dict[str, NumericCandidateV2]


def _parse_program(payload: object) -> ControlledTypedProgram:
    try:
        serialized = (
            payload.model_dump(mode="json")
            if isinstance(payload, ControlledTypedProgram)
            else payload
        )
        if (
            len(v1._canonical_json_bytes(serialized))
            > v1.MAX_PROGRAM_PAYLOAD_BYTES
        ):
            v1._raise_validation(
                "budget_exceeded",
                "controlled program payload exceeds the byte budget",
            )
        return ControlledTypedProgram.model_validate(serialized)
    except v1.TypedProgramValidationError:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        v1._raise_validation(
            "invalid_program_schema",
            "controlled program payload does not match the strict schema",
        )
        raise AssertionError from exc


def _reference_key(
    reference: ControlledOperandRef,
) -> tuple[str, str]:
    if isinstance(reference, StepRef):
        return "step", reference.step_id
    if isinstance(reference, ControlledConstantRef):
        return "constant", reference.constant_id
    return "candidate", reference.candidate_id


def _static_closure(
    *,
    program: ControlledTypedProgram,
    candidate_by_id: Mapping[str, NumericCandidateV2],
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[ControlledConstantId, ...],
]:
    seen_steps: set[str] = set()
    candidate_ids: list[str] = []
    evidence_ids: list[str] = []
    constants: list[ControlledConstantId] = []
    for ordinal, step in enumerate(program.steps, start=1):
        if step.step_id != f"step-{ordinal:02d}":
            v1._raise_validation(
                "invalid_program_schema",
                "controlled program step IDs must be contiguous and ordered",
            )
        for argument in step.arguments:
            if isinstance(argument, StepRef):
                if argument.step_id not in seen_steps:
                    v1._raise_validation(
                        "forward_step_reference",
                        "controlled step reference must point backward",
                    )
            elif isinstance(argument, ControlledConstantRef):
                if argument.constant_id not in constants:
                    constants.append(argument.constant_id)
            else:
                candidate = candidate_by_id.get(argument.candidate_id)
                if candidate is None:
                    v1._raise_validation(
                        "missing_candidate",
                        "controlled program references an unknown candidate",
                    )
                candidate_ids.append(candidate.candidate_id)
                evidence_ids.append(candidate.evidence_id)
        seen_steps.add(step.step_id)
    if program.output_step_id != program.steps[-1].step_id:
        v1._raise_validation(
            "missing_output_step",
            "controlled output must reference the final step",
        )
    unique_candidates = v1._ordered_unique(candidate_ids)
    if not unique_candidates:
        v1._raise_validation(
            "missing_candidate",
            "controlled program must use source-bound evidence",
        )
    return (
        unique_candidates,
        v1._ordered_unique(evidence_ids),
        tuple(constants),
    )


def _validate_structure(program: ControlledTypedProgram) -> None:
    fingerprints: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    step_by_id = {step.step_id: step for step in program.steps}
    for step in program.steps:
        references = tuple(_reference_key(item) for item in step.arguments)
        if len(references) != len(set(references)):
            v1._raise_validation(
                "invalid_program_schema",
                "a controlled step cannot reuse one operand reference",
            )
        fingerprint = (step.operation, references)
        if fingerprint in fingerprints:
            v1._raise_validation(
                "invalid_program_schema",
                "controlled program contains a duplicate calculation step",
            )
        fingerprints.add(fingerprint)

    reachable: set[str] = set()
    pending = [program.output_step_id]
    while pending:
        step_id = pending.pop()
        if step_id in reachable:
            continue
        reachable.add(step_id)
        pending.extend(
            reference.step_id
            for reference in step_by_id[step_id].arguments
            if isinstance(reference, StepRef)
        )
    if reachable != set(step_by_id):
        v1._raise_validation(
            "invalid_program_schema",
            "every controlled step must contribute to the final output",
        )


def _validate_shape(
    *,
    program: ControlledTypedProgram,
    intent: v22.FinancialQuestionIntentV2,
) -> None:
    output = program.steps[-1]
    if output.operation not in intent.allowed_output_operations:
        v1._raise_validation(
            "unsupported_operation",
            "controlled output operation is outside the intent family",
        )
    if (
        intent.operation_family != "percent_change"
        or output.operation == "PERCENT_CHANGE"
    ):
        return
    if output.operation != "DIV" or len(output.arguments) != 2:
        v1._raise_validation(
            "unsupported_operation",
            "percent change requires PERCENT_CHANGE or (new-old)/old",
        )
    numerator, denominator = output.arguments
    if not isinstance(numerator, StepRef):
        v1._raise_validation(
            "unsupported_operation",
            "percent-change numerator must reference a SUB step",
        )
    step_by_id = {step.step_id: step for step in program.steps}
    subtract_step = step_by_id.get(numerator.step_id)
    if (
        subtract_step is None
        or subtract_step.operation != "SUB"
        or len(subtract_step.arguments) != 2
        or _reference_key(denominator)
        != _reference_key(subtract_step.arguments[1])
    ):
        v1._raise_validation(
            "direction_mismatch",
            "percent-change division must reuse the old operand",
        )


def _constant_state(
    constant: ControlledConstantRef,
) -> v1._ValueState:
    return v1._ValueState(
        value=CONTROLLED_CONSTANT_VALUES[constant.constant_id],
        unit="ratio",
        metric=None,
        entity=None,
        periods=frozenset(),
        candidate_ids=(),
        evidence_ids=(),
    )


def _validate_and_execute(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: v22.FinancialQuestionIntentV2,
) -> _ValidatedExecution:
    try:
        checked_intent = v22.FinancialQuestionIntentV2.model_validate(
            intent.model_dump(mode="python")
        )
    except (AttributeError, ValidationError, ValueError) as exc:
        v1._raise_validation(
            "ambiguous_intent",
            "intent does not satisfy the controlled runtime contract",
        )
        raise AssertionError from exc
    program = _parse_program(planner_payload)
    candidate_by_id = v23._validated_candidates_v23(candidates)
    candidate_ids, evidence_ids, constant_ids = _static_closure(
        program=program,
        candidate_by_id=candidate_by_id,
    )
    v22._validate_candidate_contracts_v2(
        candidate_ids=candidate_ids,
        candidate_by_id=candidate_by_id,
        admitted_evidence_ids=set(admitted_evidence_ids),
        intent=checked_intent,
    )
    _validate_structure(program)
    _validate_shape(program=program, intent=checked_intent)

    step_states: dict[str, v1._ValueState] = {}
    with localcontext() as decimal_context:
        decimal_context.prec = v1.PROGRAM_DECIMAL_PRECISION
        for step in program.steps:
            states = tuple(
                (
                    step_states[argument.step_id]
                    if isinstance(argument, StepRef)
                    else (
                        _constant_state(argument)
                        if isinstance(argument, ControlledConstantRef)
                        else v1._candidate_state(
                            candidate_by_id[argument.candidate_id]
                        )
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
            "controlled output unit does not match question intent",
        )
    validation_payload = {
        "admitted_evidence_ids": sorted(admitted_evidence_ids),
        "candidates": [
            candidate_by_id[candidate_id].model_dump(mode="json")
            for candidate_id in candidate_ids
        ],
        "constant_registry": {
            key: str(value)
            for key, value in CONTROLLED_CONSTANT_VALUES.items()
        },
        "intent": checked_intent.model_dump(mode="json"),
        "program": program.model_dump(mode="json"),
        "validator_version": VALIDATOR_VERSION,
    }
    validated = ValidatedControlledProgram(
        program=program,
        candidate_ids=candidate_ids,
        evidence_ids=evidence_ids,
        controlled_constant_ids=constant_ids,
        validation_sha256=hashlib.sha256(
            v1._canonical_json_bytes(validation_payload)
        ).hexdigest(),
    )
    return _ValidatedExecution(
        validated=validated,
        step_states=step_states,
        candidate_by_id=candidate_by_id,
    )


def validate_controlled_program(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: v22.FinancialQuestionIntentV2,
) -> ValidatedControlledProgram:
    return _validate_and_execute(
        planner_payload=planner_payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=intent,
    ).validated


def compile_and_execute_controlled_program(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidateV2],
    admitted_evidence_ids: set[str],
    intent: v22.FinancialQuestionIntentV2,
) -> ControlledProgramResult:
    execution = _validate_and_execute(
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
    return ControlledProgramResult(
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
        controlled_constant_ids=(
            execution.validated.controlled_constant_ids
        ),
        program_sha256=hashlib.sha256(
            v1._canonical_json_bytes(program.model_dump(mode="json"))
        ).hexdigest(),
        diagnostics=ControlledProgramDiagnostics(
            validation_sha256=execution.validated.validation_sha256,
            step_count=len(program.steps),
            candidate_count=len(output.candidate_ids),
            evidence_count=len(output.evidence_ids),
            controlled_constant_count=len(
                execution.validated.controlled_constant_ids
            ),
            presentation_scale=intent.requested_scale,
            presentation_scale_applied=scale_applied,
            warnings=warnings,
        ),
    )


__all__ = [
    "COMPILER_VERSION",
    "CONTROLLED_CONSTANT_VALUES",
    "ControlledConstantId",
    "ControlledConstantRef",
    "ControlledProgramDiagnostics",
    "ControlledProgramResult",
    "ControlledProgramStep",
    "ControlledTypedProgram",
    "DSL_VERSION",
    "MAX_PROGRAM_ARGUMENTS",
    "MAX_PROGRAM_STEPS",
    "VALIDATOR_VERSION",
    "ValidatedControlledProgram",
    "compile_and_execute_controlled_program",
    "validate_controlled_program",
]
