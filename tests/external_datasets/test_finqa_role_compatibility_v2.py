from __future__ import annotations

from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    build_role_candidate_compatibility_matrix_v2,
    route_finqa_numeric_capability,
    verify_no_gold_runtime_inputs_v2,
    verify_role_exact_parser_enforcement_v2,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)


def _candidate(
    text: str,
    evidence_id: str,
    row_header: str,
) -> NumericCandidateV2:
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=text,
        kind="table_cell",
        table_id="table-main",
        row_header=row_header,
        column_header="2020",
    )[0]


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "value",
                    "period_role": "target",
                }
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "DIV",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"constant_id": "const_2"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def test_v2_ranks_from_complete_admitted_pool_before_any_global_top24() -> None:
    noise = tuple(
        _candidate(str(index + 1), f"table_{index}", f"Noise {index}")
        for index in range(30)
    )
    relevant = _candidate("120", "table_30", "Annual revenue creation")
    candidates = (*noise, relevant)
    context = {
        candidate.evidence_id: (
            f"{candidate.row_header} | 2020 | {candidate.raw_text}"
        )
        for candidate in candidates
    }

    matrix = build_role_candidate_compatibility_matrix_v2(
        question="What was annual revenue creation in 2020 divided by two?",
        skeleton=_skeleton(),
        candidates=candidates,
        admitted_evidence_ids=set(context),
        intent=extract_financial_question_intent_v2(
            "What was annual revenue creation in 2020 divided by two?"
        ),
        evidence_context_by_id=context,
    )

    assert matrix.source_candidate_count == 31
    assert relevant.candidate_id in matrix.candidate_ids_for_role("role-01")
    assert len(matrix.candidate_ids_for_role("role-01")) == 8


def test_v2_candidate_input_order_is_irrelevant() -> None:
    first = _candidate("120", "table_1", "Revenue")
    second = _candidate("100", "table_2", "Revenue")
    context = {
        "table_1": "Revenue | 2020 | 120",
        "table_2": "Revenue | 2020 | 100",
    }
    kwargs = {
        "question": "What was revenue in 2020 divided by two?",
        "skeleton": _skeleton(),
        "admitted_evidence_ids": set(context),
        "intent": extract_financial_question_intent_v2(
            "What was revenue in 2020 divided by two?"
        ),
        "evidence_context_by_id": context,
    }

    forward = build_role_candidate_compatibility_matrix_v2(
        candidates=(first, second),
        **kwargs,
    )
    reverse = build_role_candidate_compatibility_matrix_v2(
        candidates=(second, first),
        **kwargs,
    )

    assert forward.role_allowlists == reverse.role_allowlists
    assert forward.matrix_sha256 == reverse.matrix_sha256


def test_capability_router_fails_over_unsupported_operation_classes() -> None:
    assert route_finqa_numeric_capability(
        "Did the company outperform the market index?"
    ) == "B0_BOOLEAN_COMPARISON_FALLBACK"
    assert route_finqa_numeric_capability(
        "What was the average expected life for the three year period?"
    ) == "B0_SYMBOLIC_TABLE_AGGREGATION_FALLBACK"
    assert route_finqa_numeric_capability(
        "What was the difference in revenue?"
    ) == "TYPED_NUMERIC"
    assert route_finqa_numeric_capability(
        "By how much did the weighted average exercise price increase "
        "from 2005 to 2007?"
    ) == "TYPED_NUMERIC"
    assert verify_no_gold_runtime_inputs_v2()
    assert verify_role_exact_parser_enforcement_v2()


def test_v2_normalizes_direct_comparison_year_direction() -> None:
    old = extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id="table_1",
        text="133",
        kind="table_cell",
        table_id="table-main",
        row_header="Rent expense",
        column_header="2012",
    )[0]
    new = extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id="table_2",
        text="137",
        kind="table_cell",
        table_id="table-main",
        row_header="Rent expense",
        column_header="2013",
    )[0]
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "new_value",
                    "period_role": "end",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "old_value",
                    "period_role": "start",
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "PERCENT_CHANGE",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )
    question = "What was the growth rate in 2013 compared to 2012?"
    context = {
        "table_1": "Rent expense | 2012 | 133",
        "table_2": "Rent expense | 2013 | 137",
    }

    matrix = build_role_candidate_compatibility_matrix_v2(
        question=question,
        skeleton=skeleton,
        candidates=(old, new),
        admitted_evidence_ids=set(context),
        intent=extract_financial_question_intent_v2(question),
        evidence_context_by_id=context,
    )

    assert matrix.role_allowlists[0].expected_period == "2013"
    assert matrix.role_allowlists[1].expected_period == "2012"
    assert matrix.candidate_ids_for_role("role-01") == (new.candidate_id,)
    assert matrix.candidate_ids_for_role("role-02") == (old.candidate_id,)
