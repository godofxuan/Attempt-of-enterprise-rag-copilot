from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.trajectory import AgentEvent, SQLiteTrajectoryStore


class ReplayToolStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    tool_name: str
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    status: str
    error_code: str | None = None


class AgentTrajectoryReplay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    session_id: str
    trace_id: str
    integrity_verified: bool
    input: dict[str, Any]
    tool_steps: list[ReplayToolStep]
    evidence: list[dict[str, Any]]
    final_output: dict[str, Any]
    terminal_reason: str | None
    event_count: int = Field(ge=1)


def replay_trajectory(
    store: SQLiteTrajectoryStore,
    session_id: str,
) -> AgentTrajectoryReplay:
    events = store.load(session_id)
    if not events:
        raise ValueError("agent trajectory does not exist")
    if not store.verify(session_id):
        raise ValueError("agent trajectory integrity verification failed")

    user_input: dict[str, Any] = {}
    pending: dict[str, dict[str, Any]] = {}
    steps: list[ReplayToolStep] = []
    evidence: list[dict[str, Any]] = []
    evidence_keys: set[str] = set()
    final_output: dict[str, Any] = {}
    terminal_reason: str | None = None

    for event in events:
        if event.event_type == "user.message":
            user_input = dict(event.payload)
        elif event.event_type == "tool.requested" and event.step_id:
            pending[event.step_id] = {
                "tool_name": event.tool_name or "unknown",
                "request": dict(event.payload),
            }
        elif event.event_type in {"tool.completed", "tool.failed"} and event.step_id:
            request = pending.pop(event.step_id, {})
            steps.append(
                ReplayToolStep(
                    step_id=event.step_id,
                    tool_name=event.tool_name or request.get("tool_name", "unknown"),
                    request=request.get("request", {}),
                    result=dict(event.payload),
                    status="ok" if event.event_type == "tool.completed" else "error",
                    error_code=event.error_code,
                )
            )
        elif event.event_type == "evidence.admitted":
            for item in event.payload.get("items", []):
                key = _evidence_key(item)
                if key not in evidence_keys:
                    evidence_keys.add(key)
                    evidence.append(dict(item))
        elif event.event_type == "terminal.reached":
            final_output = dict(event.payload)
            terminal_reason = event.terminal_reason

    if not final_output:
        raise ValueError("agent trajectory has no terminal output")
    return AgentTrajectoryReplay(
        session_id=events[0].session_id,
        trace_id=events[0].trace_id,
        integrity_verified=True,
        input=user_input,
        tool_steps=steps,
        evidence=evidence,
        final_output=final_output,
        terminal_reason=terminal_reason,
        event_count=len(events),
    )


def _evidence_key(item: dict[str, Any]) -> str:
    return "|".join(
        str(item.get(field, ""))
        for field in ("doc_id", "chunk_id", "target_id", "version_id")
    )


__all__ = ["AgentTrajectoryReplay", "ReplayToolStep", "replay_trajectory"]

