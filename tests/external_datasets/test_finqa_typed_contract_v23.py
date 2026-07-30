from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_typed_contract_v2 import (
    compile_and_execute_typed_program_v2,
)
from app.external_datasets.finqa_typed_contract_v23 import (
    compile_and_execute_typed_program_v23,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_planner_v23 import (
    LocalFinQATypedProgramPlannerV23,
)
from app.external_datasets.finqa_typed_program import (
    TypedProgramValidationError,
)


def _candidate(text: str, evidence_id: str) -> NumericCandidateV2:
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=text,
        kind="table_cell",
        table_id="table-main",
        row_header="Revenue",
        column_header="2020",
    )[0]


def _payload(left: NumericCandidateV2, right: NumericCandidateV2) -> dict:
    return {
        "dsl_version": "finqa_typed_financial_dsl_v1",
        "steps": [
            {
                "step_id": "step-01",
                "operation": "SUB",
                "arguments": [
                    {"candidate_id": left.candidate_id},
                    {"candidate_id": right.candidate_id},
                ],
            }
        ],
        "output_step_id": "step-01",
    }


def test_v23_accepts_source_bound_v2_candidates_but_v22_rejects_them():
    left = _candidate("120", "table_1")
    right = _candidate("100", "table_2")
    intent = extract_financial_question_intent_v2(
        "What was the difference in revenue?"
    )

    result = compile_and_execute_typed_program_v23(
        planner_payload=_payload(left, right),
        candidates=(left, right),
        admitted_evidence_ids={"table_1", "table_2"},
        intent=intent,
    )

    assert result.value == Decimal("20")
    assert result.validator_version == "finqa_typed_program_validator_v2_3"
    with pytest.raises(TypedProgramValidationError) as error:
        compile_and_execute_typed_program_v2(
            planner_payload=_payload(left, right),
            candidates=(left, right),
            admitted_evidence_ids={"table_1", "table_2"},
            intent=intent,
        )
    assert error.value.reason == "missing_provenance"


def test_v23_rejects_tampered_v2_candidate_identity():
    left = _candidate("120", "table_1")
    right = _candidate("100", "table_2")
    tampered = left.model_copy(update={"candidate_id": right.candidate_id})

    with pytest.raises(TypedProgramValidationError) as error:
        compile_and_execute_typed_program_v23(
            planner_payload=_payload(tampered, right),
            candidates=(tampered, right),
            admitted_evidence_ids={"table_1", "table_2"},
            intent=extract_financial_question_intent_v2(
                "What was the difference in revenue?"
            ),
        )

    assert error.value.reason in {"missing_provenance", "duplicate_candidate"}


def test_v23_reconstructs_narrative_parenthetical_policy():
    candidate = extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id="text_1",
        text="($198 million)",
        kind="text",
    )[0]
    other = _candidate("$100 million", "table_2")

    result = compile_and_execute_typed_program_v23(
        planner_payload=_payload(candidate, other),
        candidates=(candidate, other),
        admitted_evidence_ids={"text_1", "table_2"},
        intent=extract_financial_question_intent_v2(
            "What was the difference in revenue?"
        ),
    )

    assert result.value == Decimal("98000000")


def test_v23_planner_uses_v2_candidates_through_host_compiler():
    left = _candidate("120", "table_1")
    right = _candidate("100", "table_2")

    def fake_chat(model, messages, *, response_format=None, think=None):
        assert model == "model"
        return json.dumps(
            {
                "template": "SUB",
                "operand_candidate_ids": [
                    left.candidate_id,
                    right.candidate_id,
                ],
            }
        )

    result = LocalFinQATypedProgramPlannerV23(
        model="model",
        chat_fn=fake_chat,
    ).plan_and_execute(
        question="What was the difference in revenue?",
        candidates=(left, right),
        admitted_evidence_ids={"table_1", "table_2"},
    )

    assert result.execution.value == Decimal("20")
    assert result.planner_version == "finqa_typed_planner_v2_3"
