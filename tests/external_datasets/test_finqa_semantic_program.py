from __future__ import annotations

import pytest

from app.external_datasets.finqa_semantic_program import (
    DirectProgramSketch,
    SemanticProgramSkeleton,
    SemanticProgramStep,
    SemanticRoleBinding,
    SemanticRoleBindings,
    SemanticRoleRef,
    SemanticRoleSpec,
    compile_semantic_program,
)
from app.external_datasets.finqa_typed_program import (
    CandidateRef,
    StepRef,
    TypedProgramStep,
)


_CANDIDATE_A = "num-" + "a" * 20
_CANDIDATE_B = "num-" + "b" * 20


def _skeleton() -> SemanticProgramSkeleton:
    return SemanticProgramSkeleton(
        roles=[
            SemanticRoleSpec(
                role_id="role-01",
                semantic_role="new_value",
                period_role="end",
            ),
            SemanticRoleSpec(
                role_id="role-02",
                semantic_role="old_value",
                period_role="start",
            ),
        ],
        steps=[
            SemanticProgramStep(
                step_id="step-01",
                operation="SUB",
                arguments=[
                    SemanticRoleRef(role_id="role-01"),
                    SemanticRoleRef(role_id="role-02"),
                ],
            ),
            SemanticProgramStep(
                step_id="step-02",
                operation="DIV",
                arguments=[
                    StepRef(step_id="step-01"),
                    SemanticRoleRef(role_id="role-02"),
                ],
            ),
        ],
        output_step_id="step-02",
    )


def test_semantic_roles_compile_to_candidate_and_step_refs() -> None:
    program = compile_semantic_program(
        skeleton=_skeleton(),
        bindings=SemanticRoleBindings(
            bindings=[
                SemanticRoleBinding(
                    role_id="role-01",
                    candidate_id=_CANDIDATE_A,
                ),
                SemanticRoleBinding(
                    role_id="role-02",
                    candidate_id=_CANDIDATE_B,
                ),
            ]
        ),
        allowed_candidate_ids=[_CANDIDATE_A, _CANDIDATE_B],
    )

    assert len(program.steps) == 2
    assert program.steps[0].arguments[0] == CandidateRef(
        candidate_id=_CANDIDATE_A
    )
    assert program.steps[1].arguments[0] == StepRef(step_id="step-01")


def test_semantic_compile_rejects_missing_or_untrusted_binding() -> None:
    with pytest.raises(ValueError, match="exact role set"):
        compile_semantic_program(
            skeleton=_skeleton(),
            bindings=SemanticRoleBindings(
                bindings=[
                    SemanticRoleBinding(
                        role_id="role-01",
                        candidate_id=_CANDIDATE_A,
                    ),
                    SemanticRoleBinding(
                        role_id="role-03",
                        candidate_id=_CANDIDATE_B,
                    ),
                ]
            ),
            allowed_candidate_ids=[_CANDIDATE_A, _CANDIDATE_B],
        )

    with pytest.raises(ValueError, match="non-allowlisted"):
        compile_semantic_program(
            skeleton=_skeleton(),
            bindings=SemanticRoleBindings(
                bindings=[
                    SemanticRoleBinding(
                        role_id="role-01",
                        candidate_id=_CANDIDATE_A,
                    ),
                    SemanticRoleBinding(
                        role_id="role-02",
                        candidate_id=_CANDIDATE_B,
                    ),
                ]
            ),
            allowed_candidate_ids=[_CANDIDATE_A],
        )


def test_semantic_skeleton_rejects_forward_step_reference() -> None:
    with pytest.raises(ValueError, match="point backward"):
        SemanticProgramSkeleton(
            roles=[
                SemanticRoleSpec(
                    role_id="role-01",
                    semantic_role="part",
                    period_role="none",
                ),
                SemanticRoleSpec(
                    role_id="role-02",
                    semantic_role="total",
                    period_role="none",
                ),
            ],
            steps=[
                SemanticProgramStep(
                    step_id="step-01",
                    operation="DIV",
                    arguments=[
                        StepRef(step_id="step-02"),
                        SemanticRoleRef(role_id="role-01"),
                    ],
                ),
                SemanticProgramStep(
                    step_id="step-02",
                    operation="ADD",
                    arguments=[
                        SemanticRoleRef(role_id="role-01"),
                        SemanticRoleRef(role_id="role-02"),
                    ],
                ),
            ],
            output_step_id="step-02",
        )


def test_direct_sketch_rejects_nonsequential_graph() -> None:
    with pytest.raises(ValueError, match="sequential"):
        DirectProgramSketch(
            steps=[
                TypedProgramStep(
                    step_id="step-02",
                    operation="DIV",
                    arguments=[
                        CandidateRef(candidate_id=_CANDIDATE_A),
                        CandidateRef(candidate_id=_CANDIDATE_B),
                    ],
                )
            ],
            output_step_id="step-02",
        )
