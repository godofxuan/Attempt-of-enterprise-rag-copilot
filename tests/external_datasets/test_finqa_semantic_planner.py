from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    extract_numeric_candidates_v2,
)
from app.external_datasets.finqa_semantic_demos import (
    FinQAStructuralDemo,
)
from app.external_datasets.finqa_semantic_planner import (
    LocalFinQASemanticPlanner,
    SemanticPlannerProtocolError,
)
from app.external_datasets.finqa_semantic_program import (
    SemanticProgramSkeleton,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
def _candidate(
    text: str,
    evidence_id: str,
    column: str,
) -> NumericCandidateV2:
    return extract_numeric_candidates_v2(
        source_id="report.pdf",
        evidence_id=evidence_id,
        text=text,
        kind="table_cell",
        table_id="table-main",
        row_header="Revenue",
        column_header=column,
    )[0]


def _skeleton_payload() -> dict:
    return {
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


def test_direct_multi_step_planner_executes_percent_change() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")

    def fake_chat(model, messages, *, response_format=None, think=None):
        return json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-01",
                        "operation": "SUB",
                        "arguments": [
                            {"candidate_id": new.candidate_id},
                            {"candidate_id": old.candidate_id},
                        ],
                    },
                    {
                        "step_id": "step-02",
                        "operation": "DIV",
                        "arguments": [
                            {"step_id": "step-01"},
                            {"candidate_id": old.candidate_id},
                        ],
                    },
                ],
                "output_step_id": "step-02",
            }
        )

    result = LocalFinQASemanticPlanner(
        model="model",
        chat_fn=fake_chat,
    ).plan_direct(
        question="What was the percentage change from 2019 to 2020?",
        candidates=(new, old),
        admitted_evidence_ids={"table_1", "table_2"},
        intent=extract_financial_question_intent_v2(
            "What was the percentage change from 2019 to 2020?"
        ),
        evidence_context_by_id={
            "table_1": "Revenue | 2020 | 120",
            "table_2": "Revenue | 2019 | 100",
        },
    )

    assert result.execution.value == Decimal("0.2")
    assert len(result.program.steps) == 2
    assert result.generation_calls == 1


def test_role_decomposition_binds_then_executes() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")

    def fake_chat(model, messages, *, response_format=None, think=None):
        if "roles" in response_format["properties"]:
            return json.dumps(_skeleton_payload())
        return json.dumps(
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
        )

    result = LocalFinQASemanticPlanner(
        model="model",
        chat_fn=fake_chat,
    ).plan_decomposed(
        question="What was the percentage change from 2019 to 2020?",
        candidates=(new, old),
        admitted_evidence_ids={"table_1", "table_2"},
        intent=extract_financial_question_intent_v2(
            "What was the percentage change from 2019 to 2020?"
        ),
        evidence_context_by_id={
            "table_1": "Revenue | 2020 | 120",
            "table_2": "Revenue | 2019 | 100",
        },
    )

    assert result.execution.value == Decimal("0.2")
    assert result.skeleton is not None
    assert result.generation_calls == 2


def test_dynamic_demo_payload_is_hash_accounted() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")
    demo = FinQAStructuralDemo(
        question_template=(
            "What was the percentage change from <NUM> to <NUM>?"
        ),
        skeleton=SemanticProgramSkeleton.model_validate(
            _skeleton_payload()
        ),
    )

    def fake_chat(model, messages, *, response_format=None, think=None):
        if "roles" in response_format["properties"]:
            payload = json.loads(messages[1]["content"])
            assert len(payload["dynamic_structural_demonstrations"]) == 1
            return json.dumps(_skeleton_payload())
        return json.dumps(
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
        )

    result = LocalFinQASemanticPlanner(
        model="model",
        chat_fn=fake_chat,
    ).plan_decomposed(
        question="What was the percentage change from 2019 to 2020?",
        candidates=(new, old),
        admitted_evidence_ids={"table_1", "table_2"},
        intent=extract_financial_question_intent_v2(
            "What was the percentage change from 2019 to 2020?"
        ),
        evidence_context_by_id={
            "table_1": "Revenue | 2020 | 120",
            "table_2": "Revenue | 2019 | 100",
        },
        demonstrations=(demo,),
    )

    assert result.demonstration_count == 1
    assert result.demonstration_payload_sha256 is not None


def test_role_planner_fails_closed_on_nonallowlisted_binding() -> None:
    new = _candidate("120", "table_1", "2020")
    old = _candidate("100", "table_2", "2019")

    def fake_chat(model, messages, *, response_format=None, think=None):
        if "roles" in response_format["properties"]:
            return json.dumps(_skeleton_payload())
        return json.dumps(
            {
                "bindings": [
                    {
                        "role_id": "role-01",
                        "candidate_id": "num-" + "f" * 20,
                    },
                    {
                        "role_id": "role-02",
                        "candidate_id": old.candidate_id,
                    },
                ]
            }
        )

    with pytest.raises(SemanticPlannerProtocolError):
        LocalFinQASemanticPlanner(
            model="model",
            chat_fn=fake_chat,
            max_attempts=1,
        ).plan_decomposed(
            question="What was the percentage change from 2019 to 2020?",
            candidates=(new, old),
            admitted_evidence_ids={"table_1", "table_2"},
            intent=extract_financial_question_intent_v2(
                "What was the percentage change from 2019 to 2020?"
            ),
            evidence_context_by_id={
                "table_1": "Revenue | 2020 | 120",
                "table_2": "Revenue | 2019 | 100",
            },
        )
