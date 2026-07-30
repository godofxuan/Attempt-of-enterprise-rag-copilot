from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_typed_program import (
    CandidateRef,
    StepRef,
    TypedFinancialOperation,
    TypedProgram,
    TypedProgramStep,
)


MAX_SEMANTIC_PROGRAM_STEPS = 3
MAX_SEMANTIC_ROLES = 6
_STEP_IDS = tuple(
    f"step-{index:02d}"
    for index in range(1, MAX_SEMANTIC_PROGRAM_STEPS + 1)
)
_ROLE_IDS = tuple(
    f"role-{index:02d}"
    for index in range(1, MAX_SEMANTIC_ROLES + 1)
)
SemanticRoleName = Literal[
    "value",
    "part",
    "total",
    "new_value",
    "old_value",
    "component",
    "factor",
    "divisor",
    "comparison_left",
    "comparison_right",
]
PeriodRole = Literal["target", "start", "end", "none"]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class SemanticRoleSpec(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-6]$")
    semantic_role: SemanticRoleName
    period_role: PeriodRole


class SemanticRoleRef(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-6]$")


SemanticArgument = SemanticRoleRef | StepRef


class SemanticProgramStep(_StrictFrozenModel):
    step_id: str = Field(pattern=r"^step-0[1-3]$")
    operation: TypedFinancialOperation
    arguments: tuple[SemanticArgument, ...] = Field(
        min_length=2,
        max_length=MAX_SEMANTIC_ROLES,
    )


def _argument_key(argument: SemanticArgument) -> tuple[str, str]:
    if isinstance(argument, StepRef):
        return "step", argument.step_id
    return "role", argument.role_id


def _validate_arity(
    operation: TypedFinancialOperation,
    argument_count: int,
) -> None:
    if operation in {"ADD", "AVERAGE"}:
        valid = 2 <= argument_count <= MAX_SEMANTIC_ROLES
    else:
        valid = argument_count == 2
    if not valid:
        raise ValueError("semantic program operation has invalid arity")


class SemanticProgramSkeleton(_StrictFrozenModel):
    roles: tuple[SemanticRoleSpec, ...] = Field(
        min_length=2,
        max_length=MAX_SEMANTIC_ROLES,
    )
    steps: tuple[SemanticProgramStep, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_PROGRAM_STEPS,
    )
    output_step_id: str = Field(pattern=r"^step-0[1-3]$")

    @model_validator(mode="after")
    def validate_graph(self) -> SemanticProgramSkeleton:
        role_ids = tuple(role.role_id for role in self.roles)
        if (
            len(role_ids) != len(set(role_ids))
            or role_ids
            != _ROLE_IDS[: len(role_ids)]
        ):
            raise ValueError("semantic roles must be unique and sequential")
        step_ids = tuple(step.step_id for step in self.steps)
        if (
            step_ids != _STEP_IDS[: len(step_ids)]
            or self.output_step_id != step_ids[-1]
        ):
            raise ValueError(
                "semantic steps must be sequential and output the last step"
            )
        declared_roles = set(role_ids)
        used_roles: set[str] = set()
        seen_steps: set[str] = set()
        for step in self.steps:
            _validate_arity(step.operation, len(step.arguments))
            keys = tuple(_argument_key(item) for item in step.arguments)
            if len(keys) != len(set(keys)):
                raise ValueError(
                    "semantic step cannot reuse one reference"
                )
            for argument in step.arguments:
                if isinstance(argument, StepRef):
                    if argument.step_id not in seen_steps:
                        raise ValueError(
                            "semantic step reference must point backward"
                        )
                elif argument.role_id not in declared_roles:
                    raise ValueError("semantic step uses undeclared role")
                else:
                    used_roles.add(argument.role_id)
            seen_steps.add(step.step_id)
        if used_roles != declared_roles:
            raise ValueError("every semantic role must enter the program")
        return self


class SemanticRoleBinding(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-6]$")
    candidate_id: str = Field(pattern=r"^num-[0-9a-f]{20}$")


class SemanticRoleBindings(_StrictFrozenModel):
    bindings: tuple[SemanticRoleBinding, ...] = Field(
        min_length=2,
        max_length=MAX_SEMANTIC_ROLES,
    )

    @model_validator(mode="after")
    def validate_unique_roles(self) -> SemanticRoleBindings:
        role_ids = [item.role_id for item in self.bindings]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("semantic role binding is duplicated")
        return self


class DirectProgramSketch(_StrictFrozenModel):
    steps: tuple[TypedProgramStep, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_PROGRAM_STEPS,
    )
    output_step_id: str = Field(pattern=r"^step-0[1-3]$")

    @model_validator(mode="after")
    def validate_graph(self) -> DirectProgramSketch:
        program = TypedProgram(
            steps=self.steps,
            output_step_id=self.output_step_id,
        )
        step_ids = tuple(step.step_id for step in program.steps)
        if (
            step_ids != _STEP_IDS[: len(step_ids)]
            or program.output_step_id != step_ids[-1]
        ):
            raise ValueError(
                "direct steps must be sequential and output the last step"
            )
        seen_steps: set[str] = set()
        for step in program.steps:
            _validate_arity(step.operation, len(step.arguments))
            references = [
                (
                    "step",
                    argument.step_id,
                )
                if isinstance(argument, StepRef)
                else ("candidate", argument.candidate_id)
                for argument in step.arguments
            ]
            if len(references) != len(set(references)):
                raise ValueError("direct step cannot reuse one reference")
            if any(
                isinstance(argument, StepRef)
                and argument.step_id not in seen_steps
                for argument in step.arguments
            ):
                raise ValueError(
                    "direct step reference must point backward"
                )
            seen_steps.add(step.step_id)
        return self

    def compile(self) -> TypedProgram:
        return TypedProgram(
            steps=self.steps,
            output_step_id=self.output_step_id,
        )


def compile_semantic_program(
    *,
    skeleton: SemanticProgramSkeleton,
    bindings: SemanticRoleBindings,
    allowed_candidate_ids: Sequence[str],
) -> TypedProgram:
    binding_by_role = {
        item.role_id: item.candidate_id for item in bindings.bindings
    }
    expected_roles = {role.role_id for role in skeleton.roles}
    if set(binding_by_role) != expected_roles:
        raise ValueError("semantic bindings do not cover exact role set")
    allowlist = set(allowed_candidate_ids)
    if (
        not allowlist
        or len(allowlist) != len(tuple(allowed_candidate_ids))
        or not set(binding_by_role.values()).issubset(allowlist)
    ):
        raise ValueError("semantic binding uses non-allowlisted candidate")
    steps = tuple(
        TypedProgramStep(
            step_id=step.step_id,
            operation=step.operation,
            arguments=tuple(
                (
                    argument
                    if isinstance(argument, StepRef)
                    else CandidateRef(
                        candidate_id=binding_by_role[argument.role_id]
                    )
                )
                for argument in step.arguments
            ),
        )
        for step in skeleton.steps
    )
    return DirectProgramSketch(
        steps=steps,
        output_step_id=skeleton.output_step_id,
    ).compile()


__all__ = [
    "MAX_SEMANTIC_PROGRAM_STEPS",
    "MAX_SEMANTIC_ROLES",
    "DirectProgramSketch",
    "PeriodRole",
    "SemanticArgument",
    "SemanticProgramSkeleton",
    "SemanticProgramStep",
    "SemanticRoleBinding",
    "SemanticRoleBindings",
    "SemanticRoleName",
    "SemanticRoleRef",
    "SemanticRoleSpec",
    "compile_semantic_program",
]
