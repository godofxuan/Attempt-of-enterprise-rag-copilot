from __future__ import annotations

import ast
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
_DECIMAL_EXPRESSION = re.compile(r"[0-9eE+\-*/().\s]+")
MAX_DECIMAL_EXPRESSION_CHARS = 256
MAX_DECIMAL_EXPRESSION_NODES = 32
MAX_DECIMAL_EXPRESSION_DEPTH = 8


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


def execute_decimal_expression(expression: str) -> Decimal:
    source = expression.strip()
    if (
        not source
        or len(source) > MAX_DECIMAL_EXPRESSION_CHARS
        or _DECIMAL_EXPRESSION.fullmatch(source) is None
    ):
        raise ValueError("decimal expression contains unsupported input")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError("decimal expression is invalid") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_DECIMAL_EXPRESSION_NODES:
        raise ValueError("decimal expression exceeds the node budget")
    with localcontext() as context:
        context.prec = 28
        return _evaluate_expression_node(tree.body, source, depth=1)


def _evaluate_expression_node(
    node: ast.AST,
    source: str,
    *,
    depth: int,
) -> Decimal:
    if depth > MAX_DECIMAL_EXPRESSION_DEPTH:
        raise ValueError("decimal expression exceeds the depth budget")
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        literal = ast.get_source_segment(source, node)
        if literal is None:
            raise ValueError("decimal expression literal is unavailable")
        return _parse_decimal_literal(literal)
    if isinstance(node, ast.UnaryOp) and isinstance(
        node.op,
        (ast.UAdd, ast.USub),
    ):
        value = _evaluate_expression_node(node.operand, source, depth=depth + 1)
        result = value if isinstance(node.op, ast.UAdd) else -value
    elif isinstance(node, ast.BinOp) and isinstance(
        node.op,
        (ast.Add, ast.Sub, ast.Mult, ast.Div),
    ):
        left = _evaluate_expression_node(node.left, source, depth=depth + 1)
        right = _evaluate_expression_node(node.right, source, depth=depth + 1)
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        else:
            if right == 0:
                raise ValueError("decimal expression cannot divide by zero")
            result = left / right
    else:
        raise ValueError("decimal expression contains an unsupported operation")
    if not _is_safe_decimal(result):
        raise ValueError("decimal expression result is outside the safe range")
    return result


def _resolve_argument(argument: str, values: list[Decimal]) -> Decimal:
    reference = _STEP_REFERENCE.fullmatch(argument)
    if reference is not None:
        index = int(reference.group(1))
        if index >= len(values):
            raise ValueError("decimal program step reference must point backward")
        return values[index]
    return _parse_decimal_literal(argument)


def _parse_decimal_literal(argument: str) -> Decimal:
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
    "MAX_DECIMAL_EXPRESSION_CHARS",
    "MAX_DECIMAL_EXPRESSION_DEPTH",
    "MAX_DECIMAL_EXPRESSION_NODES",
    "MAX_DECIMAL_LITERAL_CHARS",
    "MAX_DECIMAL_PROGRAM_STEPS",
    "execute_decimal_expression",
    "execute_decimal_program",
]
