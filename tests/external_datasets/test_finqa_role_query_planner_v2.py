from __future__ import annotations

from app.external_datasets.finqa_role_query_planner_v2 import (
    plan_role_queries_from_question_v2,
    verify_question_only_role_query_planner_v2,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


def _skeleton(period_roles: tuple[str, str]) -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "new_value",
                    "period_role": period_roles[0],
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "old_value",
                    "period_role": period_roles[1],
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
    )


def test_v2_uses_only_declared_temporal_roles_for_hard_periods() -> None:
    planned = plan_role_queries_from_question_v2(
        question="What was the percentage change from 2014 to 2015?",
        skeleton=_skeleton(("end", "start")),
    )

    assert [role.expected_period for role in planned.roles] == [
        "2015",
        "2014",
    ]
    assert verify_question_only_role_query_planner_v2()


def test_v2_does_not_infer_period_for_non_temporal_roles() -> None:
    skeleton = SemanticProgramSkeletonV2.model_validate(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "semantic_role": "component",
                    "period_role": "none",
                },
                {
                    "role_id": "role-02",
                    "semantic_role": "component",
                    "period_role": "none",
                },
            ],
            "steps": [
                {
                    "step_id": "step-01",
                    "operation": "ADD",
                    "arguments": [
                        {"role_id": "role-01"},
                        {"role_id": "role-02"},
                    ],
                }
            ],
            "output_step_id": "step-01",
        }
    )

    planned = plan_role_queries_from_question_v2(
        question=(
            "What is the average price of the company's stock in 2016?"
        ),
        skeleton=skeleton,
    )

    assert all(role.expected_period is None for role in planned.roles)
    assert all("2019" not in role.role_query for role in planned.roles)
