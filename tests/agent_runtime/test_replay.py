from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.orchestrator import AgentRunRequest, BoundedControllerAdapter
from app.agent_runtime.replay import replay_trajectory
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context


def completed_store(tmp_path):
    path = tmp_path / "trajectory.sqlite3"
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    store = SQLiteTrajectoryStore(path, now=lambda: now)
    navigator = RecordingNavigator(search_results=[search_result([search_hit()])])
    adapter = BoundedControllerAdapter(
        V2ToolRegistry(navigator, clock_ms=lambda: 100.0),
        clock_ms=lambda: 100.0,
        trajectory_store=store,
    )
    adapter.run(
        AgentRunRequest(
            question="What is the remote policy?",
            user=user_context(),
            request_id="request-one",
            trace_id="trace-one",
            session_id="session-one",
        )
    )
    return path, store


def test_replay_reconstructs_input_tools_evidence_and_terminal(tmp_path) -> None:
    _, store = completed_store(tmp_path)

    replay = replay_trajectory(store, "session-one")

    assert replay.integrity_verified is True
    assert replay.input == {"question": "What is the remote policy?"}
    assert len(replay.tool_steps) == 1
    assert replay.tool_steps[0].tool_name == "search"
    assert replay.tool_steps[0].request["tool_call_id"] == "agent-step-1"
    assert replay.evidence[0]["chunk_id"] == "chunk-a"
    assert replay.final_output["mode"] == "answered"
    assert replay.terminal_reason == "completed"


def test_replay_rejects_tampered_event_even_if_trigger_is_removed(tmp_path) -> None:
    path, store = completed_store(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER agent_events_no_update")
        row = connection.execute(
            "SELECT event_json FROM agent_events WHERE sequence = 2"
        ).fetchone()
        payload = json.loads(row[0])
        payload["payload"]["question"] = "forged"
        connection.execute(
            "UPDATE agent_events SET event_json = ? WHERE sequence = 2",
            (json.dumps(payload),),
        )

    with pytest.raises(ValueError, match="integrity"):
        replay_trajectory(store, "session-one")


def test_replay_requires_completed_terminal(tmp_path) -> None:
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3")
    from app.agent_runtime.trajectory import AgentEventDraft

    store.append(
        AgentEventDraft(
            session_id="session-one",
            trace_id="trace-one",
            event_type="session.started",
        )
    )
    with pytest.raises(ValueError, match="terminal"):
        replay_trajectory(store, "session-one")


def test_replay_cli_outputs_verified_json(tmp_path) -> None:
    path, _ = completed_store(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.replay_agent_trajectory",
            "--store",
            str(path),
            "--session-id",
            "session-one",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["integrity_verified"] is True
    assert payload["final_output"]["mode"] == "answered"

