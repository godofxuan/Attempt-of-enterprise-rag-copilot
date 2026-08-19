from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.replay import replay_trajectory
from app.agent_runtime.trajectory import AgentEvent, SQLiteTrajectoryStore


class AgentRunArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_name: Literal["enterprise.agent-run"] = "enterprise.agent-run"
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=200)
    git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    input: dict[str, Any]
    output: dict[str, Any]
    trajectory: list[AgentEvent] = Field(min_length=1)
    retrieval: dict[str, Any]
    evidence: dict[str, Any]
    usage: dict[str, Any]
    terminal: dict[str, Any]
    source_trajectory_root_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_agent_run_artifact(
    store: SQLiteTrajectoryStore,
    session_id: str,
    *,
    case_id: str,
    git_sha: str,
) -> AgentRunArtifactV1:
    replay = replay_trajectory(store, session_id)
    events = store.load(session_id)
    values = {
        "schema_name": "enterprise.agent-run",
        "schema_version": "1.0",
        "run_id": session_id,
        "case_id": case_id,
        "git_sha": git_sha,
        "created_at": events[-1].timestamp,
        "session_id": session_id,
        "trace_id": replay.trace_id,
        "input": replay.input,
        "output": replay.final_output,
        "trajectory": events,
        "retrieval": {
            "tool_steps": [step.model_dump(mode="json") for step in replay.tool_steps]
        },
        "evidence": {
            "admitted": replay.evidence,
            "admitted_count": len(replay.evidence),
        },
        "usage": _usage(events),
        "terminal": {
            "mode": replay.final_output.get("mode"),
            "reason": replay.terminal_reason,
            "completed": events[-1].event_type == "session.completed",
        },
        "source_trajectory_root_hash": events[-1].event_hash,
    }
    artifact_hash = hashlib.sha256(
        _canonical_json(_jsonable(values)).encode("utf-8")
    ).hexdigest()
    return AgentRunArtifactV1(**values, artifact_sha256=artifact_hash)


def verify_agent_run_artifact(artifact: AgentRunArtifactV1) -> bool:
    if not isinstance(artifact, AgentRunArtifactV1):
        raise TypeError("artifact verifier requires AgentRunArtifactV1")
    if not artifact.trajectory:
        return False
    if artifact.trajectory[-1].event_hash != artifact.source_trajectory_root_hash:
        return False
    if artifact.trajectory[0].session_id != artifact.session_id:
        return False
    previous_hash = None
    for sequence, event in enumerate(artifact.trajectory, start=1):
        if event.session_id != artifact.session_id or event.trace_id != artifact.trace_id:
            return False
        if event.sequence != sequence or event.previous_hash != previous_hash:
            return False
        event_values = event.model_dump(mode="json", exclude={"event_hash"})
        event_hash = hashlib.sha256(
            _canonical_json(event_values).encode("utf-8")
        ).hexdigest()
        if event_hash != event.event_hash:
            return False
        previous_hash = event.event_hash
    artifact_values = artifact.model_dump(
        mode="json",
        exclude={"artifact_sha256"},
    )
    expected = hashlib.sha256(
        _canonical_json(artifact_values).encode("utf-8")
    ).hexdigest()
    return expected == artifact.artifact_sha256


def _usage(events: list[AgentEvent]) -> dict[str, Any]:
    return {
        "trajectory_event_count": len(events),
        "tool_call_count": sum(event.event_type == "tool.requested" for event in events),
        "model_call_count": sum(event.event_type == "model.requested" for event in events),
        "token_usage": sum(event.token_usage or 0 for event in events),
        "cost_usd": round(sum(event.cost_usd or 0.0 for event in events), 8),
        "recorded_latency_ms": round(sum(event.latency_ms or 0.0 for event in events), 3),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "AgentRunArtifactV1",
    "build_agent_run_artifact",
    "verify_agent_run_artifact",
]

