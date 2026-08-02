from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_semantic_program import (
    PeriodRole,
    SemanticRoleName,
)
from app.external_datasets.finqa_controlled_program import (
    ControlledConstantRef,
    ControlledProgramStep,
    ControlledTypedProgram,
)
from app.external_datasets.finqa_typed_program import (
    CandidateRef,
    StepRef,
    TypedFinancialOperation,
)


SEMANTIC_PROGRAM_VERSION = "finqa_semantic_program_v2"
MAX_SEMANTIC_PROGRAM_STEPS_V2 = 5
MAX_SEMANTIC_ROLES_V2 = 8
_STEP_IDS = tuple(
    f"step-{index:02d}"
    for index in range(1, MAX_SEMANTIC_PROGRAM_STEPS_V2 + 1)
)
_ROLE_IDS = tuple(
    f"role-{index:02d}"
    for index in range(1, MAX_SEMANTIC_ROLES_V2 + 1)
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class SemanticRoleSpecV2(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    semantic_role: SemanticRoleName
    period_role: PeriodRole


class SemanticRoleRefV2(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")


SemanticArgumentV2 = SemanticRoleRefV2 | ControlledConstantRef | StepRef


class SemanticProgramStepV2(_StrictFrozenModel):
    step_id: str = Field(pattern=r"^step-0[1-5]$")
    operation: TypedFinancialOperation
    arguments: tuple[SemanticArgumentV2, ...] = Field(
        min_length=2,
        max_length=MAX_SEMANTIC_ROLES_V2,
    )


def _argument_key(argument: SemanticArgumentV2) -> tuple[str, str]:
    if isinstance(argument, StepRef):
        return "step", argument.step_id
    if isinstance(argument, ControlledConstantRef):
        return "constant", argument.constant_id
    return "role", argument.role_id


def _validate_arity(
    operation: TypedFinancialOperation,
    argument_count: int,
) -> None:
    if operation in {"ADD", "AVERAGE"}:
        valid = 2 <= argument_count <= MAX_SEMANTIC_ROLES_V2
    else:
        valid = argument_count == 2
    if not valid:
        raise ValueError("semantic v2 operation has invalid arity")


class SemanticProgramSkeletonV2(_StrictFrozenModel):
    semantic_program_version: Literal[
        "finqa_semantic_program_v2"
    ] = SEMANTIC_PROGRAM_VERSION
    roles: tuple[SemanticRoleSpecV2, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_ROLES_V2,
    )
    steps: tuple[SemanticProgramStepV2, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_PROGRAM_STEPS_V2,
    )
    output_step_id: str = Field(pattern=r"^step-0[1-5]$")

    @model_validator(mode="after")
    def validate_graph(self) -> SemanticProgramSkeletonV2:
        role_ids = tuple(role.role_id for role in self.roles)
        if (
            len(role_ids) != len(set(role_ids))
            or role_ids != _ROLE_IDS[: len(role_ids)]
        ):
            raise ValueError("semantic v2 roles must be unique and sequential")
        step_ids = tuple(step.step_id for step in self.steps)
        if (
            step_ids != _STEP_IDS[: len(step_ids)]
            or self.output_step_id != step_ids[-1]
        ):
            raise ValueError("semantic v2 steps must be sequential")
        declared_roles = set(role_ids)
        used_roles: set[str] = set()
        seen_steps: set[str] = set()
        for step in self.steps:
            _validate_arity(step.operation, len(step.arguments))
            keys = tuple(_argument_key(item) for item in step.arguments)
            if len(keys) != len(set(keys)):
                raise ValueError("semantic v2 step reuses one reference")
            for argument in step.arguments:
                if isinstance(argument, StepRef):
                    if argument.step_id not in seen_steps:
                        raise ValueError(
                            "semantic v2 step reference must point backward"
                        )
                elif isinstance(argument, SemanticRoleRefV2):
                    if argument.role_id not in declared_roles:
                        raise ValueError("semantic v2 uses undeclared role")
                    used_roles.add(argument.role_id)
            seen_steps.add(step.step_id)
        if used_roles != declared_roles:
            raise ValueError("every semantic v2 role must enter the program")
        return self


class SemanticRoleBindingV2(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")


class SemanticRoleBindingsV2(_StrictFrozenModel):
    bindings: tuple[SemanticRoleBindingV2, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_ROLES_V2,
    )

    @model_validator(mode="after")
    def validate_unique_roles(self) -> SemanticRoleBindingsV2:
        role_ids = [item.role_id for item in self.bindings]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("semantic v2 role binding is duplicated")
        return self


def compile_semantic_program_v2(
    *,
    skeleton: SemanticProgramSkeletonV2,
    bindings: SemanticRoleBindingsV2,
    allowed_candidate_ids_by_role: dict[str, Sequence[str]],
) -> ControlledTypedProgram:
    binding_by_role = {
        item.role_id: item.candidate_id for item in bindings.bindings
    }
    expected_roles = {role.role_id for role in skeleton.roles}
    if set(binding_by_role) != expected_roles:
        raise ValueError("semantic v2 bindings do not cover exact role set")
    if set(allowed_candidate_ids_by_role) != expected_roles:
        raise ValueError("semantic v2 role allowlists are incomplete")
    for role_id, candidate_id in binding_by_role.items():
        allowlist = tuple(allowed_candidate_ids_by_role[role_id])
        if (
            not allowlist
            or len(allowlist) != len(set(allowlist))
            or candidate_id not in allowlist
        ):
            raise ValueError("semantic v2 binding violates role allowlist")
    steps = tuple(
        ControlledProgramStep(
            step_id=step.step_id,
            operation=step.operation,
            arguments=tuple(
                (
                    CandidateRef(
                        candidate_id=binding_by_role[argument.role_id]
                    )
                    if isinstance(argument, SemanticRoleRefV2)
                    else argument
                )
                for argument in step.arguments
            ),
        )
        for step in skeleton.steps
    )
    return ControlledTypedProgram(
        steps=steps,
        output_step_id=skeleton.output_step_id,
    )


__all__ = [
    "MAX_SEMANTIC_PROGRAM_STEPS_V2",
    "MAX_SEMANTIC_ROLES_V2",
    "SEMANTIC_PROGRAM_VERSION",
    "SemanticArgumentV2",
    "SemanticProgramSkeletonV2",
    "SemanticProgramStepV2",
    "SemanticRoleBindingV2",
    "SemanticRoleBindingsV2",
    "SemanticRoleRefV2",
    "SemanticRoleSpecV2",
    "compile_semantic_program_v2",
]
