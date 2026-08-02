from __future__ import annotations

import json

import pytest

from app.external_datasets.finqa_role_query_planner_llm_v1 import (
    LocalFinQARoleQueryPlannerV1,
    parse_role_query_response,
    role_query_response_format,
    verify_question_only_llm_role_query_planner,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
)


def _skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
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


def test_llm_role_query_planner_uses_strict_question_only_schema() -> None:
    calls = []

    def fake_chat(model, messages, **kwargs):
        calls.append((model, messages, kwargs))
        return json.dumps(
            {
                "roles": [
                    {
                        "role_id": "role-01",
                        "role_query": "ending unrecognized tax benefits",
                        "expected_period": "2015",
                    },
                    {
                        "role_id": "role-02",
                        "role_query": "ending unrecognized tax benefits",
                        "expected_period": "2014",
                    },
                ]
            }
        )

    planner = LocalFinQARoleQueryPlannerV1(
        model="local-model",
        chat_fn=fake_chat,
    )
    result = planner.plan(
        question=(
            "What was the percentage change in unrecognized tax benefits "
            "from 2014 to 2015?"
        ),
        skeleton=_skeleton(),
    )

    assert result.generation_calls == 1
    assert result.skeleton.roles[0].expected_period == "2015"
    assert verify_question_only_llm_role_query_planner()
    assert calls[0][2]["think"] is False
    assert "candidates" not in calls[0][1][1]["content"]
    schema = calls[0][2]["response_format"]
    assert schema["properties"]["roles"]["maxItems"] == 2


def test_llm_role_query_parser_rejects_invented_period() -> None:
    raw = json.dumps(
        {
            "roles": [
                {
                    "role_id": "role-01",
                    "role_query": "new value",
                    "expected_period": "2016",
                },
                {
                    "role_id": "role-02",
                    "role_query": "old value",
                    "expected_period": "2014",
                },
            ]
        }
    )

    with pytest.raises(ValueError, match="invented a period"):
        parse_role_query_response(
            raw,
            skeleton=_skeleton(),
            explicit_periods=("2014", "2015"),
        )


def test_llm_role_query_schema_bounds_role_ids_and_count() -> None:
    schema = role_query_response_format(
        _skeleton(),
        explicit_periods=("2014", "2015"),
    )

    roles = schema["properties"]["roles"]
    assert roles["minItems"] == roles["maxItems"] == 2
    assert roles["items"]["properties"]["role_id"]["enum"] == [
        "role-01",
        "role-02",
    ]
