from __future__ import annotations

import json

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_semantic_calibration_run import (
    semantic_arm_order,
)
from app.external_datasets.finqa_semantic_demos import (
    FinQADemoSource,
    FinQAStructuralDemoIndex,
)
from app.external_datasets.finqa_semantic_planner import (
    LocalFinQASemanticPlanner,
)
from app.external_datasets.finqa_semantic_runtime import (
    evaluate_semantic_case,
)
from app.external_datasets.finqa_typed_retrospective import (
    refused_arm_evaluation,
)
from app.external_datasets.finqa_v23_calibration_run import (
    FinQAV23CalibrationCase,
)


def _case() -> FinQACase:
    table = [["", "2020", "2019"], ["Revenue", "120", "100"]]
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


def test_semantic_runtime_executes_three_arms_and_audits_demos() -> None:
    case = _case()
    source_e4 = FinQAV23CalibrationCase(
        case_id=case.id,
        diagnostic_category="fixture",
        selected_unit_ids=["table_1"],
        admitted_closure_unit_ids=["table_1"],
        gold_unit_ids=["table_1"],
        candidate_count_before_shortlist=2,
        candidate_count_after_shortlist=2,
        guard_scan_count=1,
        quarantined_unit_count=0,
        b0_stored=_refusal("B0_FREE_LITERAL"),
        b1_v22_stored=_refusal("B1_TYPED_SINGLE"),
        b1_v23_intervention=_refusal("B1_TYPED_SINGLE"),
    )
    demos = FinQAStructuralDemoIndex(
        [
            FinQADemoSource(
                case_id=f"train-{index}",
                question=f"What was the difference in revenue item {index}?",
                program="subtract(120, 100)",
            )
            for index in range(100)
        ],
        forbidden_case_ids={case.id},
    )
    skeleton = {
        "roles": [
            {
                "role_id": "role-01",
                "semantic_role": "comparison_left",
                "period_role": "none",
            },
            {
                "role_id": "role-02",
                "semantic_role": "comparison_right",
                "period_role": "none",
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
            }
        ],
        "output_step_id": "step-01",
    }

    def fake_chat(model, messages, *, response_format=None, think=None):
        payload = json.loads(messages[1]["content"])
        if "roles" in response_format["properties"]:
            return json.dumps(skeleton)
        candidates = payload["candidates"]
        ids = {
            item["raw_text"]: item["candidate_id"] for item in candidates
        }
        if "bindings" in response_format["properties"]:
            return json.dumps(
                {
                    "bindings": [
                        {
                            "role_id": "role-01",
                            "candidate_id": ids["120"],
                        },
                        {
                            "role_id": "role-02",
                            "candidate_id": ids["100"],
                        },
                    ]
                }
            )
        return json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step-01",
                        "operation": "SUB",
                        "arguments": [
                            {"candidate_id": ids["120"]},
                            {"candidate_id": ids["100"]},
                        ],
                    }
                ],
                "output_step_id": "step-01",
            }
        )

    row = evaluate_semantic_case(
        case=case,
        source_e4=source_e4,
        planner=LocalFinQASemanticPlanner(
            model="model",
            chat_fn=fake_chat,
        ),
        demo_index=demos,
        arm_order=semantic_arm_order(0),
    )

    assert row.b2_direct.strict_execution_match
    assert row.b3_roles.strict_execution_match
    assert row.b4_dynamic_demos.strict_execution_match
    assert row.b4_demo_count == 3
    assert row.b4_demo_payload_sha256 is not None
