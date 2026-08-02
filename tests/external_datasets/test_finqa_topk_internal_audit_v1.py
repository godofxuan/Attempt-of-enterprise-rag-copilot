from __future__ import annotations

from scripts.audit_finqa_topk_internal_v1 import _paired_role_transitions


def _row(case_id: str, values: tuple[bool, bool]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "retention": [
            {"role_id": f"role-{index}", "hit": value}
            for index, value in enumerate(values)
        ],
    }


def test_paired_role_transitions_reconcile_all_outcomes() -> None:
    left = [_row("case-a", (True, False)), _row("case-b", (True, False))]
    right = [_row("case-a", (True, True)), _row("case-b", (False, False))]

    result = _paired_role_transitions(left, right, metric="hit")

    assert result == {
        "retained": 1,
        "regressed": 1,
        "gained": 1,
        "missed_both": 1,
    }
