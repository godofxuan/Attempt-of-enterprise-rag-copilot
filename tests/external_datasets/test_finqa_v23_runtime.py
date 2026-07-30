from __future__ import annotations

import json

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
)
from app.external_datasets.finqa_typed_planner_v23 import (
    LocalFinQATypedProgramPlannerV23,
)
from app.external_datasets.finqa_typed_retrospective import (
    refused_arm_evaluation,
)
from app.external_datasets.finqa_v23_runtime import evaluate_v23_case


def _case() -> FinQACase:
    table = [
        ["", "2020", "2019"],
        ["Revenue", "120", "100"],
    ]
    return FinQACase.model_validate(
        {
            "pre_text": ["Revenue changed."],
            "post_text": ["Final note."],
            "filename": "report.pdf",
            "table_ori": table,
            "table": table,
            "qa": {
                "question": "What was the difference in revenue?",
                "answer": "20",
                "explanation": "",
                "ann_table_rows": [1],
                "ann_text_rows": [],
                "steps": [],
                "program": "subtract(120, 100)",
                "gold_inds": {"table_1": "synthetic evidence"},
                "exe_ans": 20,
                "tfidftopn": {},
                "program_re": "subtract(120, 100)",
                "model_input": [],
            },
            "id": "report.pdf-1",
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


def _refusal(arm_id: str):
    return refused_arm_evaluation(
        arm_id=arm_id,
        failure_reason="fixture",
        generation_calls=0,
        compiler_calls=0,
        generated_program_count=0,
        latency_ms=1,
        candidate_count=0,
    )


def test_v23_runtime_closes_guards_shortlists_and_executes():
    case = _case()
    source = FinQATypedCalibrationRunCase(
        case_id=case.id,
        cohort="calibration",
        diagnostic_category="fixture",
        selected_unit_ids=["table_1"],
        gold_unit_ids=["table_1"],
        b0=_refusal("B0_FREE_LITERAL"),
        b1_v1=_refusal("B1_TYPED_SINGLE"),
        b1_v2=_refusal("B1_TYPED_SINGLE"),
    )

    def fake_chat(model, messages, *, response_format=None, think=None):
        payload = json.loads(messages[1]["content"])
        ids = {
            item["raw_text"]: item["candidate_id"]
            for item in payload["candidates"]
        }
        return json.dumps(
            {
                "template": "SUB",
                "operand_candidate_ids": [ids["120"], ids["100"]],
            }
        )

    row = evaluate_v23_case(
        case=case,
        source=source,
        planner=LocalFinQATypedProgramPlannerV23(
            model="model",
            chat_fn=fake_chat,
        ),
    )

    assert row.guard_scan_count == len(row.admitted_closure_unit_ids)
    assert row.candidate_count_before_shortlist >= 2
    assert row.candidate_count_after_shortlist >= 2
    assert row.b1_v23_intervention.strict_execution_match
    assert row.b1_v23_intervention.grounded_execution_match
