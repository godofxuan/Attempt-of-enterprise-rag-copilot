import pytest

from app.evaluation.numeric_answer import (
    normalize_direct_answer,
    strict_execution_match,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,200.50", "1200.50"),
        ("12%", "0.12"),
        ("(25)", "-25"),
        ("yes", "yes"),
        (42, "42"),
    ],
)
def test_normalize_direct_answer_handles_financial_formats(
    raw: object,
    expected: str,
) -> None:
    assert str(normalize_direct_answer(raw)) == expected


@pytest.mark.parametrize(
    ("predicted", "gold"),
    [
        ("12%", 0.12),
        ("1,200", 1200),
        ("0.333333", 0.33333),
        ("YES", "yes"),
    ],
)
def test_strict_execution_match_accepts_equivalent_answers(
    predicted: object,
    gold: object,
) -> None:
    assert strict_execution_match(predicted, gold)


@pytest.mark.parametrize(
    ("predicted", "gold"),
    [
        ("12", 0.12),
        ("about 1200", 1200),
        ("10%", 0.11),
        ("yes", "no"),
        ("(25", -25),
    ],
)
def test_strict_execution_match_fails_closed(
    predicted: object,
    gold: object,
) -> None:
    assert not strict_execution_match(predicted, gold)
