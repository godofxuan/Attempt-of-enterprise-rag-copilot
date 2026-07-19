from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.evaluation.indirect_injection_arm_order import (
    ARM_ORDER_PROTOCOL_ID,
    CounterbalancedArmOrderPlan,
    build_counterbalanced_arm_order_plan,
)


def _case_ids(count: int) -> tuple[str, ...]:
    return tuple(f"case-{index:02d}" for index in range(count))


def test_even_cohort_is_exactly_counterbalanced_and_order_independent() -> None:
    case_ids = _case_ids(36)

    first = build_counterbalanced_arm_order_plan(case_ids)
    second = build_counterbalanced_arm_order_plan(tuple(reversed(case_ids)))

    assert first == second
    assert first.case_count == 36
    assert first.off_then_on_count == 18
    assert first.on_then_off_count == 18
    assert tuple(item.case_id for item in first.assignments) == tuple(
        sorted(case_ids)
    )


def test_odd_cohort_order_counts_differ_by_at_most_one() -> None:
    plan = build_counterbalanced_arm_order_plan(_case_ids(5))

    assert plan.off_then_on_count == 3
    assert plan.on_then_off_count == 2
    assert abs(plan.off_then_on_count - plan.on_then_off_count) == 1


def test_assignments_use_recomputed_sha256_rank_and_rank_parity() -> None:
    case_ids = ("zeta", "alpha", "middle", "omega")
    plan = build_counterbalanced_arm_order_plan(case_ids)
    expected_ranked = sorted(
        (hashlib.sha256(case_id.encode("utf-8")).hexdigest(), case_id)
        for case_id in case_ids
    )
    expected_rank = {
        case_id: rank for rank, (_, case_id) in enumerate(expected_ranked)
    }

    assert plan.protocol_id == ARM_ORDER_PROTOCOL_ID
    for assignment in plan.assignments:
        assert assignment.case_hash == hashlib.sha256(
            assignment.case_id.encode("utf-8")
        ).hexdigest()
        assert assignment.hash_rank == expected_rank[assignment.case_id]
        if assignment.hash_rank % 2 == 0:
            assert assignment.arm_order == "off_then_on"
            assert assignment.modes() == ("off", "on")
        else:
            assert assignment.arm_order == "on_then_off"
            assert assignment.modes() == ("on", "off")
        assert plan.assignment_for(assignment.case_id) == assignment


@pytest.mark.parametrize(
    ("case_ids", "message"),
    [
        ((), "at least one"),
        (("case-a", "case-a"), "unique"),
        (("case-a", ""), "non-empty"),
        (("case-a", " case-b"), "surrounding whitespace"),
    ],
)
def test_plan_builder_rejects_invalid_case_ids(
    case_ids: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        build_counterbalanced_arm_order_plan(case_ids)


def test_plan_lookup_rejects_unknown_case_id() -> None:
    plan = build_counterbalanced_arm_order_plan(("case-a", "case-b"))

    with pytest.raises(KeyError, match="unknown arm-order case ID"):
        plan.assignment_for("missing")


@pytest.mark.parametrize(
    "mutation",
    [
        "case_hash",
        "hash_rank",
        "arm_order",
        "off_then_on_count",
        "on_then_off_count",
        "assignment_order",
    ],
)
def test_plan_model_rejects_tampered_allocation(mutation: str) -> None:
    plan = build_counterbalanced_arm_order_plan(_case_ids(4))
    payload = plan.model_dump(mode="python")

    if mutation == "case_hash":
        payload["assignments"][0]["case_hash"] = "f" * 64
    elif mutation == "hash_rank":
        payload["assignments"][0]["hash_rank"] = 99
    elif mutation == "arm_order":
        original = payload["assignments"][0]["arm_order"]
        payload["assignments"][0]["arm_order"] = (
            "on_then_off" if original == "off_then_on" else "off_then_on"
        )
    elif mutation == "off_then_on_count":
        payload["off_then_on_count"] += 1
    elif mutation == "on_then_off_count":
        payload["on_then_off_count"] += 1
    else:
        payload["assignments"] = tuple(reversed(payload["assignments"]))

    with pytest.raises(ValidationError, match="arm-order plan"):
        CounterbalancedArmOrderPlan.model_validate(payload)
