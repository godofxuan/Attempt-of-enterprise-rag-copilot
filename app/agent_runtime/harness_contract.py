from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.evalops_artifact import build_agent_run_artifact
from app.agent_runtime.evaluation import AgentRuntimeScenarioNavigator
from app.agent_runtime.orchestrator import AgentRunRequest, BoundedControllerAdapter
from app.agent_runtime.telemetry import AgentTelemetry
from app.agent_runtime.tool_policy import PolicyHookDispatcher, SQLitePolicyAuditStore
from app.agent_runtime.trajectory import SQLiteTrajectoryStore
from app.domain.agent import AgentBudget
from app.domain.queries import UserContext


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HarnessRequestV1(_StrictModel):
    schema_name: Literal["enterprise.agent-harness-request"] = (
        "enterprise.agent-harness-request"
    )
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    tenant_fixture: Literal["eval-tenant"] = "eval-tenant"
    user_fixture: Literal["eval-employee"] = "eval-employee"
    expected_evidence_policy: Literal["grounded_or_refuse"] = "grounded_or_refuse"
    timeout_ms: int = Field(default=15_000, ge=100, le=300_000)
    traceparent: str | None = Field(
        default=None,
        pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
    )
    mode: Literal["deterministic_mock", "local_real"] = "deterministic_mock"
    attempt_id: str | None = Field(default=None, min_length=1, max_length=100)


class HarnessOutputV1(_StrictModel):
    schema_name: Literal["enterprise.agent-harness-result"] = (
        "enterprise.agent-harness-result"
    )
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    attempt_id: str
    answer: str
    terminal_state: str
    citations: list[dict[str, Any]]
    tool_events: list[dict[str, Any]]
    policy_decisions: list[dict[str, Any]]
    trajectory_artifact: dict[str, Any]
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    root_span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    propagated_traceparent: str = Field(
        pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
    )
    error_classification: str


class AgentHarnessRunner:
    """Versioned boundary for EvalOps/Inspect-style consumers."""

    def __init__(
        self,
        *,
        state_root: Path,
        git_sha: str,
        telemetry: AgentTelemetry | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self.state_root.mkdir(parents=True, exist_ok=True)
        if len(git_sha) != 40 or any(char not in "0123456789abcdef" for char in git_sha):
            raise ValueError("harness requires an exact lowercase Git SHA")
        self.git_sha = git_sha
        self.telemetry = telemetry or AgentTelemetry()

    def run(self, request: HarnessRequestV1) -> HarnessOutputV1:
        attempt_id = request.attempt_id or uuid4().hex
        case_hash = hashlib.sha256(
            f"{request.case_id}:{attempt_id}".encode()
        ).hexdigest()[:20]
        session_id = f"harness-{case_hash}"
        request_id = f"request-{case_hash}"
        trajectory = SQLiteTrajectoryStore(self.state_root / "trajectory.sqlite3")
        audit = SQLitePolicyAuditStore(self.state_root / "policy_audit.sqlite3")
        hooks = PolicyHookDispatcher(audit_store=audit)
        user = _trusted_fixture(request.tenant_fixture, request.user_fixture)

        with self.telemetry.span(
            "agent.harness.api",
            operation="api",
            attributes={"case": request.case_id, "tenant": user.tenant_id},
            traceparent=request.traceparent,
        ) as api_trace:
            propagated = self.telemetry.inject()
            with self.telemetry.span(
                "agent.run",
                operation="agent",
                attributes={
                    "case": request.case_id,
                    "tenant": user.tenant_id,
                    "user": user.user_id,
                    "runtime.mode": request.mode,
                },
            ):
                orchestrator = self._build_orchestrator(
                    request,
                    trajectory=trajectory,
                    hooks=hooks,
                )
                result = orchestrator.run(
                    AgentRunRequest(
                        question=request.question,
                        user=user,
                        request_id=request_id,
                        trace_id=api_trace.trace_id,
                        session_id=session_id,
                    )
                )
            with self.telemetry.span(
                "agent.citation.verify",
                operation="citation",
                attributes={"citation.count": len(result.response.citations)},
            ):
                citations = [
                    citation.model_dump(mode="json")
                    for citation in result.response.citations
                ]
            with self.telemetry.span("agent.evalops.export", operation="evalops"):
                artifact = build_agent_run_artifact(
                    trajectory,
                    session_id,
                    case_id=request.case_id,
                    git_sha=self.git_sha,
                    trace_identity=api_trace,
                    tool_metadata={"runtime.mode": request.mode},
                )

        events = trajectory.load(session_id)
        tool_events = [
            {
                "event_type": event.event_type,
                "tool_name": event.tool_name,
                "sequence": event.sequence,
                "payload": event.payload,
            }
            for event in events
            if event.event_type in {"tool.requested", "tool.completed", "tool.failed"}
        ]
        policy_rows = [
            {
                "lifecycle": row["lifecycle"],
                "tool_name": row["tool_name"],
                "decision": row["decision"],
                "reason_code": row["reason_code"],
                "arguments_sha256": row["arguments_sha256"],
            }
            for row in audit.rows()
            if row["run_hash"] == hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        ]
        return HarnessOutputV1(
            case_id=request.case_id,
            attempt_id=attempt_id,
            answer=result.response.answer,
            terminal_state=result.response.mode,
            citations=citations,
            tool_events=tool_events,
            policy_decisions=policy_rows,
            trajectory_artifact=artifact.model_dump(mode="json"),
            trace_id=api_trace.trace_id,
            root_span_id=api_trace.span_id,
            propagated_traceparent=propagated,
            error_classification=_error_classification(result.response.mode),
        )

    def _build_orchestrator(self, request, *, trajectory, hooks):
        if request.mode == "deterministic_mock":
            registry = V2ToolRegistry(AgentRuntimeScenarioNavigator("answered"))
            return BoundedControllerAdapter(
                registry,
                budget=AgentBudget(deadline_ms=request.timeout_ms),
                trajectory_store=trajectory,
                policy_hooks=hooks,
                telemetry=self.telemetry,
            )
        return _build_local_real_orchestrator(
            timeout_ms=request.timeout_ms,
            trajectory_store=trajectory,
            policy_hooks=hooks,
            telemetry=self.telemetry,
        )


def _trusted_fixture(tenant_fixture: str, user_fixture: str) -> UserContext:
    if (tenant_fixture, user_fixture) != ("eval-tenant", "eval-employee"):
        raise PermissionError("unregistered harness identity fixture")
    return UserContext(
        user_id="eval-employee",
        tenant_id="eval-tenant",
        region="cn",
        groups=["employees"],
        roles=[],
    )


def _build_local_real_orchestrator(
    *, timeout_ms, trajectory_store, policy_hooks, telemetry
):
    from app.agent.generation_v2 import GenerationV2ResponseBuilder
    from app.config import get_settings
    from app.retrieval.navigation import DocumentNavigator
    from app.retrieval.pipeline import HybridRetrievalPipeline
    from app.retrieval.snapshot import V2IndexSnapshot
    from app.retriever import _embed_text

    settings = get_settings()
    snapshot = V2IndexSnapshot.load(settings.v2_indexes_dir)
    pipeline = HybridRetrievalPipeline(
        snapshot,
        embed_text=lambda text: _embed_text(settings.embedding_model, text),
    )
    response_builder = GenerationV2ResponseBuilder(model=settings.chat_model)
    return BoundedControllerAdapter(
        V2ToolRegistry(DocumentNavigator(snapshot, pipeline=pipeline)),
        response_builder=_TelemetryResponseBuilder(
            response_builder,
            telemetry=telemetry,
            model_name=settings.chat_model,
        ),
        budget=AgentBudget(deadline_ms=timeout_ms),
        trajectory_store=trajectory_store,
        policy_hooks=policy_hooks,
        telemetry=telemetry,
    )


class _TelemetryResponseBuilder:
    def __init__(self, delegate, *, telemetry: AgentTelemetry, model_name: str) -> None:
        self.delegate = delegate
        self.telemetry = telemetry
        self.model_name = model_name

    def build(self, **kwargs):
        with self.telemetry.span(
            "agent.model.call",
            operation="model",
            attributes={"model.name": self.model_name},
        ):
            return self.delegate.build(**kwargs)


def _error_classification(mode: str) -> str:
    return {
        "answered": "ok",
        "unsafe": "unsafe_request",
        "permission": "permission_denied",
        "not_found": "retrieval_miss",
        "security_filtered": "retrieved_content_blocked",
        "budget": "budget_exhausted",
        "system": "system_error",
        "partial": "partial_evidence",
    }.get(mode, "unknown")


__all__ = ["AgentHarnessRunner", "HarnessOutputV1", "HarnessRequestV1"]
