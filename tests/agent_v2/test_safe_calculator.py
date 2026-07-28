from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agent.safe_calculator import (
    DecimalProgram,
    execute_decimal_expression,
    execute_decimal_program,
)


def test_decimal_program_executes_references_without_eval() -> None:
    program = DecimalProgram.model_validate(
        {
            "steps": [
                {"operation": "subtract", "arguments": ["1703", "1371"]},
                {"operation": "divide", "arguments": ["#0", "1703"]},
            ]
        }
    )

    result = execute_decimal_program(program)

    assert result.value == Decimal("332") / Decimal("1703")
    assert result.step_values == (
        Decimal("332"),
        Decimal("332") / Decimal("1703"),
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["#0", "1"], "point backward"),
        (["1", "0"], "divide by zero"),
        (["__import__('os')", "1"], "must be numeric"),
        (["1e19", "1"], "outside the safe range"),
        (["1e-999999", "1"], "outside the safe range"),
    ],
)
def test_decimal_program_fails_closed_on_unsafe_arguments(
    arguments: list[str],
    message: str,
) -> None:
    program = DecimalProgram.model_validate(
        {
            "steps": [
                {"operation": "divide", "arguments": arguments},
            ]
        }
    )

    with pytest.raises(ValueError, match=message):
        execute_decimal_program(program)


def test_decimal_program_rejects_extra_fields_and_step_overflow() -> None:
    step = {"operation": "add", "arguments": ["1", "2"]}

    with pytest.raises(ValidationError):
        DecimalProgram.model_validate(
            {"steps": [{**step, "expression": "arbitrary code"}]}
        )
    with pytest.raises(ValidationError):
        DecimalProgram.model_validate({"steps": [step] * 9})


def test_decimal_expression_executes_financial_arithmetic() -> None:
    result = execute_decimal_expression("(1703 - 1371) / 1703")

    assert result == Decimal("332") / Decimal("1703")


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('whoami')",
        "evidence_01 / evidence_02",
        "2 ** 8",
        "[1, 2][0]",
        "1 / 0",
        "1e-999999 / 1",
    ],
)
def test_decimal_expression_rejects_non_arithmetic_or_unsafe_input(
    expression: str,
) -> None:
    with pytest.raises(ValueError):
        execute_decimal_expression(expression)
