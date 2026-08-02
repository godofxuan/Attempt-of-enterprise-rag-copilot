from __future__ import annotations

from app.external_datasets.finqa_role_query_planner_v1 import (
    plan_role_queries_from_question,
    verify_question_only_role_query_planner,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


def _skeleton(roles: list[dict]) -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": roles,
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "DIV",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )


def test_question_only_planner_assigns_percent_change_periods() -> None:
    skeleton = _skeleton(
        [
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
        ]
    )

    planned = plan_role_queries_from_question(
        question=(
            "What was the percentage change in unrecognized tax benefits "
            "from 2014 to 2015?"
        ),
        skeleton=skeleton,
    )

    assert planned.roles[0].expected_period == "2015"
    assert planned.roles[1].expected_period == "2014"
    assert "unrecognized" in planned.roles[0].role_query
    assert verify_question_only_role_query_planner()


def test_question_only_planner_separates_ratio_anchors() -> None:
    skeleton = _skeleton(
        [
            {
                "role_id": "role-01",
                "semantic_role": "part",
                "period_role": "none",
            },
            {
                "role_id": "role-02",
                "semantic_role": "total",
                "period_role": "none",
            },
        ]
    )

    planned = plan_role_queries_from_question(
        question=(
            "What is long-term retail in Americas as a percentage of "
            "total long-term retail?"
        ),
        skeleton=skeleton,
    )

    assert "americas" in planned.roles[0].role_query
    assert "americas" not in planned.roles[1].role_query
    assert "retail" in planned.roles[1].role_query


def test_question_only_planner_maps_repeated_roles_to_explicit_years() -> None:
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": f"role-{index:02d}",
                    "semantic_role": "component",
                    "period_role": "none",
                }
                for index in range(1, 4)
            ],
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
            ],
            "output_step_id": "step-02",
        }
    )

    planned = plan_role_queries_from_question(
        question="What were total volumes in 2006, 2005 and 2004?",
        skeleton=skeleton,
    )

    assert [role.expected_period for role in planned.roles] == [
        "2006",
        "2005",
        "2004",
    ]
