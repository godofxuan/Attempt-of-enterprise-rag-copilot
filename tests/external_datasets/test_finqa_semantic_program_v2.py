from __future__ import annotations

import pytest

from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticRoleBindingsV2,
    compile_semantic_program_v2,
)


def _five_step_skeleton() -> SemanticProgramSkeletonV2:
    return SemanticProgramSkeletonV2.model_validate(
        {
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
                        {"constant_id": "const_100"},
                    ],
                },
                {
                    "step_id": "step-02",
                    "operation": "DIV",
                    "arguments": [
                        {"step_id": "step-01"},
                        {"constant_id": "const_100"},
                    ],
                },
                {
                    "step_id": "step-03",
                    "operation": "SUB",
                    "arguments": [
                        {"role_id": "role-02"},
                        {"constant_id": "const_100"},
                    ],
                },
                {
                    "step_id": "step-04",
                    "operation": "DIV",
                    "arguments": [
                        {"step_id": "step-03"},
                        {"constant_id": "const_100"},
                    ],
                },
                {
                    "step_id": "step-05",
                    "operation": "SUB",
                    "arguments": [
                        {"step_id": "step-04"},
                        {"step_id": "step-02"},
                    ],
                },
            ],
            "output_step_id": "step-05",
        }
    )


def test_semantic_v2_supports_five_steps_and_controlled_constants() -> None:
    skeleton = _five_step_skeleton()
    bindings = SemanticRoleBindingsV2.model_validate(
        {
            "bindings": [
                {
                    "role_id": "role-01",
                    "candidate_id": f"num-{'a' * 20}",
                },
                {
                    "role_id": "role-02",
                    "candidate_id": f"num-{'b' * 20}",
                },
            ]
        }
    )

    program = compile_semantic_program_v2(
        skeleton=skeleton,
        bindings=bindings,
        allowed_candidate_ids_by_role={
            "role-01": (f"num-{'a' * 20}",),
            "role-02": (f"num-{'b' * 20}",),
        },
    )

    assert len(program.steps) == 5
    assert program.steps[0].arguments[1].constant_id == "const_100"
    assert program.output_step_id == "step-05"


def test_semantic_v2_rejects_non_registry_constant() -> None:
    payload = _five_step_skeleton().model_dump(mode="json")
    payload["steps"][0]["arguments"][1] = {"constant_id": "const_7"}

    with pytest.raises(ValueError):
        SemanticProgramSkeletonV2.model_validate(payload)


def test_semantic_v2_compiler_enforces_each_role_allowlist() -> None:
    skeleton = _five_step_skeleton()
    bindings = SemanticRoleBindingsV2.model_validate(
        {
            "bindings": [
                {
                    "role_id": "role-01",
                    "candidate_id": f"num-{'b' * 20}",
                },
                {
                    "role_id": "role-02",
                    "candidate_id": f"num-{'b' * 20}",
                },
            ]
        }
    )

    with pytest.raises(ValueError, match="role allowlist"):
        compile_semantic_program_v2(
            skeleton=skeleton,
            bindings=bindings,
            allowed_candidate_ids_by_role={
                "role-01": (f"num-{'a' * 20}",),
                "role-02": (f"num-{'b' * 20}",),
            },
        )
