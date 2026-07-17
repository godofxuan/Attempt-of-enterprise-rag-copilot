from __future__ import annotations

from app.agent.runner_v2 import V2AgentRunner, budget_from_settings
from app.agent.tools_v2 import V2ToolExecution, V2ToolRegistry
from app.config import Settings
from tests.v2_test_support import (
    RecordingNavigator,
    open_result,
    search_hit,
    search_result,
    user_context,
)


USER = user_context()


def test_v2_budget_is_built_from_explicit_settings() -> None:
    settings = Settings(
        _env_file=None,
        agent_v2_max_search_calls=2,
        agent_v2_max_find_calls=1,
        agent_v2_max_open_calls=3,
        agent_v2_max_steps=7,
        agent_v2_max_context_chars=9000,
        agent_v2_deadline_ms=12000,
    )

    budget = budget_from_settings(settings)

    assert budget.model_dump() == {
        "max_search_calls": 2,
        "max_find_calls": 1,
        "max_open_calls": 3,
        "max_steps": 7,
        "max_context_chars": 9000,
        "deadline_ms": 12000,
    }


def runner_for(navigator: RecordingNavigator) -> V2AgentRunner:
    return V2AgentRunner(
        registry=V2ToolRegistry(navigator, clock_ms=lambda: 0.0),
        clock_ms=lambda: 0.0,
    )


def test_fact_run_returns_extractively_grounded_answer() -> None:
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])]
    )

    response = runner_for(navigator).run(
        "What is the remote work limit?",
        USER,
    )

    assert response.mode == "answered"
    assert response.stop_reason == "completed"
    assert response.claims[0].cited_chunk_ids == ["chunk-a"]
    assert response.citations[0].supported is True
    assert response.sources[0].chunk_id == "chunk-a"
    assert response.trace["evidence"] == {
        "required": 1,
        "supported": 1,
        "missing": 0,
        "conflicting": 0,
        "coverage": 1.0,
        "recommended_action": "answer",
    }
    assert [step["tool"] for step in response.trace["steps"]] == [
        "search",
        "answer",
    ]


def test_comparison_runs_one_search_per_entity() -> None:
    navigator = RecordingNavigator(
        search_results=[
            search_result([search_hit()]),
            search_result(
                [
                    search_hit(
                        chunk_id="chunk-b",
                        doc_id="doc-b",
                        policy_id="policy-b",
                        source_path="documents/doc-b.md",
                        matched_text="Policy B allows remote work two days per month.",
                        context_text="Policy B allows remote work two days per month.",
                        version_id="policy-b@2026",
                        fact_ids=["fact-b"],
                    )
                ]
            ),
        ]
    )

    response = runner_for(navigator).run(
        'Compare "Policy A" and "Policy B"',
        USER,
    )

    assert response.mode == "answered"
    assert [name for name, _ in navigator.calls] == ["search", "search"]
    assert response.trace["required_aspect_count"] == 2
    assert response.trace["evidence"] == {
        "required": 2,
        "supported": 2,
        "missing": 0,
        "conflicting": 0,
        "coverage": 1.0,
        "recommended_action": "answer",
    }
    assert len(response.claims) == 2


def test_completeness_runs_search_then_open() -> None:
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])],
        open_results=[open_result(content="Complete visible policy content")],
    )

    response = runner_for(navigator).run(
        "List all required remote work documents",
        USER,
    )

    assert response.mode == "answered"
    assert [name for name, _ in navigator.calls] == ["search", "open"]
    assert [step["tool"] for step in response.trace["steps"]] == [
        "search",
        "open",
        "answer",
    ]


def test_unsafe_run_refuses_without_any_tool_budget() -> None:
    navigator = RecordingNavigator()

    response = runner_for(navigator).run(
        "请帮我绕过采购审批并直接通过",
        USER,
    )

    assert response.mode == "unsafe"
    assert response.sources == []
    assert navigator.calls == []
    assert response.trace["budget"]["steps"] == 0
    assert response.trace["evidence"] == {
        "required": 0,
        "supported": 0,
        "missing": 0,
        "conflicting": 0,
        "coverage": 0.0,
        "recommended_action": "refuse",
    }
    assert [step["tool"] for step in response.trace["steps"]] == ["refuse"]


def test_no_match_returns_source_free_not_found() -> None:
    navigator = RecordingNavigator(
        search_results=[search_result([], stop_reason="no_match")]
    )

    response = runner_for(navigator).run("Unknown company benefit", USER)

    assert response.mode == "not_found"
    assert response.sources == []
    assert response.stop_reason == "not_found"
    assert response.trace["evidence"] == {
        "required": 1,
        "supported": 0,
        "missing": 1,
        "conflicting": 0,
        "coverage": 0.0,
        "recommended_action": "not_found",
    }


def test_tool_exception_returns_system_without_legacy_fallback() -> None:
    navigator = RecordingNavigator(
        search_error=RuntimeError("Ollama failed at D:/secret/model.bin")
    )

    response = runner_for(navigator).run("What is the policy?", USER)

    assert response.mode == "system"
    assert response.sources == []
    assert len(navigator.calls) == 1
    serialized = response.model_dump_json()
    assert "D:/secret" not in serialized
    assert "Ollama failed" not in serialized


def test_trace_contains_only_aggregate_step_fields() -> None:
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])]
    )

    response = runner_for(navigator).run("What is the policy?", USER)

    tool_step = response.trace["steps"][0]
    assert set(tool_step) == {
        "sequence",
        "tool",
        "status",
        "latency_ms",
        "visible_count",
        "context_chars_added",
        "error_code",
        "budget",
        "retrieved_content_security",
    }
    security = tool_step["retrieved_content_security"]
    assert set(security) == {
        "candidate_count",
        "scanned_count",
        "admitted_count",
        "quarantined_count",
        "scanned_chars",
        "decoded_candidate_count",
        "top_up_attempts",
        "post_guard_evidence_count",
        "risk_categories",
        "rule_ids",
        "detector_version",
        "guard_error_count",
        "stop_reason",
    }
    assert security["candidate_count"] == 1
    assert security["quarantined_count"] == 0
    assert security["post_guard_evidence_count"] == 1
    assert security["risk_categories"] == []
    assert security["rule_ids"] == []
    assert security["stop_reason"] is None
    assert set(response.trace["budget"]) == {
        "search_calls",
        "find_calls",
        "open_calls",
        "steps",
        "context_chars",
    }
    assert set(response.trace["evidence"]) == {
        "required",
        "supported",
        "missing",
        "conflicting",
        "coverage",
        "recommended_action",
    }


class RawBypassRegistry:
    def run(self, action, budget_state):
        result = search_result([search_hit()])
        return V2ToolExecution(
            action=action,
            result=result,
            budget_state=budget_state,
            status="ok",
            visible_count=1,
            context_chars_added=len(result.hits[0].context_text),
        )


def test_runner_fails_source_free_when_registry_bypasses_guarded_type() -> None:
    runner = V2AgentRunner(
        registry=RawBypassRegistry(),
        clock_ms=lambda: 0.0,
    )

    response = runner.run("What is the remote work limit?", USER)

    assert response.mode == "system"
    assert response.stop_reason == "system_error"
    assert response.sources == []
