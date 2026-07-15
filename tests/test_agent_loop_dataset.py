import json
from collections import Counter
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
RAW_DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_docs"
SCENARIO_TO_TOOLS = {
    "first_pass_answer": [
        "retrieval.search",
        "evidence.assess",
        "rag.answer",
        "guardrail.check",
    ],
    "rewrite_then_answer": [
        "retrieval.search",
        "evidence.assess",
        "query.rewrite",
        "retrieval.search",
        "evidence.assess",
        "rag.answer",
        "guardrail.check",
    ],
    "rewrite_then_no_answer": [
        "retrieval.search",
        "evidence.assess",
        "query.rewrite",
        "retrieval.search",
        "evidence.assess",
        "rag.no_answer",
        "guardrail.check",
    ],
    "unsafe_refusal": ["guardrail.refuse"],
}
SCENARIO_TO_OUTCOME = {
    "first_pass_answer": "answered",
    "rewrite_then_answer": "answered",
    "rewrite_then_no_answer": "grounded_no_answer",
    "unsafe_refusal": "refused",
}
REQUIRED_KEYS = {
    "id",
    "question",
    "expected_route",
    "scenario",
    "expected_tools",
    "expected_outcome",
    "gold_sources",
    "tags",
}


def load(name: str) -> list[dict]:
    with (EVAL_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_agent_loop_splits_have_balanced_trajectory_schema():
    for name in ["agent_loop_dev.json", "agent_loop_test.json"]:
        rows = load(name)

        assert len(rows) == 16
        assert Counter(row["scenario"] for row in rows) == Counter(
            {scenario: 4 for scenario in SCENARIO_TO_TOOLS}
        )
        assert len({row["id"] for row in rows}) == len(rows)
        assert len({row["question"] for row in rows}) == len(rows)

        for row in rows:
            assert REQUIRED_KEYS.issubset(row)
            assert row["question"].strip()
            assert "??" not in row["question"]
            assert isinstance(row["tags"], list) and row["tags"]
            assert row["expected_tools"] == SCENARIO_TO_TOOLS[row["scenario"]]
            assert row["expected_outcome"] == SCENARIO_TO_OUTCOME[row["scenario"]]
            assert isinstance(row["gold_sources"], list)
            if row["expected_outcome"] == "answered":
                assert row["gold_sources"]
            else:
                assert row["gold_sources"] == []
            for source in row["gold_sources"]:
                assert (RAW_DOCS_DIR / source).is_file(), source


def test_agent_loop_splits_are_disjoint_from_each_other_and_stage7():
    dev = load("agent_loop_dev.json")
    test = load("agent_loop_test.json")
    stage7_dev = load("agent_action_dev.json")
    stage7_test = load("agent_action_test.json")

    dev_ids = {row["id"] for row in dev}
    test_ids = {row["id"] for row in test}
    new_questions = {row["question"] for row in [*dev, *test]}
    stage7_questions = {row["question"] for row in [*stage7_dev, *stage7_test]}

    assert dev_ids.isdisjoint(test_ids)
    assert {row["question"] for row in dev}.isdisjoint(
        row["question"] for row in test
    )
    assert new_questions.isdisjoint(stage7_questions)
