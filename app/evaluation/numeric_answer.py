from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import TypeAlias


NormalizedAnswer: TypeAlias = Decimal | str

_NUMERIC = re.compile(
    r"^\s*(?P<open>\()?\s*"
    r"(?P<currency>[$])?\s*"
    r"(?P<number>[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
    r"(?:\.[0-9]+)?)\s*"
    r"(?P<percent>%)?\s*(?P<close>\))?\s*$"
)
_QUANTUM = Decimal("0.00001")


def normalize_direct_answer(value: object) -> NormalizedAnswer:
    if isinstance(value, bool) or value is None:
        raise ValueError("answer must be a finite number or supported label")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return _decimal_from_text(str(value))
    if not isinstance(value, str):
        raise ValueError("answer must be a finite number or supported label")
    text = value.strip()
    canonical = text.casefold()
    if canonical in {"yes", "no"}:
        return canonical
    match = _NUMERIC.fullmatch(text)
    if match is None:
        raise ValueError("answer must contain only one final numeric value")
    if bool(match.group("open")) != bool(match.group("close")):
        raise ValueError("answer has unbalanced accounting parentheses")
    number = _decimal_from_text(match.group("number").replace(",", ""))
    if match.group("open"):
        if number < 0:
            raise ValueError("answer must not combine two negative notations")
        number = -number
    if match.group("percent"):
        number /= Decimal(100)
    return number


def strict_execution_match(predicted: object, gold: object) -> bool:
    try:
        normalized_predicted = normalize_direct_answer(predicted)
        normalized_gold = normalize_direct_answer(gold)
    except ValueError:
        return False
    if isinstance(normalized_predicted, str) or isinstance(normalized_gold, str):
        return normalized_predicted == normalized_gold
    return normalized_predicted.quantize(
        _QUANTUM,
        rounding=ROUND_HALF_EVEN,
    ) == normalized_gold.quantize(
        _QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _decimal_from_text(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("answer is not a valid decimal") from exc
    if not result.is_finite():
        raise ValueError("answer must be finite")
    return result


__all__ = [
    "NormalizedAnswer",
    "normalize_direct_answer",
    "strict_execution_match",
]
