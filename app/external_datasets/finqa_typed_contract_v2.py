from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import (
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    model_validator,
)

from app.external_datasets import finqa_typed_program as v1
from app.external_datasets.finqa_typed_program import (
    FinancialScale,
    FinancialUnit,
    NumericCandidate,
    StepRef,
    TypedFinancialOperation,
    TypedProgram,
    TypedProgramValidationError,
)


INTENT_VERSION = "finqa_financial_question_intent_v2_2"
VALIDATOR_VERSION = "finqa_typed_program_validator_v2_2"
COMPILER_VERSION = "finqa_typed_program_compiler_v2_2"
MAX_V2_PROGRAM_STEPS = 5

OperationFamily = Literal[
    "exact_add",
    "exact_subtract",
    "exact_multiply",
    "exact_divide",
    "ratio",
    "percent_change",
    "average",
    "unspecified",
]

_ALL_OPERATIONS: tuple[TypedFinancialOperation, ...] = (
    "ADD",
    "SUB",
    "MUL",
    "DIV",
    "PERCENT_CHANGE",
    "RATIO",
    "AVERAGE",
)
_FAMILY_OUTPUTS: dict[
    OperationFamily,
    tuple[TypedFinancialOperation, ...],
] = {
    "exact_add": ("ADD",),
    "exact_subtract": ("SUB",),
    "exact_multiply": ("MUL",),
    "exact_divide": ("DIV",),
    "ratio": ("DIV", "RATIO"),
    "percent_change": ("DIV", "PERCENT_CHANGE"),
    "average": ("AVERAGE",),
    "unspecified": _ALL_OPERATIONS,
}
_PRESENTATION_DIVISOR: dict[FinancialScale, Decimal] = {
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "basis_point": Decimal("0.0001"),
}


class _StrictFrozenModel(v1._StrictFrozenModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class FinancialQuestionIntentV2(_StrictFrozenModel):
    operation_family: OperationFamily
    allowed_output_operations: tuple[TypedFinancialOperation, ...] = Field(
        min_length=1,
        max_length=len(_ALL_OPERATIONS),
    )
    metric: str | None = Field(default=None, max_length=512)
    entity: str | None = Field(default=None, max_length=512)
    target_period: str | None = Field(default=None, max_length=128)
    start_period: str | None = Field(default=None, max_length=128)
    end_period: str | None = Field(default=None, max_length=128)
    requested_unit: FinancialUnit
    requested_scale: FinancialScale
    direction: Literal[
        "new_over_old",
        "old_over_new",
        "part_over_total",
        "none",
    ]
    allow_additive_metric_composition: bool
    unknown_metadata_policy: Literal["allow_if_no_known_conflict"] = (
        "allow_if_no_known_conflict"
    )
    intent_version: Literal[
        "finqa_financial_question_intent_v2_2"
    ] = INTENT_VERSION

    @model_validator(mode="after")
    def validate_contract(self) -> FinancialQuestionIntentV2:
        if (self.start_period is None) != (self.end_period is None):
            raise ValueError("start_period and end_period must be paired")
        if self.target_period is not None and self.start_period is not None:
            raise ValueError(
                "target_period cannot be combined with start/end periods"
            )
        expected_outputs = _FAMILY_OUTPUTS[self.operation_family]
        if (
            self.allowed_output_operations != expected_outputs
            or len(set(self.allowed_output_operations))
            != len(self.allowed_output_operations)
        ):
            raise ValueError(
                "allowed output operations do not match the operation family"
            )
        if (
            self.operation_family == "percent_change"
            and self.requested_unit != "ratio"
        ):
            raise ValueError("percent-change intent must request ratio output")
        if (
            self.direction in {"new_over_old", "old_over_new"}
            and self.operation_family != "percent_change"
        ):
            raise ValueError(
                "temporal direction is reserved for percent-change intent"
            )
        return self


class ValidatedTypedProgramV2(_StrictFrozenModel):
    program: TypedProgram
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validator_version: Literal[
        "finqa_typed_program_validator_v2_2"
    ] = VALIDATOR_VERSION


class TypedProgramDiagnosticsV2(_StrictFrozenModel):
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_count: int = Field(ge=1, le=v1.MAX_PROGRAM_STEPS)
    candidate_count: int = Field(ge=1, le=v1.MAX_PROGRAM_CANDIDATES)
    evidence_count: int = Field(ge=1, le=v1.MAX_PROGRAM_CANDIDATES)
    decimal_precision: Literal[50] = v1.PROGRAM_DECIMAL_PRECISION
    presentation_scale: FinancialScale
    presentation_scale_applied: bool
    warnings: tuple[str, ...] = ()


class TypedProgramResultV2(_StrictFrozenModel):
    value: Decimal
    canonical_value: Decimal
    unit: FinancialUnit
    output_step_id: str = Field(pattern=r"^step-0[1-8]$")
    step_values: Mapping[str, Decimal]
    candidate_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    program_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnostics: TypedProgramDiagnosticsV2
    validator_version: Literal[
        "finqa_typed_program_validator_v2_2"
    ] = VALIDATOR_VERSION
    compiler_version: Literal[
        "finqa_typed_program_compiler_v2_2"
    ] = COMPILER_VERSION

    @field_serializer("step_values")
    def serialize_step_values(
        self,
        value: Mapping[str, Decimal],
    ) -> dict[str, Decimal]:
        return dict(value)


@dataclass(frozen=True)
class _ValidatedExecutionV2:
    validated: ValidatedTypedProgramV2
    step_states: dict[str, v1._ValueState]
    candidate_by_id: dict[str, NumericCandidate]


def allowed_outputs_for_family(
    family: OperationFamily,
) -> tuple[TypedFinancialOperation, ...]:
    return _FAMILY_OUTPUTS[family]


def _candidate_period(candidate: NumericCandidate) -> str | None:
    if candidate.period is not None:
        return candidate.period.casefold().strip()
    if candidate.fiscal_year is not None:
        return str(candidate.fiscal_year)
    return None


def _known_metadata(
    states: tuple[v1._ValueState, ...],
    attribute: Literal["metric", "entity"],
    *,
    allow_composition: bool,
) -> str | None:
    values = [
        (value, v1._metadata_key(value))
        for state in states
        if (value := getattr(state, attribute)) is not None
    ]
    keys = {key for _, key in values if key is not None}
    if len(keys) > 1:
        if allow_composition:
            return None
        v1._raise_validation(
            "metric_mismatch",
            f"operation arguments have incompatible known {attribute}",
        )
    return values[0][0] if values and len(keys) == 1 else None


def _compatible_same_unit(
    states: tuple[v1._ValueState, ...],
) -> FinancialUnit:
    known = {state.unit for state in states if state.unit != "unknown"}
    if len(known) > 1:
        v1._raise_validation(
            "unit_mismatch",
            "operation arguments have incompatible known units",
        )
    return next(iter(known), "unknown")


def _validate_candidate_contracts_v2(
    *,
    candidate_ids: tuple[str, ...],
    candidate_by_id: dict[str, NumericCandidate],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
) -> None:
    if len(admitted_evidence_ids) > v1.MAX_PROGRAM_CANDIDATES:
        v1._raise_validation(
            "budget_exceeded",
            "admitted evidence set exceeds the validator budget",
        )
    used = [candidate_by_id[candidate_id] for candidate_id in candidate_ids]
    for candidate in used:
        if candidate.evidence_id not in admitted_evidence_ids:
            v1._raise_validation(
                "unadmitted_source",
                "candidate is not from admitted evidence",
            )
        if candidate.role != "operand":
            v1._raise_validation(
                "invalid_candidate_role",
                "non-operand candidate cannot enter a program",
            )

    allowed_periods: set[str] | None = None
    if intent.target_period is not None:
        allowed_periods = {intent.target_period.casefold().strip()}
    elif intent.start_period is not None and intent.end_period is not None:
        allowed_periods = {
            intent.start_period.casefold().strip(),
            intent.end_period.casefold().strip(),
        }
    if allowed_periods is not None:
        for candidate in used:
            period = _candidate_period(candidate)
            if period is not None and period not in allowed_periods:
                v1._raise_validation(
                    "temporal_mismatch",
                    "candidate has a known period outside the question boundary",
                )

    requested_metric = v1._metadata_key(intent.metric)
    if requested_metric is not None:
        for candidate in used:
            candidate_metric = v1._metadata_key(candidate.metric)
            if (
                candidate_metric is not None
                and candidate_metric != requested_metric
            ):
                v1._raise_validation(
                    "metric_mismatch",
                    "candidate has a known metric conflict",
                )
    requested_entity = v1._metadata_key(intent.entity)
    if requested_entity is not None:
        for candidate in used:
            candidate_entity = v1._metadata_key(candidate.entity)
            if (
                candidate_entity is not None
                and candidate_entity != requested_entity
            ):
                v1._raise_validation(
                    "metric_mismatch",
                    "candidate has a known entity conflict",
                )
    for candidate in used:
        expected_sign = (
            -1
            if candidate.normalized_value < 0
            else (1 if candidate.normalized_value > 0 else 0)
        )
        if candidate.sign != expected_sign:
            v1._raise_validation(
                "sign_mismatch",
                "candidate sign is inconsistent with its value",
            )


def _validate_arity_v2(
    operation: TypedFinancialOperation,
    argument_count: int,
) -> None:
    if operation in {"ADD", "AVERAGE"}:
        valid = 2 <= argument_count <= v1.MAX_PROGRAM_ARGUMENTS
    else:
        valid = argument_count == 2
    if not valid:
        v1._raise_validation(
            "invalid_arity",
            "operation has an invalid v2 argument count",
        )


def _validate_direction_v2(
    *,
    operation: TypedFinancialOperation,
    states: tuple[v1._ValueState, ...],
    intent: FinancialQuestionIntentV2,
) -> None:
    if (
        intent.operation_family != "percent_change"
        or operation not in {"SUB", "PERCENT_CHANGE"}
        or intent.start_period is None
        or intent.end_period is None
        or intent.direction not in {"new_over_old", "old_over_new"}
    ):
        return
    if any(len(state.periods) != 1 for state in states[:2]):
        return
    start = intent.start_period.casefold().strip()
    end = intent.end_period.casefold().strip()
    expected = (
        (end, start)
        if intent.direction == "new_over_old"
        else (start, end)
    )
    actual = tuple(next(iter(state.periods)) for state in states[:2])
    if actual != expected:
        v1._raise_validation(
            "direction_mismatch",
            "known operand order conflicts with the requested direction",
        )


def _execute_step_v2(
    *,
    operation: TypedFinancialOperation,
    states: tuple[v1._ValueState, ...],
    intent: FinancialQuestionIntentV2,
) -> v1._ValueState:
    _validate_arity_v2(operation, len(states))
    _validate_direction_v2(
        operation=operation,
        states=states,
        intent=intent,
    )
    values = tuple(state.value for state in states)
    metric: str | None = None
    entity: str | None = None
    if operation == "ADD":
        metric = _known_metadata(
            states,
            "metric",
            allow_composition=intent.allow_additive_metric_composition,
        )
        entity = _known_metadata(
            states,
            "entity",
            allow_composition=intent.allow_additive_metric_composition,
        )
        unit = _compatible_same_unit(states)
        value = sum(values, start=Decimal("0"))
    elif operation in {"SUB", "AVERAGE", "PERCENT_CHANGE"}:
        metric = _known_metadata(
            states,
            "metric",
            allow_composition=False,
        )
        entity = _known_metadata(
            states,
            "entity",
            allow_composition=False,
        )
        unit = _compatible_same_unit(states)
        if operation == "SUB":
            value = values[0] - values[1]
        elif operation == "AVERAGE":
            value = sum(values, start=Decimal("0")) / Decimal(len(values))
        else:
            if values[1] == 0:
                v1._raise_validation(
                    "divide_by_zero",
                    "old value must not be zero",
                )
            unit = "ratio"
            value = (values[0] - values[1]) / values[1]
    elif operation in {"DIV", "RATIO"}:
        if values[1] == 0:
            v1._raise_validation(
                "divide_by_zero",
                "denominator must not be zero",
            )
        left_unit, right_unit = states[0].unit, states[1].unit
        if right_unit == "ratio":
            unit = left_unit
            metric = states[0].metric
            entity = states[0].entity
        elif (
            left_unit == right_unit
            or left_unit == "unknown"
            or right_unit == "unknown"
        ):
            unit = "ratio"
            metric = v1._shared_metadata(states, "metric")
            entity = v1._shared_metadata(states, "entity")
        else:
            v1._raise_validation(
                "unit_mismatch",
                "division arguments have incompatible known units",
            )
        value = values[0] / values[1]
    else:
        left, right = states
        if left.unit == "ratio" and right.unit == "ratio":
            unit = "ratio"
        elif left.unit == "ratio":
            unit = right.unit
        elif right.unit == "ratio":
            unit = left.unit
        else:
            v1._raise_validation(
                "unit_mismatch",
                "multiplication requires a known dimensionless argument",
            )
        value_states = tuple(
            state for state in states if state.unit != "ratio"
        )
        if len(value_states) == 1:
            metric = value_states[0].metric
            entity = value_states[0].entity
        value = values[0] * values[1]
    return v1._merge_state(
        value=value,
        unit=unit,
        states=states,
        metric=metric,
        entity=entity,
    )


def _reference_key(reference: object) -> tuple[str, str]:
    if isinstance(reference, StepRef):
        return "step", reference.step_id
    return "candidate", reference.candidate_id


def _validate_program_structure_v2(program: TypedProgram) -> None:
    if len(program.steps) > MAX_V2_PROGRAM_STEPS:
        v1._raise_validation(
            "budget_exceeded",
            "v2 program exceeds the five-step calibration budget",
        )
    fingerprints: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    step_by_id = {step.step_id: step for step in program.steps}
    for step in program.steps:
        references = tuple(_reference_key(item) for item in step.arguments)
        if len(references) != len(set(references)):
            v1._raise_validation(
                "invalid_program_schema",
                "a step cannot reuse the same operand reference",
            )
        fingerprint = (step.operation, references)
        if fingerprint in fingerprints:
            v1._raise_validation(
                "invalid_program_schema",
                "program contains a duplicate calculation step",
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
            "every program step must contribute to the final output",
        )


def _validate_program_shape_v2(
    program: TypedProgram,
    intent: FinancialQuestionIntentV2,
) -> None:
    output = program.steps[-1]
    if output.operation not in intent.allowed_output_operations:
        v1._raise_validation(
            "unsupported_operation",
            "output operation is outside the v2 intent family",
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
            "percent-change division numerator must reference a SUB step",
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
            "percent-change division must reuse the old operand as denominator",
        )


def _validate_and_execute_v2(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidate],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
) -> _ValidatedExecutionV2:
    try:
        intent = FinancialQuestionIntentV2.model_validate(
            intent.model_dump(mode="python")
        )
    except (AttributeError, ValidationError, ValueError) as exc:
        v1._raise_validation(
            "ambiguous_intent",
            "question intent does not satisfy the v2 runtime contract",
        )
        raise AssertionError from exc
    program = v1._parse_typed_program(planner_payload)
    candidate_by_id = v1._validated_candidates(tuple(candidates))
    candidate_ids, evidence_ids = v1._static_program_closure(
        program,
        candidate_by_id,
    )
    _validate_candidate_contracts_v2(
        candidate_ids=candidate_ids,
        candidate_by_id=candidate_by_id,
        admitted_evidence_ids=set(admitted_evidence_ids),
        intent=intent,
    )
    _validate_program_structure_v2(program)
    _validate_program_shape_v2(program, intent)

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
            step_states[step.step_id] = _execute_step_v2(
                operation=step.operation,
                states=states,
                intent=intent,
            )
    output_state = step_states[program.output_step_id]
    if (
        intent.requested_unit != "unknown"
        and output_state.unit != intent.requested_unit
    ):
        v1._raise_validation(
            "unit_mismatch",
            "program output unit does not match the v2 question intent",
        )
    validation_payload = {
        "admitted_evidence_ids": sorted(admitted_evidence_ids),
        "candidates": [
            candidate_by_id[candidate_id].model_dump(mode="json")
            for candidate_id in candidate_ids
        ],
        "intent": intent.model_dump(mode="json"),
        "program": program.model_dump(mode="json"),
        "validator_version": VALIDATOR_VERSION,
    }
    validated = ValidatedTypedProgramV2(
        program=program,
        candidate_ids=candidate_ids,
        evidence_ids=evidence_ids,
        validation_sha256=hashlib.sha256(
            v1._canonical_json_bytes(validation_payload)
        ).hexdigest(),
    )
    return _ValidatedExecutionV2(
        validated=validated,
        step_states=step_states,
        candidate_by_id=candidate_by_id,
    )


def _presentation_value(
    *,
    output: v1._ValueState,
    candidate_by_id: Mapping[str, NumericCandidate],
    requested_scale: FinancialScale,
) -> tuple[Decimal, bool, tuple[str, ...]]:
    if requested_scale in {"one", "unknown", "percent"}:
        return output.value, False, ()
    if requested_scale == "basis_point":
        if output.unit != "ratio":
            v1._raise_validation(
                "scale_mismatch",
                "basis-point presentation requires a ratio result",
            )
        return (
            output.value / _PRESENTATION_DIVISOR["basis_point"],
            True,
            (),
        )
    explicit_source_scales = {
        candidate_by_id[candidate_id].scale
        for candidate_id in output.candidate_ids
        if candidate_by_id[candidate_id].scale not in {"one", "unknown"}
    }
    if not explicit_source_scales:
        return (
            output.value,
            False,
            ("requested scale treated as evidence display scale",),
        )
    return (
        output.value / _PRESENTATION_DIVISOR[requested_scale],
        True,
        (),
    )


def validate_typed_program_v2(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidate],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
) -> ValidatedTypedProgramV2:
    return _validate_and_execute_v2(
        planner_payload=planner_payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=intent,
    ).validated


def compile_and_execute_typed_program_v2(
    *,
    planner_payload: object,
    candidates: Sequence[NumericCandidate],
    admitted_evidence_ids: set[str],
    intent: FinancialQuestionIntentV2,
) -> TypedProgramResultV2:
    execution = _validate_and_execute_v2(
        planner_payload=planner_payload,
        candidates=candidates,
        admitted_evidence_ids=admitted_evidence_ids,
        intent=intent,
    )
    program = execution.validated.program
    output = execution.step_states[program.output_step_id]
    presented, scale_applied, warnings = _presentation_value(
        output=output,
        candidate_by_id=execution.candidate_by_id,
        requested_scale=intent.requested_scale,
    )
    return TypedProgramResultV2(
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
        diagnostics=TypedProgramDiagnosticsV2(
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
    "INTENT_VERSION",
    "MAX_V2_PROGRAM_STEPS",
    "VALIDATOR_VERSION",
    "FinancialQuestionIntentV2",
    "OperationFamily",
    "TypedProgramDiagnosticsV2",
    "TypedProgramResultV2",
    "ValidatedTypedProgramV2",
    "allowed_outputs_for_family",
    "compile_and_execute_typed_program_v2",
    "validate_typed_program_v2",
]
