from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ArmOrder = Literal["off_then_on", "on_then_off"]
GuardMode = Literal["off", "on"]
ARM_ORDER_PLAN_SCHEMA_VERSION = "indirect_injection_arm_order_plan_v1"
ARM_ORDER_PROTOCOL_ID = "stable_case_hash_rank_counterbalanced_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=False,
    )


class ArmOrderAssignment(_StrictFrozenModel):
    case_id: str = Field(min_length=1, max_length=200)
    case_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_rank: int = Field(ge=0)
    arm_order: ArmOrder

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("case ID cannot contain surrounding whitespace")
        return value

    def modes(self) -> tuple[GuardMode, GuardMode]:
        if self.arm_order == "off_then_on":
            return ("off", "on")
        return ("on", "off")


class CounterbalancedArmOrderPlan(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_arm_order_plan_v1"]
    protocol_id: Literal["stable_case_hash_rank_counterbalanced_v1"]
    hash_algorithm: Literal["sha256"]
    allocation_method: Literal["stable_hash_rank_alternation"]
    case_count: int = Field(ge=1)
    off_then_on_count: int = Field(ge=0)
    on_then_off_count: int = Field(ge=0)
    assignments: tuple[ArmOrderAssignment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self) -> CounterbalancedArmOrderPlan:
        case_ids = tuple(item.case_id for item in self.assignments)
        if case_ids != tuple(sorted(case_ids)):
            raise ValueError("arm-order plan assignments must use canonical case order")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("arm-order plan case IDs must be unique")
        if self.case_count != len(case_ids):
            raise ValueError("arm-order plan case count is inconsistent")

        ranked = sorted((_case_hash(case_id), case_id) for case_id in case_ids)
        expected_rank = {
            case_id: rank for rank, (_, case_id) in enumerate(ranked)
        }
        for item in self.assignments:
            rank = expected_rank[item.case_id]
            expected_order: ArmOrder = (
                "off_then_on" if rank % 2 == 0 else "on_then_off"
            )
            if (
                item.case_hash != _case_hash(item.case_id)
                or item.hash_rank != rank
                or item.arm_order != expected_order
            ):
                raise ValueError("arm-order plan assignment is inconsistent")

        off_then_on_count = sum(
            item.arm_order == "off_then_on" for item in self.assignments
        )
        on_then_off_count = len(self.assignments) - off_then_on_count
        if (
            self.off_then_on_count != off_then_on_count
            or self.on_then_off_count != on_then_off_count
        ):
            raise ValueError("arm-order plan summary counts are inconsistent")
        return self

    def assignment_for(self, case_id: str) -> ArmOrderAssignment:
        for item in self.assignments:
            if item.case_id == case_id:
                return item
        raise KeyError(f"unknown arm-order case ID: {case_id}")

    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.assignments)


def build_counterbalanced_arm_order_plan(
    case_ids: Iterable[str],
) -> CounterbalancedArmOrderPlan:
    canonical_ids = _validated_case_ids(case_ids)
    ranked = sorted((_case_hash(case_id), case_id) for case_id in canonical_ids)
    rank_by_id = {case_id: rank for rank, (_, case_id) in enumerate(ranked)}
    assignments = tuple(
        ArmOrderAssignment(
            case_id=case_id,
            case_hash=_case_hash(case_id),
            hash_rank=rank_by_id[case_id],
            arm_order=(
                "off_then_on" if rank_by_id[case_id] % 2 == 0 else "on_then_off"
            ),
        )
        for case_id in sorted(canonical_ids)
    )
    off_then_on_count = sum(
        item.arm_order == "off_then_on" for item in assignments
    )
    return CounterbalancedArmOrderPlan(
        schema_version=ARM_ORDER_PLAN_SCHEMA_VERSION,
        protocol_id=ARM_ORDER_PROTOCOL_ID,
        hash_algorithm="sha256",
        allocation_method="stable_hash_rank_alternation",
        case_count=len(assignments),
        off_then_on_count=off_then_on_count,
        on_then_off_count=len(assignments) - off_then_on_count,
        assignments=assignments,
    )


def _validated_case_ids(case_ids: Iterable[str]) -> tuple[str, ...]:
    if isinstance(case_ids, str):
        raise TypeError("case IDs must be an iterable of strings")
    values = tuple(case_ids)
    if not values:
        raise ValueError("arm-order plan requires at least one case ID")
    for value in values:
        if not isinstance(value, str):
            raise TypeError("case IDs must be strings")
        if not value:
            raise ValueError("case IDs must be non-empty")
        if value != value.strip():
            raise ValueError("case IDs cannot contain surrounding whitespace")
    if len(values) != len(set(values)):
        raise ValueError("case IDs must be unique")
    return values


def _case_hash(case_id: str) -> str:
    return hashlib.sha256(case_id.encode("utf-8")).hexdigest()


__all__ = [
    "ARM_ORDER_PLAN_SCHEMA_VERSION",
    "ARM_ORDER_PROTOCOL_ID",
    "ArmOrder",
    "ArmOrderAssignment",
    "CounterbalancedArmOrderPlan",
    "GuardMode",
    "build_counterbalanced_arm_order_plan",
]
