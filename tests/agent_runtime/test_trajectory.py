from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.orchestrator import AgentRunRequest, LangGraphOrchestratorAdapter
from app.agent_runtime.trajectory import (
    AgentEventDraft,
    SQLiteTrajectoryStore,
    redact_trajectory_payload,
)
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def draft(event_type: str, **updates) -> AgentEventDraft:
    values = {
        "session_id": "session-one",
        "trace_id": "trace-one",
        "event_type": event_type,
        "payload": {},
    }
    values.update(updates)
    return AgentEventDraft(**values)


def test_store_is_ordered_hash_chained_and_verifiable(tmp_path) -> None:
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: NOW)

    first = store.append(draft("session.started"))
    second = store.append(draft("user.message", payload={"question": "Policy?"}))

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_hash == first.event_hash
    assert store.verify("session-one") is True


def test_database_triggers_reject_update_and_delete(tmp_path) -> None:
    path = tmp_path / "trajectory.sqlite3"
    store = SQLiteTrajectoryStore(path, now=lambda: NOW)
    store.append(draft("session.started"))

    with (
        sqlite3.connect(path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        connection.execute("UPDATE agent_events SET trace_id = 'forged'")
    with (
        sqlite3.connect(path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
    ):
        connection.execute("DELETE FROM agent_events")


def test_completed_or_reused_session_cannot_be_appended(tmp_path) -> None:
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: NOW)
    store.append(draft("session.started"))
    store.append(draft("session.completed"))

    with pytest.raises(ValueError, match="immutable"):
        store.append(draft("user.message"))
    with pytest.raises(ValueError, match="already exists|immutable"):
        store.append(draft("session.started"))


def test_idempotent_projection_returns_existing_event_after_session_completion(
    tmp_path,
) -> None:
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: NOW)
    store.append(draft("session.started"))
    first = store.append(
        draft("session.completed", payload={"status": "completed"}),
        idempotency_key="approval-one:session.completed",
    )

    repeated = store.append(
        draft("session.completed", payload={"status": "completed"}),
        idempotency_key="approval-one:session.completed",
    )

    assert repeated == first
    assert len(store.load("session-one")) == 2


def test_secret_and_raw_retrieval_content_are_redacted() -> None:
    canary = "placeholder"
    payload = redact_trajectory_payload(
        {
            "authorization": "placeholder",
            "nested": {"api_key": canary, "context_text": "private policy"},
            "safe": "document-id-1",
        }
    )

    assert payload["authorization"] == "[REDACTED]"
    assert payload["nested"]["api_key"] == "[REDACTED]"
    assert payload["nested"]["context_text"] == "[REDACTED]"
    assert canary not in str(payload)
    assert payload["safe"] == "document-id-1"


def test_path_like_session_id_is_rejected(tmp_path) -> None:
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: NOW)
    with pytest.raises(ValueError, match="unsafe"):
        store.append(
            AgentEventDraft(
                session_id="../../escape",
                trace_id="trace-one",
                event_type="session.started",
            )
        )


def test_langgraph_run_persists_semantic_trajectory(tmp_path) -> None:
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: NOW)
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    adapter = LangGraphOrchestratorAdapter(
        V2ToolRegistry(navigator, clock_ms=lambda: 100.0),
        clock_ms=lambda: 100.0,
        trajectory_store=store,
    )
    request = AgentRunRequest(
        question="What is the remote policy?",
        user=user_context(),
        request_id="request-one",
        trace_id="trace-one",
        session_id="session-one",
    )

    result = adapter.run(request)
    events = store.load("session-one")

    event_types = [event.event_type for event in events]
    assert event_types[0:2] == ["session.started", "user.message"]
    assert "tool.requested" in event_types
    assert "retrieval.completed" in event_types
    assert "evidence.admitted" in event_types
    assert "citation.checked" in event_types
    assert event_types[-2:] == ["terminal.reached", "session.completed"]
    terminal = next(event for event in events if event.event_type == "terminal.reached")
    assert terminal.payload["answer"] == result.response.answer
    assert "matched_text" not in terminal.model_dump_json()
    assert store.verify("session-one") is True
