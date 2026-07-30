from __future__ import annotations

import json

import pytest

from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility import (
    build_role_candidate_compatibility_matrix,
    parse_role_bindings_by_role,
    role_binding_response_format_by_role,
    verify_role_exact_parser_enforcement,
)
from app.external_datasets.finqa_semantic_program import (
    SemanticProgramSkeleton,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)


QUESTION = "What was the percentage change in revenue from 2019 to 2020?"


def _candidate(
    text: str,
    evidence_id: str,
    column: str,
    *,
    row: str = "Revenue",
) -> NumericCandidateV2:
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=text,
        kind="table_cell",
        table_id="table-main",
        row_header=row,
        column_header=column,
    )[0]


def _skeleton(
    *,
    new_period_role: str = "end",
    old_period_role: str = "start",
) -> SemanticProgramSkeleton:
    return SemanticProgramSkeleton.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "new_value",
                    "period_role": new_period_role,
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "old_value",
                    "period_role": old_period_role,
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                },
                {
                    "step_id": "step-02",
                    "operation": "DIV",
                    "arguments": [
                        {"step_id": "step-01"},
                        {"role_id": "role-02"},
                    ],
                },
            ],
            "output_step_id": "step-02",
        }
    )


def _matrix(
    candidates: tuple[NumericCandidateV2, ...],
):
    return build_role_candidate_compatibility_matrix(
        question=QUESTION,
        skeleton=_skeleton(),
        candidates=candidates,
        admitted_evidence_ids={
            candidate.evidence_id for candidate in candidates
        },
        intent=extract_financial_question_intent_v2(QUESTION),
        evidence_context_by_id={
            candidate.evidence_id: (
                f"{candidate.row_header} | {candidate.column_header} | "
                f"{candidate.raw_text}"
            )
            for candidate in sorted(
                candidates,
                key=lambda item: item.evidence_id,
            )
        },
    )


def test_period_roles_receive_distinct_allowlists_and_keep_unknown() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")
    unknown = _candidate("110", "table_3", "Current")

    matrix = _matrix((new, old, unknown))

    assert matrix.candidate_ids_for_role("role-01") == (
        new.candidate_id,
        unknown.candidate_id,
    )
    assert matrix.candidate_ids_for_role("role-02") == (
        old.candidate_id,
        unknown.candidate_id,
    )
    assert matrix.role_allowlists[0].hard_compatible_candidate_count == 2
    assert matrix.role_allowlists[1].hard_compatible_candidate_count == 2


def test_zero_denominator_is_removed_without_removing_zero_numerator() -> None:
    new_zero = _candidate("0", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")

    matrix = _matrix((new_zero, old))

    assert matrix.candidate_ids_for_role("role-01") == (
        new_zero.candidate_id,
    )
    assert matrix.candidate_ids_for_role("role-02") == (old.candidate_id,)


def test_candidate_input_order_does_not_change_matrix() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")
    unknown = _candidate("110", "table_3", "Current")

    forward = _matrix((new, old, unknown))
    reverse = _matrix((unknown, old, new))

    assert forward.role_allowlists == reverse.role_allowlists
    assert forward.matrix_sha256 == reverse.matrix_sha256


def test_non_admitted_candidate_fails_closed() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")

    with pytest.raises(ValueError, match="non-admitted"):
        build_role_candidate_compatibility_matrix(
            question=QUESTION,
            skeleton=_skeleton(),
            candidates=(new, old),
            admitted_evidence_ids={"table_1"},
            intent=extract_financial_question_intent_v2(QUESTION),
            evidence_context_by_id={"table_1": "Revenue | 2020 | 120"},
        )


def test_contradictory_temporal_role_fails_before_ranking() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")

    with pytest.raises(ValueError, match="new_value"):
        build_role_candidate_compatibility_matrix(
            question=QUESTION,
            skeleton=_skeleton(new_period_role="start"),
            candidates=(new, old),
            admitted_evidence_ids={"table_1", "table_2"},
            intent=extract_financial_question_intent_v2(QUESTION),
            evidence_context_by_id={
                "table_1": "Revenue | 2020 | 120",
                "table_2": "Revenue | 2019 | 100",
            },
        )


def test_schema_and_parser_enforce_each_role_allowlist() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")
    matrix = _matrix((new, old))
    schema = role_binding_response_format_by_role(matrix)
    alternatives = schema["properties"]["bindings"]["items"]["anyOf"]

    assert alternatives[0]["properties"]["candidate_id"]["enum"] == [
        new.candidate_id
    ]
    assert alternatives[1]["properties"]["candidate_id"]["enum"] == [
        old.candidate_id
    ]

    valid = parse_role_bindings_by_role(
        json.dumps(
            {
                "bindings": [
                    {
                        "role_id": "role-01",
                        "candidate_id": new.candidate_id,
                    },
                    {
                        "role_id": "role-02",
                        "candidate_id": old.candidate_id,
                    },
                ]
            }
        ),
        matrix=matrix,
    )
    assert len(valid.bindings) == 2

    with pytest.raises(ValueError, match="role-specific"):
        parse_role_bindings_by_role(
            json.dumps(
                {
                    "bindings": [
                        {
                            "role_id": "role-01",
                            "candidate_id": old.candidate_id,
                        },
                        {
                            "role_id": "role-02",
                            "candidate_id": old.candidate_id,
                        },
                    ]
                }
            ),
            matrix=matrix,
        )


def test_runtime_parser_enforcement_self_check() -> None:
    assert verify_role_exact_parser_enforcement()
