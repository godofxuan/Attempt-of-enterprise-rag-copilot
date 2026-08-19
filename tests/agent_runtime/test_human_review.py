from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.orchestrator import (
    AgentRunRequest,
    HumanReviewDecision,
    LangGraphOrchestratorAdapter,
)
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from app.domain.agent import AgentBudget
from app.domain.queries import QueryAnalysis, UserContext
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context


class PartialEvidenceAnalyzer:
    def analyze(self, question, user):
        return QueryAnalysis(
            original_question=question,
            intent="comparison",
            entities=["remote", "leave"],
            search_queries=["remote policy", "leave policy"],
            required_aspects=["remote", "leave"],
            source="rules",
        )


def reviewer(*, tenant_id: str = "tenant-one", roles=None) -> UserContext:
    return UserContext(
        user_id="reviewer-one",
        tenant_id=tenant_id,
        region="cn",
        groups=["employees"],
        roles=roles if roles is not None else ["knowledge_reviewer"],
    )


def paused_runtime(tmp_path):
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: now)
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    adapter = LangGraphOrchestratorAdapter(
        V2ToolRegistry(navigator, clock_ms=lambda: 100.0),
        analyzer=PartialEvidenceAnalyzer(),
        budget=AgentBudget(max_steps=1, max_search_calls=1),
        clock_ms=lambda: 100.0,
        trajectory_store=store,
        hitl_on_partial=True,
    )
    request = AgentRunRequest(
        question="Compare remote and leave policy.",
        user=user_context(),
        request_id="request-one",
        trace_id="trace-one",
        session_id="session-one",
    )
    return adapter, store, navigator, adapter.run(request)


def test_partial_evidence_interrupts_before_terminal_publication(tmp_path) -> None:
    _, store, navigator, result = paused_runtime(tmp_path)

    assert result.status == "needs_human_review"
    assert result.response is None
    assert result.human_review.reason == "partial_evidence"
    assert result.human_review.evidence_summary["supported"] == 1
    assert result.human_review.evidence_summary["missing"] == ["leave"]
    assert len(navigator.calls) == 1
    events = store.load("session-one")
    assert events[-1].event_type == "human_review.requested"
    assert "terminal.reached" not in [event.event_type for event in events]
    assert result.human_review.review_token not in "".join(
        event.model_dump_json() for event in events
    )


def test_authorized_human_can_accept_partial_once(tmp_path) -> None:
    adapter, store, _, paused = paused_runtime(tmp_path)
    token = paused.human_review.review_token

    completed = adapter.resume(
        token,
        HumanReviewDecision(decision="accept_partial", note="Evidence is useful."),
        reviewer(),
    )

    assert completed.status == "completed"
    assert completed.response.mode == "partial"
    event_types = [event.event_type for event in store.load("session-one")]
    assert "human_review.completed" in event_types
    assert event_types[-2:] == ["terminal.reached", "session.completed"]
    with pytest.raises(ValueError, match="already used"):
        adapter.resume(
            token,
            HumanReviewDecision(decision="accept_partial"),
            reviewer(),
        )


def test_authorized_human_can_reject_partial_publication(tmp_path) -> None:
    adapter, _, _, paused = paused_runtime(tmp_path)

    completed = adapter.resume(
        paused.human_review.review_token,
        HumanReviewDecision(decision="reject"),
        reviewer(),
    )

    assert completed.response.mode == "not_found"
    assert completed.response.sources == []
    assert "human review rejected" in completed.response.answer


def test_cross_tenant_or_unprivileged_reviewer_cannot_resume(tmp_path) -> None:
    adapter, store, _, paused = paused_runtime(tmp_path)
    token = paused.human_review.review_token

    with pytest.raises(PermissionError, match="different tenant"):
        adapter.resume(
            token,
            HumanReviewDecision(decision="accept_partial"),
            reviewer(tenant_id="tenant-two"),
        )
    with pytest.raises(PermissionError, match="role"):
        adapter.resume(
            token,
            HumanReviewDecision(decision="accept_partial"),
            reviewer(roles=[]),
        )
    assert store.load("session-one")[-1].event_type == "human_review.requested"


def test_forged_review_token_is_rejected_without_consuming_real_token(tmp_path) -> None:
    adapter, _, _, paused = paused_runtime(tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        adapter.resume(
            "x" * 48,
            HumanReviewDecision(decision="reject"),
            reviewer(),
        )
    completed = adapter.resume(
        paused.human_review.review_token,
        HumanReviewDecision(decision="reject"),
        reviewer(),
    )
    assert completed.status == "completed"

