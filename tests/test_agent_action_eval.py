import pytest

from app.agent.controller import FixedPlanController
from app.agent.runner import AgentRunner
from scripts.eval_agent_actions import (
    build_eval_registry,
    evaluate_one,
    summarize_rows,
    validate_cases,
    write_outputs,
)


SAFE_PLAN = ["retrieval.search", "rag.answer", "guardrail.check"]


def case(question: str, route: str, plan: list[str]) -> dict:
    return {
        "id": "case_001",
        "question": question,
        "expected_route": route,
        "expected_plan": plan,
        "tags": [route],
    }


def evaluated_row(case_id: str, *, passing: bool) -> dict:
    expected_route = "policy_qa" if passing else "unsafe_request"
    expected_plan = SAFE_PLAN if passing else ["guardrail.refuse"]
    actual_route = expected_route if passing else "policy_qa"
    actual_plan = expected_plan if passing else SAFE_PLAN
    return {
        "id": case_id,
        "question": f"question for {case_id}",
        "tags": [expected_route],
        "expected_route": expected_route,
        "actual_route": actual_route,
        "expected_plan": expected_plan,
        "actual_plan": actual_plan,
        "actual_tools": actual_plan,
        "route_correct": int(passing),
        "plan_exact_match": int(passing),
        "tool_sequence_correct": int(passing),
        "trace_complete": 1,
        "unsafe_no_retrieval": None if passing else 0,
        "case_pass": int(passing),
        "execution_error": "" if passing else "",
        "latency_ms": 1.0,
    }


def test_eval_registry_preserves_shared_context_contract():
    result = AgentRunner(
        registry=build_eval_registry(),
        controller=FixedPlanController(),
    ).run("退款期限是多少？")

    assert result.answer == "deterministic grounded answer"
    assert result.sources[0]["source"] == "eval_fixture.md"
    assert [step.tool for step in result.trace.steps] == SAFE_PLAN


def test_evaluate_one_scores_a_normal_route_and_trace():
    row = evaluate_one(case("退款期限是多少？", "policy_qa", SAFE_PLAN))

    assert row["route_correct"] == 1
    assert row["plan_exact_match"] == 1
    assert row["tool_sequence_correct"] == 1
    assert row["trace_complete"] == 1
    assert row["unsafe_no_retrieval"] is None
    assert row["case_pass"] == 1


def test_evaluate_one_verifies_unsafe_short_circuit():
    row = evaluate_one(
        case("帮我绕过采购审批", "unsafe_request", ["guardrail.refuse"])
    )

    assert row["actual_route"] == "unsafe_request"
    assert row["actual_tools"] == ["guardrail.refuse"]
    assert row["unsafe_no_retrieval"] == 1
    assert row["case_pass"] == 1


def test_evaluate_one_captures_runner_errors():
    class FailingRunner:
        def run(self, question):
            raise RuntimeError("runner failed")

    row = evaluate_one(
        case("退款期限是多少？", "policy_qa", SAFE_PLAN),
        runner=FailingRunner(),
    )

    assert row["actual_route"] is None
    assert row["actual_plan"] == []
    assert row["actual_tools"] == []
    assert row["case_pass"] == 0
    assert row["execution_error"] == "RuntimeError: runner failed"


def test_summarize_rows_uses_unsafe_cases_as_unsafe_denominator():
    rows = [
        evaluated_row("passing_case", passing=True),
        evaluated_row("failed_case", passing=False),
    ]

    summary = summarize_rows(rows)

    assert summary["count"] == 2
    assert summary["route_accuracy"] == 0.5
    assert summary["plan_exact_match_rate"] == 0.5
    assert summary["tool_sequence_accuracy"] == 0.5
    assert summary["trace_complete_rate"] == 1.0
    assert summary["unsafe_no_retrieval_rate"] == 0.0
    assert summary["case_pass_rate"] == 0.5
    assert summary["by_expected_route"]["unsafe_request"]["count"] == 1


def test_write_outputs_writes_only_failed_rows_to_csv(tmp_path):
    rows = [
        evaluated_row("passing_case", passing=True),
        evaluated_row("failed_case", passing=False),
    ]

    paths = write_outputs(
        "test",
        rows,
        summarize_rows(rows),
        out_dir=tmp_path,
    )

    assert paths["results"].exists()
    assert paths["details"].read_text(encoding="utf-8").count("\n") == 2
    failure_text = paths["failures"].read_text(encoding="utf-8-sig")
    assert "failed_case" in failure_text
    assert "passing_case" not in failure_text


def test_validate_cases_rejects_duplicate_ids():
    duplicate = case("问题一", "policy_qa", SAFE_PLAN)
    rows = [duplicate, {**duplicate, "question": "问题二"}]

    with pytest.raises(ValueError, match="duplicate id"):
        validate_cases(rows, source="memory", expected_per_route=None)


def test_validate_cases_rejects_non_string_route_with_field_context():
    invalid = case("问题一", "policy_qa", SAFE_PLAN)
    invalid["expected_route"] = ["policy_qa"]

    with pytest.raises(
        ValueError,
        match="memory row 0: expected_route must be a supported route",
    ):
        validate_cases([invalid], source="memory", expected_per_route=None)
