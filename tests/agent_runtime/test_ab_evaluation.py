from __future__ import annotations

from app.agent_runtime.evaluation import DEFAULT_CASES, run_agent_runtime_ab


def test_ab_protocol_uses_paired_identical_runtime_constraints() -> None:
    artifact = run_agent_runtime_ab(git_sha="a" * 40)

    assert artifact.protocol["sample_count"] == 5
    assert artifact.protocol["arms"] == ["bounded", "langgraph"]
    assert artifact.protocol["model"].startswith("none")
    assert len(artifact.rows) == len(DEFAULT_CASES) * 2
    assert {row.arm for row in artifact.rows} == {"bounded", "langgraph"}


def test_ab_rows_cover_answer_refusal_permission_and_injection() -> None:
    artifact = run_agent_runtime_ab(git_sha="b" * 40)
    expected = {case.case_id: case.expected_mode for case in DEFAULT_CASES}

    for row in artifact.rows:
        assert row.actual_mode == expected[row.case_id]
        assert row.task_success is True
        assert row.tool_call_validity == 1.0
        assert row.permission_violation is False


def test_ab_summary_reports_parity_without_claiming_quality_gain() -> None:
    artifact = run_agent_runtime_ab(git_sha="c" * 40)

    assert artifact.summary["behavioral_parity_rate"] == 1.0
    assert artifact.summary["arms"]["bounded"]["task_success_rate"] == 1.0
    assert artifact.summary["arms"]["langgraph"]["task_success_rate"] == 1.0

