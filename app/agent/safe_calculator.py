from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DecimalOperation = Literal["add", "subtract", "multiply", "divide"]
MAX_DECIMAL_PROGRAM_STEPS = 8
MAX_DECIMAL_MAGNITUDE = Decimal("1e18")
MAX_DECIMAL_LITERAL_CHARS = 64
MAX_DECIMAL_ADJUSTED_EXPONENT = 18
_STEP_REFERENCE = re.compile(r"#([0-9]+)")


class DecimalProgramStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: DecimalOperation
    arguments: tuple[str, str]


class DecimalProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[DecimalProgramStep] = Field(
        min_length=1,
        max_length=MAX_DECIMAL_PROGRAM_STEPS,
    )


@dataclass(frozen=True)
class DecimalProgramResult:
    value: Decimal
    step_values: tuple[Decimal, ...]


def execute_decimal_program(program: DecimalProgram) -> DecimalProgramResult:
    values: list[Decimal] = []
    with localcontext() as context:
        context.prec = 28
        for step in program.steps:
            left, right = (
                _resolve_argument(argument, values)
                for argument in step.arguments
            )
            if step.operation == "add":
                value = left + right
            elif step.operation == "subtract":
                value = left - right
            elif step.operation == "multiply":
                value = left * right
            else:
                if right == 0:
                    raise ValueError("decimal program cannot divide by zero")
                value = left / right
            if not _is_safe_decimal(value):
                raise ValueError("decimal program result is outside the safe range")
            values.append(value)
    return DecimalProgramResult(value=values[-1], step_values=tuple(values))


def _resolve_argument(argument: str, values: list[Decimal]) -> Decimal:
    reference = _STEP_REFERENCE.fullmatch(argument)
    if reference is not None:
        index = int(reference.group(1))
        if index >= len(values):
            raise ValueError("decimal program step reference must point backward")
        return values[index]
    if len(argument) > MAX_DECIMAL_LITERAL_CHARS:
        raise ValueError("decimal program argument is outside the safe range")
    try:
        value = Decimal(argument)
    except Exception as exc:
        raise ValueError("decimal program argument must be numeric") from exc
    if not _is_safe_decimal(value):
        raise ValueError("decimal program argument is outside the safe range")
    return value


def _is_safe_decimal(value: Decimal) -> bool:
    return bool(
        value.is_finite()
        and abs(value) <= MAX_DECIMAL_MAGNITUDE
        and (
            value == 0
            or abs(value.adjusted()) <= MAX_DECIMAL_ADJUSTED_EXPONENT
        )
    )


__all__ = [
    "DecimalOperation",
    "DecimalProgram",
    "DecimalProgramResult",
    "DecimalProgramStep",
    "MAX_DECIMAL_MAGNITUDE",
    "MAX_DECIMAL_ADJUSTED_EXPONENT",
    "MAX_DECIMAL_LITERAL_CHARS",
    "MAX_DECIMAL_PROGRAM_STEPS",
    "execute_decimal_program",
]
