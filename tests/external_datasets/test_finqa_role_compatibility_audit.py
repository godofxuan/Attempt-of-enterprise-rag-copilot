from __future__ import annotations

from app.external_datasets.finqa_role_compatibility_audit import (
    parse_gold_role_targets,
    verify_no_gold_runtime_input,
)


def test_gold_role_target_parser_matches_semantic_role_deduplication() -> None:
    targets = parse_gold_role_targets(
        "subtract(120, 100), divide(#0, 100), multiply(#1, const_100)"
    )

    assert [
        (item.role_id, item.kind, str(item.value))
        for item in targets
    ] == [
        ("role-01", "evidence", "120"),
        ("role-02", "evidence", "100"),
        ("role-03", "controlled_constant", "100"),
    ]


def test_gold_role_target_parser_preserves_symbolic_diagnostic() -> None:
    targets = parse_gold_role_targets("table_average(expected life in years)")

    assert len(targets) == 1
    assert targets[0].kind == "symbolic"
    assert targets[0].value is None


def test_runtime_compatibility_api_has_no_gold_input() -> None:
    assert verify_no_gold_runtime_input()
