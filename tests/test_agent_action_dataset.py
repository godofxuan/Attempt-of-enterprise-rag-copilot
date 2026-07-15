import json
from collections import Counter
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
ROUTES = {
    "policy_qa",
    "process",
    "comparison",
    "no_answer_check",
    "unsafe_request",
}
SAFE_PLAN = ["retrieval.search", "rag.answer", "guardrail.check"]
UNSAFE_PLAN = ["guardrail.refuse"]
REQUIRED_KEYS = {"id", "question", "expected_route", "expected_plan", "tags"}


def load(name: str) -> list[dict]:
    with (EVAL_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_agent_action_splits_have_balanced_schema():
    for name in ["agent_action_dev.json", "agent_action_test.json"]:
        rows = load(name)

        assert len(rows) == 20
        assert Counter(row["expected_route"] for row in rows) == Counter(
            {route: 4 for route in ROUTES}
        )
        assert len({row["id"] for row in rows}) == len(rows)
        assert len({row["question"] for row in rows}) == len(rows)

        for row in rows:
            assert REQUIRED_KEYS.issubset(row)
            assert row["question"].strip()
            assert isinstance(row["tags"], list) and row["tags"]
            expected_plan = (
                UNSAFE_PLAN
                if row["expected_route"] == "unsafe_request"
                else SAFE_PLAN
            )
            assert row["expected_plan"] == expected_plan


def test_agent_action_splits_are_disjoint():
    dev = load("agent_action_dev.json")
    test = load("agent_action_test.json")

    assert {row["id"] for row in dev}.isdisjoint(row["id"] for row in test)
    assert {row["question"] for row in dev}.isdisjoint(
        row["question"] for row in test
    )
