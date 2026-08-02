from __future__ import annotations

from decimal import Decimal

from app.external_datasets.finqa_role_compatibility_audit_v2 import (
    build_oracle_semantic_program_v2,
)


def test_oracle_v2_removes_controlled_constants_from_evidence_roles() -> None:
    oracle = build_oracle_semantic_program_v2(
        question="What was the average value?",
        program="add(116, 109), divide(#0, const_2)",
    )

    assert oracle.capability_route == "TYPED_NUMERIC"
    assert oracle.skeleton is not None
    assert len(oracle.skeleton.roles) == 2
    assert len(oracle.skeleton.steps) == 2
    assert oracle.controlled_constant_ids == ("const_2",)
    assert (
        oracle.skeleton.steps[1].arguments[1].constant_id
        == "const_2"
    )


def test_oracle_v2_keeps_source_bound_constants_as_evidence_roles() -> None:
    oracle = build_oracle_semantic_program_v2(
        question="By what percentage can the line of credit increase?",
        program="subtract(const_7, const_5), divide(#0, const_5)",
        source_bound_constant_ids=frozenset({"const_5", "const_7"}),
    )

    assert oracle.controlled_constant_ids == ()
    assert tuple(item.value for item in oracle.evidence_targets) == (
        Decimal("7"),
        Decimal("5"),
    )
    assert oracle.skeleton is not None
    assert len(oracle.skeleton.roles) == 2


def test_oracle_v2_supports_five_steps() -> None:
    oracle = build_oracle_semantic_program_v2(
        question="What was the difference in percentage return?",
        program=(
            "subtract(96.50, const_100), divide(#0, const_100), "
            "subtract(150.30, const_100), divide(#2, const_100), "
            "subtract(#3, #1)"
        ),
    )

    assert oracle.skeleton is not None
    assert len(oracle.skeleton.steps) == 5
    assert len(oracle.skeleton.roles) == 2
    assert oracle.controlled_constant_ids == ("const_100",)


def test_oracle_v2_classifies_non_numeric_operation_routes() -> None:
    boolean = build_oracle_semantic_program_v2(
        question="Did the company outperform the index?",
        program="greater(178.93, 105.34)",
    )
    table = build_oracle_semantic_program_v2(
        question="What was the average expected life?",
        program="table_average(expected life in years, none)",
    )

    assert boolean.capability_route == "B0_BOOLEAN_COMPARISON_FALLBACK"
    assert table.capability_route == (
        "B0_SYMBOLIC_TABLE_AGGREGATION_FALLBACK"
    )
