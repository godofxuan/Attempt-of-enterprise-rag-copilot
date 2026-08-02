from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.external_datasets.finqa_controlled_program import (
    ControlledProgramStep,
    ControlledTypedProgram,
)
from app.external_datasets.finqa_semantic_program import (
    PeriodRole,
    SemanticRoleName,
)
from app.external_datasets.finqa_semantic_program_v2 import (
    MAX_SEMANTIC_PROGRAM_STEPS_V2,
    MAX_SEMANTIC_ROLES_V2,
    SemanticArgumentV2,
    SemanticProgramStepV2,
    SemanticRoleBindingV2,
    SemanticRoleBindingsV2,
    SemanticRoleRefV2,
    _StrictFrozenModel,
    _argument_key,
    _validate_arity,
)
from app.external_datasets.finqa_typed_program import CandidateRef, StepRef


SEMANTIC_PROGRAM_VERSION = "finqa_semantic_program_v3"
MAX_ROLE_QUERY_CHARS = 160
_ROLE_IDS = tuple(
    f"role-{index:02d}" for index in range(1, MAX_SEMANTIC_ROLES_V2 + 1)
)
_STEP_IDS = tuple(
    f"step-{index:02d}"
    for index in range(1, MAX_SEMANTIC_PROGRAM_STEPS_V2 + 1)
)
_FORBIDDEN_ROLE_QUERY = re.compile(
    r"(?:\bnum-[0-9a-f]{20}\b|\b(?:table|text)_\d+\b|"
    r"\bstep-\d+\b|\bconst_(?:m)?\d+\b|[{}[\]])",
    re.IGNORECASE,
)


class SemanticRoleSpecV3(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    semantic_role: SemanticRoleName
    period_role: PeriodRole
    role_query: str = Field(min_length=2, max_length=MAX_ROLE_QUERY_CHARS)
    expected_period: str | None = Field(default=None, max_length=128)

    @field_validator("role_query")
    @classmethod
    def validate_role_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if _FORBIDDEN_ROLE_QUERY.search(normalized):
            raise ValueError("role query contains a runtime identifier")
        return normalized

    @field_validator("expected_period")
    @classmethod
    def validate_expected_period(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized or _FORBIDDEN_ROLE_QUERY.search(normalized):
            raise ValueError("role period contains a runtime identifier")
        return normalized


class SemanticProgramSkeletonV3(_StrictFrozenModel):
    semantic_program_version: Literal[
        "finqa_semantic_program_v3"
    ] = SEMANTIC_PROGRAM_VERSION
    roles: tuple[SemanticRoleSpecV3, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_ROLES_V2,
    )
    steps: tuple[SemanticProgramStepV2, ...] = Field(
        min_length=1,
        max_length=MAX_SEMANTIC_PROGRAM_STEPS_V2,
    )
    output_step_id: str = Field(pattern=r"^step-0[1-5]$")

    @model_validator(mode="after")
    def validate_graph(self) -> SemanticProgramSkeletonV3:
        role_ids = tuple(role.role_id for role in self.roles)
        if (
            len(role_ids) != len(set(role_ids))
            or role_ids != _ROLE_IDS[: len(role_ids)]
        ):
            raise ValueError("semantic v3 roles must be unique and sequential")
        step_ids = tuple(step.step_id for step in self.steps)
        if (
            step_ids != _STEP_IDS[: len(step_ids)]
            or self.output_step_id != step_ids[-1]
        ):
            raise ValueError("semantic v3 steps must be sequential")
        declared_roles = set(role_ids)
        used_roles: set[str] = set()
        seen_steps: set[str] = set()
        for step in self.steps:
            _validate_arity(step.operation, len(step.arguments))
            keys = tuple(_argument_key(item) for item in step.arguments)
            if len(keys) != len(set(keys)):
                raise ValueError("semantic v3 step reuses one reference")
            for argument in step.arguments:
                if isinstance(argument, StepRef):
                    if argument.step_id not in seen_steps:
                        raise ValueError(
                            "semantic v3 step reference must point backward"
                        )
                elif isinstance(argument, SemanticRoleRefV2):
                    if argument.role_id not in declared_roles:
                        raise ValueError("semantic v3 uses undeclared role")
                    used_roles.add(argument.role_id)
            seen_steps.add(step.step_id)
        if used_roles != declared_roles:
            raise ValueError("every semantic v3 role must enter the program")
        return self


def compile_semantic_program_v3(
    *,
    skeleton: SemanticProgramSkeletonV3,
    bindings: SemanticRoleBindingsV2,
    allowed_candidate_ids_by_role: dict[str, Sequence[str]],
) -> ControlledTypedProgram:
    binding_by_role = {
        item.role_id: item.candidate_id for item in bindings.bindings
    }
    expected_roles = {role.role_id for role in skeleton.roles}
    if (
        set(binding_by_role) != expected_roles
        or set(allowed_candidate_ids_by_role) != expected_roles
    ):
        raise ValueError("semantic v3 bindings do not cover exact role set")
    for role_id, candidate_id in binding_by_role.items():
        allowlist = tuple(allowed_candidate_ids_by_role[role_id])
        if (
            not allowlist
            or len(allowlist) != len(set(allowlist))
            or candidate_id not in allowlist
        ):
            raise ValueError("semantic v3 binding violates role allowlist")
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
    "MAX_ROLE_QUERY_CHARS",
    "SEMANTIC_PROGRAM_VERSION",
    "SemanticArgumentV2",
    "SemanticProgramSkeletonV3",
    "SemanticProgramStepV2",
    "SemanticRoleBindingV2",
    "SemanticRoleBindingsV2",
    "SemanticRoleRefV2",
    "SemanticRoleSpecV3",
    "compile_semantic_program_v3",
]
