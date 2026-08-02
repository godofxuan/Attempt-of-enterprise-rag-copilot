from __future__ import annotations

import pytest

from app.external_datasets.finqa_numeric_evidence_v2 import (
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility_v3 import (
    build_role_candidate_compatibility_matrix_v3,
    verify_no_gold_runtime_inputs_v3,
)
from app.external_datasets.finqa_semantic_program_v3 import (
    SemanticProgramSkeletonV3,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)


def _candidate(year: int, value: int):
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=f"table_{year - 2016}",
        text=str(value),
        kind="table_cell",
        table_id="payments",
        row_header=str(year),
        column_header="Expected principal payment",
    )[0]


def _five_role_skeleton() -> SemanticProgramSkeletonV3:
    roles = [
        {
            "role_id": f"role-{index:02d}",
            "semantic_role": "component",
            "period_role": "none",
            "role_query": f"expected principal payment {year}",
            "expected_period": str(year),
        }
        for index, year in enumerate(range(2016, 2021), start=1)
    ]
    return SemanticProgramSkeletonV3.model_validate(
        {
            "roles": roles,
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "ADD",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                },
                {
                    "step_id": "step-02",
                    "operation": "ADD",
                    "arguments": [
                        {"step_id": "step-01"},
                        {"role_id": "role-03"},
                    ],
                },
                {
                    "step_id": "step-03",
                    "operation": "ADD",
                    "arguments": [
                        {"step_id": "step-02"},
                        {"role_id": "role-04"},
                    ],
                },
                {
                    "step_id": "step-04",
                    "operation": "ADD",
                    "arguments": [
                        {"step_id": "step-03"},
                        {"role_id": "role-05"},
                    ],
                },
            ],
            "output_step_id": "step-04",
        }
    )


def test_v3_role_queries_separate_same_semantic_role_by_period() -> None:
    candidates = tuple(
        _candidate(year, value)
        for year, value in zip(
            range(2016, 2021),
            (204079, 766451, 822690, 768588, 664995),
            strict=True,
        )
    )
    context = {
        candidate.evidence_id: (
            f"{candidate.row_header} | expected principal payment | "
            f"{candidate.raw_text}"
        )
        for candidate in candidates
    }
    question = "What was the total expected principal payment from 2016 to 2020?"

    matrix = build_role_candidate_compatibility_matrix_v3(
        question=question,
        skeleton=_five_role_skeleton(),
        candidates=candidates,
        admitted_evidence_ids=set(context),
        intent=extract_financial_question_intent_v2(question),
        evidence_context_by_id=context,
    )

    for index, candidate in enumerate(candidates, start=1):
        assert matrix.candidate_ids_for_role(
            f"role-{index:02d}"
        )[0] == candidate.candidate_id
    assert matrix.unique_exposed_candidate_count == 5
    assert verify_no_gold_runtime_inputs_v3()


@pytest.mark.parametrize(
    "role_query",
    [
        f"bind num-{'a' * 20}",
        "use table_3",
        "reuse step-01",
        "divide by const_100",
        '{"candidate_id":"hidden"}',
    ],
)
def test_v3_role_query_rejects_runtime_identifiers(role_query: str) -> None:
    payload = _five_role_skeleton().model_dump(mode="json")
    payload["roles"][0]["role_query"] = role_query

    with pytest.raises(ValueError):
        SemanticProgramSkeletonV3.model_validate(payload)


def test_v3_candidate_input_order_is_irrelevant() -> None:
    candidates = tuple(
        _candidate(year, value)
        for year, value in zip(
            range(2016, 2021),
            (204079, 766451, 822690, 768588, 664995),
            strict=True,
        )
    )
    context = {
        candidate.evidence_id: (
            f"{candidate.row_header} | expected principal payment | "
            f"{candidate.raw_text}"
        )
        for candidate in candidates
    }
    kwargs = {
        "question": "What was the total expected principal payment?",
        "skeleton": _five_role_skeleton(),
        "admitted_evidence_ids": set(context),
        "intent": extract_financial_question_intent_v2(
            "What was the total expected principal payment?"
        ),
        "evidence_context_by_id": context,
    }

    forward = build_role_candidate_compatibility_matrix_v3(
        candidates=candidates,
        **kwargs,
    )
    reverse = build_role_candidate_compatibility_matrix_v3(
        candidates=tuple(reversed(candidates)),
        **kwargs,
    )

    assert forward.role_allowlists == reverse.role_allowlists
    assert forward.matrix_sha256 == reverse.matrix_sha256
