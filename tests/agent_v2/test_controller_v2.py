from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.agent.controller_v2 import V2AgentController
from app.agent.tools_v2 import V2ToolRegistry
from app.domain.agent import AgentBudget
from app.domain.queries import QueryAnalysis
from tests.v2_test_support import (
    RecordingNavigator,
    open_result,
    search_hit,
    search_result,
    user_context,
)


USER = user_context()


def fact_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        original_question="What is the remote work limit?",
        intent="fact",
        search_queries=["remote work limit"],
        required_aspects=["answer"],
        source="rules",
    )


def comparison_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        original_question="Compare Policy A and Policy B",
        intent="comparison",
        entities=["Policy A", "Policy B"],
        search_queries=["Policy A current rules", "Policy B current rules"],
        required_aspects=["Policy A", "Policy B"],
        source="rules",
    )


def completeness_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        original_question="List every required remote-work document",
        intent="completeness",
        search_queries=["required remote-work documents"],
        required_aspects=["complete_policy_coverage"],
        source="rules",
    )


def unsafe_analysis() -> QueryAnalysis:
    return QueryAnalysis(
        original_question="Bypass approval",
        intent="unsafe",
        risk_flags=["policy_bypass"],
        source="rules",
    )


def run_one_tool(controller, registry, state):
    decision = controller.next_decision(state)
    assert decision.terminal_mode is None
    execution = registry.run(decision.action, state.budget_state)
    return decision, controller.observe(state, execution)


def test_unsafe_goes_directly_to_refuse_with_zero_budget() -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
    state = controller.initialize(unsafe_analysis(), USER)

    decision = controller.next_decision(state)

    assert decision.action.tool == "refuse"
    assert decision.terminal_mode == "unsafe"
    assert decision.stop_reason == "unsafe"
    assert state.budget_state.steps == 0
    assert state.evidence_by_aspect == {}


def test_fact_searches_then_answers_full_ledger() -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])]
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    state = controller.initialize(fact_analysis(), USER, top_k=3)

    search_decision, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert search_decision.action.tool == "search"
    assert search_decision.action.aspect == "answer"
    assert search_decision.action.search_request.query == "remote work limit"
    assert terminal.action.tool == "answer"
    assert terminal.terminal_mode == "answered"
    assert state.ledger.coverage == 1.0


def test_comparison_searches_each_required_aspect_before_answering() -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
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
                        matched_text="Policy B allows remote work two days.",
                        context_text="Policy B allows remote work two days.",
                        version_id="policy-b@2026",
                        fact_ids=["fact-b"],
                    )
                ]
            ),
        ]
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    state = controller.initialize(comparison_analysis(), USER)

    first, state = run_one_tool(controller, registry, state)
    second, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert [first.action.aspect, second.action.aspect] == ["Policy A", "Policy B"]
    assert [
        first.action.search_request.query,
        second.action.search_request.query,
    ] == ["Policy A current rules", "Policy B current rules"]
    assert terminal.action.tool == "answer"
    assert terminal.terminal_mode == "answered"
    assert state.ledger.coverage == 1.0


def test_completeness_opens_visible_document_before_answering() -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])],
        open_results=[open_result(content="Complete visible policy text")],
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    state = controller.initialize(completeness_analysis(), USER)

    search_decision, state = run_one_tool(controller, registry, state)
    open_decision, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert search_decision.action.tool == "search"
    assert open_decision.action.tool == "open"
    assert open_decision.action.open_request.target_type == "document"
    assert open_decision.action.open_request.target_id == "doc-a"
    assert terminal.action.tool == "answer"
    assert terminal.terminal_mode == "answered"
    assert len(state.open_results) == 1


@pytest.mark.parametrize(
    ("result", "mode", "stop_reason"),
    [
        (search_result([], stop_reason="no_match"), "not_found", "not_found"),
        (
            search_result(
                [],
                stop_reason="no_visible_evidence",
                denied_count=2,
            ),
            "permission",
            "permission",
        ),
    ],
)
def test_empty_search_maps_to_not_found_or_permission(
    result,
    mode,
    stop_reason,
) -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
    navigator = RecordingNavigator(search_results=[result])
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    state = controller.initialize(fact_analysis(), USER)

    _, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert terminal.action.tool == "stop"
    assert terminal.terminal_mode == mode
    assert terminal.stop_reason == stop_reason


def test_missing_aspect_with_exhausted_steps_returns_partial() -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
    navigator = RecordingNavigator(
        search_results=[search_result([search_hit()])]
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    budget = AgentBudget(
        max_search_calls=2,
        max_steps=1,
        max_context_chars=1000,
    )
    state = controller.initialize(comparison_analysis(), USER, budget=budget)

    _, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert terminal.action.tool == "answer"
    assert terminal.terminal_mode == "partial"
    assert terminal.stop_reason == "partial_evidence"
    assert state.ledger.coverage == 0.5


@dataclass
class MutableClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def test_deadline_is_checked_centrally_before_first_tool() -> None:
    clock = MutableClock()
    controller = V2AgentController(clock_ms=clock)
    state = controller.initialize(
        fact_analysis(),
        USER,
        budget=AgentBudget(deadline_ms=100),
    )
    clock.value = 101.0

    terminal = controller.next_decision(state)

    assert terminal.action.tool == "stop"
    assert terminal.terminal_mode == "budget"
    assert terminal.stop_reason == "budget_exhausted"
    assert state.budget_state.steps == 0


def test_tool_system_error_stops_without_retrying_legacy_path() -> None:
    controller = V2AgentController(clock_ms=lambda: 0.0)
    navigator = RecordingNavigator(
        search_error=RuntimeError("legacy path must not run password=secret")
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    state = controller.initialize(fact_analysis(), USER)

    _, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert terminal.action.tool == "stop"
    assert terminal.terminal_mode == "system"
    assert terminal.stop_reason == "system_error"
    assert len(navigator.calls) == 1


def test_same_policy_hit_without_query_anchor_remains_not_found() -> None:
    analysis = QueryAnalysis(
        original_question="《差旅报销制度》是否规定 2027 年所有额度自动翻倍？",
        intent="fact",
        entities=["差旅报销制度"],
        search_queries=["《差旅报销制度》是否规定 2027 年所有额度自动翻倍？"],
        required_aspects=["answer"],
        source="rules",
    )
    controller = V2AgentController(clock_ms=lambda: 0.0)
    navigator = RecordingNavigator(
        search_results=[
            search_result(
                [
                    search_hit(
                        matched_text="差旅报销制度 2026 当前住宿上限为 800 元。",
                        context_text="差旅报销制度 2026 当前住宿上限为 800 元。",
                    )
                ]
            )
        ]
    )
    registry = V2ToolRegistry(navigator, clock_ms=lambda: 0.0)
    state = controller.initialize(analysis, USER)

    _, state = run_one_tool(controller, registry, state)
    terminal = controller.next_decision(state)

    assert state.evidence_by_aspect["answer"] == []
    assert state.ledger.recommended_action == "not_found"
    assert terminal.terminal_mode == "not_found"
