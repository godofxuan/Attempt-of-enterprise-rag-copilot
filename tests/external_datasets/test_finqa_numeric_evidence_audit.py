from __future__ import annotations

from app.external_datasets.finqa_numeric_evidence_audit import (
    classify_operand_availability,
    parse_gold_operand_references,
)
from app.external_datasets.finqa_typed_program import (
    extract_numeric_candidates,
)


def _candidate(value: str, evidence_id: str):
    return extract_numeric_candidates(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=value,
        kind="table_cell",
        table_id="table-main",
        row_header="Metric",
        column_header="2020",
    )[0]


def test_gold_parser_separates_controlled_constants_from_evidence():
    operands = parse_gold_operand_references(
        "add(const_1, 10), divide(#0, const_m1)"
    )

    assert [(item.kind, str(item.value)) for item in operands] == [
        ("controlled_constant", "1"),
        ("evidence", "10"),
        ("controlled_constant", "-1"),
    ]


def test_gold_parser_ignores_valid_symbolic_table_selector():
    operands = parse_gold_operand_references(
        "table_average(expected life in years, none)"
    )

    assert operands == ()


def test_surface_scale_view_matches_without_mutating_normalized_value():
    operands = parse_gold_operand_references("add(12, const_1)")
    candidate = _candidate("$12 million", "table_1")

    categories = classify_operand_availability(
        operands,
        selected_candidates=(candidate,),
        gold_evidence_candidates=(candidate,),
    )

    assert categories == ("selected_surface_view", "controlled_constant")
    assert str(candidate.normalized_value) == "12000000"


def test_duplicate_operands_can_reuse_one_provenance_bound_candidate():
    operands = parse_gold_operand_references("subtract(5, 5)")
    selected = _candidate("5", "table_1")

    categories = classify_operand_availability(
        operands,
        selected_candidates=(selected,),
        gold_evidence_candidates=(selected,),
    )

    assert categories == ("selected_normalized", "selected_normalized")


def test_unselected_gold_value_is_classified_as_retrieval_missing():
    operands = parse_gold_operand_references("subtract(5, 5)")
    selected = _candidate("6", "table_1")
    gold = _candidate("5", "table_2")

    categories = classify_operand_availability(
        operands,
        selected_candidates=(selected,),
        gold_evidence_candidates=(gold,),
    )

    assert categories == ("retrieval_missing", "retrieval_missing")
