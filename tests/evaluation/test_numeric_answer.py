import pytest

from app.evaluation.numeric_answer import (
    normalize_direct_answer,
    presentation_tolerance_match,
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


@pytest.mark.parametrize(
    ("predicted", "gold", "expected"),
    [
        ("52.8%", 0.52772, True),
        ("1.16", 1.15615, True),
        ("33%", 0.3385, False),
        ("-20%", 0.19495, False),
        ("16750000", 16750000.0, True),
    ],
)
def test_presentation_tolerance_is_explicit_and_sign_sensitive(
    predicted: object,
    gold: object,
    expected: bool,
) -> None:
    assert presentation_tolerance_match(predicted, gold) is expected
