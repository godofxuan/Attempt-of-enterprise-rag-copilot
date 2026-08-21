from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.evalops_artifact import (
    AgentRunArtifactV1,
    build_agent_run_artifact,
    verify_agent_run_artifact,
)
from app.agent_runtime.orchestrator import AgentRunRequest, BoundedControllerAdapter
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from tests.v2_test_support import RecordingNavigator, search_hit, search_result, user_context


ROOT = Path(__file__).resolve().parents[2]


def artifact(tmp_path) -> AgentRunArtifactV1:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    store = SQLiteTrajectoryStore(tmp_path / "trajectory.sqlite3", now=lambda: now)
    adapter = BoundedControllerAdapter(
        V2ToolRegistry(
            RecordingNavigator(search_results=[search_result([search_hit()])]),
            clock_ms=lambda: 100.0,
        ),
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
    return build_agent_run_artifact(
        store,
        "session-one",
        case_id="case-one",
        git_sha="a" * 40,
    )


def test_artifact_contains_evalops_layers_and_verifies(tmp_path) -> None:
    result = artifact(tmp_path)

    assert result.schema_name == "enterprise.agent-run"
    assert result.input["question"] == "What is the remote policy?"
    assert result.output["mode"] == "answered"
    assert result.retrieval["tool_steps"][0]["tool_name"] == "search"
    assert result.evidence["admitted"][0]["chunk_id"] == "chunk-a"
    assert result.usage["tool_call_count"] == 1
    assert len(result.trace_context.trace_id) == 32
    assert len(result.trace_context.root_span_id) == 16
    assert result.trace_context.content_capture_policy == "off"
    assert result.terminal == {
        "mode": "answered",
        "reason": "completed",
        "completed": True,
    }
    assert verify_agent_run_artifact(result) is True


def test_artifact_hash_detects_output_mutation(tmp_path) -> None:
    result = artifact(tmp_path)
    values = result.model_dump(mode="python")
    values["output"]["answer"] = "forged answer"
    forged = AgentRunArtifactV1(**values)

    assert verify_agent_run_artifact(forged) is False


def test_artifact_roundtrip_and_schema_are_stable(tmp_path) -> None:
    result = artifact(tmp_path)
    loaded = AgentRunArtifactV1.model_validate_json(result.model_dump_json())
    schema = AgentRunArtifactV1.model_json_schema()

    assert verify_agent_run_artifact(loaded) is True
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert "trajectory" in schema["required"]


def test_artifact_does_not_contain_raw_retrieval_fields_or_secrets(tmp_path) -> None:
    serialized = artifact(tmp_path).model_dump_json()

    assert "context_text" not in serialized
    assert "matched_text" not in serialized
    assert "session_handle" not in serialized
    assert "api_key" not in serialized


def test_tracked_public_sample_and_schema_are_valid() -> None:
    artifact_path = (
        ROOT
        / "docs"
        / "agent_runtime"
        / "evidence"
        / "agent_run_artifact_sample_v1.json"
    )
    schema_path = (
        ROOT
        / "docs"
        / "agent_runtime"
        / "schemas"
        / "agent_run_artifact_v1.schema.json"
    )
    result = AgentRunArtifactV1.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert verify_agent_run_artifact(result) is True
    assert result.git_sha == "9ff917bdf99b971a59754b731176e85d61f570e6"
    assert schema["properties"]["schema_name"]["const"] == "enterprise.agent-run"
