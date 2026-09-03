import json

from app.evaluation.query_expansion import validate_query_expansion


def test_expansion_accepts_two_short_distinct_intent_preserving_queries() -> None:
    result = validate_query_expansion(
        original_query="How do I change a Wix plan in 2024?",
        raw_output=json.dumps(
            {"queries": ["Wix 2024 change subscription plan", "Wix plan upgrade options 2024"]}
        ),
    )
    assert result.accepted is True
    assert result.queries[0].startswith("Wix")


def test_expansion_rejects_entity_or_number_drop() -> None:
    result = validate_query_expansion(
        original_query="How do I change a Wix plan in 2024?",
        raw_output=json.dumps(
            {"queries": ["change subscription plan", "subscription upgrade options"]}
        ),
    )
    assert result.accepted is False
    assert result.rejection_reason == "protected_entity_or_number_dropped"


def test_expansion_rejects_duplicate_or_original_query() -> None:
    result = validate_query_expansion(
        original_query="Wix plan change",
        raw_output=json.dumps(
            {"queries": ["Wix plan change", "Wix plan change"]}
        ),
    )
    assert result.rejection_reason == "duplicate_or_original_query"


def test_expansion_rejects_non_json() -> None:
    assert validate_query_expansion(original_query="test", raw_output="not json").rejection_reason == "invalid_json"
