from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.orchestrator import (
    AgentRunRequest,
    AgentRunResult,
    LangGraphOrchestratorAdapter,
)
from app.agent_runtime.side_effects import (
    AccessRequestDraft,
    AccessRequestDraftArguments,
    SQLiteSideEffectStore,
)
from app.agent_runtime.tool_policy import (
    POLICY_VERSION,
    PolicyDecision,
    PolicyHookDispatcher,
    PolicyResult,
    ToolPolicyInput,
    normalized_arguments_sha256,
)
from app.agent_runtime.trajectory import AgentEventDraft, SQLiteTrajectoryStore
from app.agent_runtime.telemetry import AgentTelemetry, TraceIdentity
from app.domain.queries import UserContext


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DurableToolRunRequest(_StrictModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    roles: tuple[str, ...] = ()
    reviewer_user_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    traceparent: str | None = Field(
        default=None,
        pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
    )
    tool_name: Literal["create_access_request_draft"] = "create_access_request_draft"
    arguments: AccessRequestDraftArguments
    acl_decision: Literal["ALLOW", "DENY"] = "ALLOW"
    budget_exhausted: bool = False
    deadline_at_ms: float = Field(gt=0)
    authentication_expires_at_ms: float = Field(gt=0)
    approval_expires_at_ms: float = Field(gt=0)
    policy_version: Literal["tool-policy.v1"] = POLICY_VERSION


class DurableApprovalRequest(_StrictModel):
    approval_id: str = Field(min_length=1, max_length=128)
    approval_token: str = Field(min_length=32, max_length=256, repr=False)
    thread_id: str = Field(min_length=1, max_length=128)
    tool_call_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at_ms: float = Field(gt=0)
    policy_version: Literal["tool-policy.v1"] = POLICY_VERSION
    allowed_decisions: tuple[Literal["approve", "reject"], ...] = (
        "approve",
        "reject",
    )


class DurableToolRunResult(_StrictModel):
    schema_name: Literal["enterprise.durable-tool-run"] = "enterprise.durable-tool-run"
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["needs_approval", "completed", "denied", "rejected"]
    terminal_state: str
    run_id: str
    session_id: str
    trace_id: str
    policy_decision: PolicyDecision
    policy_reason: str
    approval: DurableApprovalRequest | None = None
    draft: AccessRequestDraft | None = None
    trajectory_events: tuple[str, ...] = ()


class _DurableState(TypedDict, total=False):
    request: dict[str, Any]
    policy_input: dict[str, Any]
    policy_result: dict[str, Any]
    approval_id: str
    approval: dict[str, Any]
    crash_point: str | None
    draft: dict[str, Any]
    terminal_state: str


class _ApprovalRecord(_StrictModel):
    approval_id: str
    token_sha256: str
    thread_id: str
    request: DurableToolRunRequest
    tool_call_sha256: str
    status: Literal["PENDING", "COMPLETED", "REJECTED"]
    continuation_trace: TraceIdentity
    result: DurableToolRunResult | None = None


class SQLiteApprovalStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_approvals (
                    approval_id TEXT PRIMARY KEY,
                    token_sha256 TEXT NOT NULL UNIQUE,
                    thread_id TEXT NOT NULL UNIQUE,
                    request_json TEXT NOT NULL,
                    tool_call_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETED','REJECTED')),
                    continuation_trace_json TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def create(
        self,
        request: DurableToolRunRequest,
        *,
        thread_id: str,
        tool_call_sha256: str,
        continuation_trace: TraceIdentity,
    ) -> tuple[_ApprovalRecord, str]:
        token = secrets.token_urlsafe(32)
        record = _ApprovalRecord(
            approval_id=f"approval-{secrets.token_hex(12)}",
            token_sha256=_sha256(token),
            thread_id=thread_id,
            request=request,
            tool_call_sha256=tool_call_sha256,
            status="PENDING",
            continuation_trace=continuation_trace,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO durable_approvals VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    record.approval_id,
                    record.token_sha256,
                    record.thread_id,
                    request.model_dump_json(),
                    tool_call_sha256,
                    record.status,
                    continuation_trace.model_dump_json(),
                ),
            )
        return record, token

    def by_token(self, token: str) -> _ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM durable_approvals WHERE token_sha256 = ?",
                (_sha256(token),),
            ).fetchone()
        if row is None:
            raise ValueError("approval token is invalid")
        return _ApprovalRecord(
            approval_id=row["approval_id"],
            token_sha256=row["token_sha256"],
            thread_id=row["thread_id"],
            request=DurableToolRunRequest.model_validate_json(row["request_json"]),
            tool_call_sha256=row["tool_call_sha256"],
            status=row["status"],
            continuation_trace=TraceIdentity.model_validate_json(
                row["continuation_trace_json"]
            ),
            result=(
                DurableToolRunResult.model_validate_json(row["result_json"])
                if row["result_json"]
                else None
            ),
        )

    def finish(self, approval_id: str, result: DurableToolRunResult) -> None:
        status = "REJECTED" if result.status == "rejected" else "COMPLETED"
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE durable_approvals
                SET status = ?, result_json = ?
                WHERE approval_id = ? AND status = 'PENDING'
                """,
                (status, result.model_dump_json(), approval_id),
            )


class DurableLangGraphOrchestrator:
    """Optional durable workflow; bounded remains the product default."""

    name: Literal["durable_langgraph"] = "durable_langgraph"

    def __init__(
        self,
        registry: V2ToolRegistry,
        *,
        state_dir: Path,
        clock_ms=None,
        checkpointer=None,
        policy_hooks: PolicyHookDispatcher | None = None,
        trajectory_store: SQLiteTrajectoryStore | None = None,
        telemetry: AgentTelemetry | None = None,
        tenant_status_checker: Callable[[str], bool] | None = None,
        acl_revalidator: Callable[[DurableToolRunRequest], Literal["ALLOW", "DENY"]]
        | None = None,
    ) -> None:
        self.registry = registry
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.clock_ms = clock_ms or (lambda: time.time() * 1000.0)
        self.policy_hooks = policy_hooks or PolicyHookDispatcher()
        self.approvals = SQLiteApprovalStore(self.state_dir / "approvals.sqlite3")
        self.side_effects = SQLiteSideEffectStore(self.state_dir / "side_effects.sqlite3")
        self.trajectory_store = trajectory_store
        self.telemetry = telemetry or AgentTelemetry()
        self.tenant_status_checker = tenant_status_checker or (lambda tenant_id: True)
        self.acl_revalidator = acl_revalidator or (lambda request: request.acl_decision)
        self._checkpoint_connection = None
        if checkpointer is None:
            self._checkpoint_connection = sqlite3.connect(
                self.state_dir / "langgraph_checkpoints.sqlite3",
                check_same_thread=False,
            )
            checkpointer = SqliteSaver(self._checkpoint_connection)
            checkpointer.setup()
        self.checkpointer = checkpointer
        self.graph = self._compile()

    def close(self) -> None:
        if self._checkpoint_connection is not None:
            self._checkpoint_connection.close()
            self._checkpoint_connection = None

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        result = LangGraphOrchestratorAdapter(self.registry).run(request)
        return result.model_copy(update={"orchestrator": self.name})

    def start_access_request(
        self,
        request: DurableToolRunRequest,
    ) -> DurableToolRunResult:
        policy_input = self._policy_input(
            request,
            acl_decision=self.acl_revalidator(request),
        )
        if not self.tenant_status_checker(request.tenant_id):
            return self._result(
                request,
                status="denied",
                terminal_state="TENANT_INACTIVE",
                policy_result=PolicyResult(
                    decision=PolicyDecision.DENY,
                    reason_code="tenant_inactive",
                ),
            )
        with self.telemetry.span(
            "agent.durable.start",
            operation="agent",
            traceparent=request.traceparent,
            attributes={"tenant": request.tenant_id, "run": request.run_id},
        ):
            with self.telemetry.span(
                "agent.policy.decision",
                operation="policy",
                attributes={"tool.name": request.tool_name},
            ):
                policy_result = self.policy_hooks.pre_tool_use(policy_input)
        if policy_result.decision == PolicyDecision.DENY:
            return self._result(
                request,
                status="denied",
                terminal_state="POLICY_DENIED",
                policy_result=policy_result,
            )
        if policy_result.decision != PolicyDecision.ASK:
            raise RuntimeError("side-effect tool must require approval")
        thread_id = _stable_thread_id(request)
        with self.telemetry.span(
            "agent.approval.interrupt",
            operation="interrupt",
            attributes={"tool.name": request.tool_name, "run": request.run_id},
        ) as continuation_trace:
            record, raw_token = self.approvals.create(
                request,
                thread_id=thread_id,
                tool_call_sha256=policy_input.normalized_arguments_sha256,
                continuation_trace=continuation_trace,
            )
            self._record_start(request, record.approval_id)
            state = self.graph.invoke(
                {
                    "request": request.model_dump(mode="json"),
                    "policy_input": policy_input.model_dump(mode="json"),
                    "policy_result": policy_result.model_dump(mode="json"),
                    "approval_id": record.approval_id,
                },
                config=self._config(thread_id),
            )
        if "__interrupt__" not in state:
            raise RuntimeError("durable workflow did not pause before side effect")
        approval = DurableApprovalRequest(
            approval_id=record.approval_id,
            approval_token=raw_token,
            thread_id=thread_id,
            tool_call_sha256=record.tool_call_sha256,
            expires_at_ms=request.approval_expires_at_ms,
        )
        return self._result(
            request,
            status="needs_approval",
            terminal_state="INTERRUPTED",
            policy_result=policy_result,
            approval=approval,
        )

    def resume_access_request(
        self,
        approval_token: str,
        *,
        decision: Literal["approve", "reject"],
        reviewer: UserContext,
        expected_tool_call_sha256: str,
        crash_point: Literal["before_commit", "after_commit"] | None = None,
    ) -> DurableToolRunResult:
        record = self.approvals.by_token(approval_token)
        request = record.request
        now = float(self.clock_ms())
        if not self.tenant_status_checker(request.tenant_id):
            raise PermissionError("tenant is no longer active")
        if reviewer.tenant_id != request.tenant_id:
            raise PermissionError("reviewer belongs to a different tenant")
        if reviewer.user_id != request.reviewer_user_id:
            raise PermissionError("reviewer identity is not bound to this approval")
        if "knowledge_reviewer" not in reviewer.roles:
            raise PermissionError("knowledge_reviewer role is required")
        if expected_tool_call_sha256 != record.tool_call_sha256:
            raise PermissionError("tool arguments changed after approval was requested")
        if record.status != "PENDING":
            if record.result is None:
                raise RuntimeError("completed approval has no persisted result")
            completed_decision = (
                "reject" if record.result.status == "rejected" else "approve"
            )
            if decision != completed_decision:
                raise ValueError("approval decision conflicts with completed result")
            return record.result
        if now >= request.approval_expires_at_ms:
            raise PermissionError("approval has expired")
        current_policy = self.policy_hooks.pre_tool_use(
            self._policy_input(
                request,
                acl_decision=self.acl_revalidator(request),
            )
        )
        if current_policy.decision != PolicyDecision.ASK:
            raise PermissionError("current policy no longer permits approval")
        config = self._config(record.thread_id)
        snapshot = self.graph.get_state(config)
        if "execute_side_effect" in snapshot.next:
            persisted_decision = snapshot.values.get("approval", {}).get("decision")
            if persisted_decision != decision:
                raise ValueError("approval decision was already checkpointed")
            self.graph.update_state(config, {"crash_point": crash_point})
            graph_input = None
        else:
            graph_input = Command(
                resume={
                    "decision": decision,
                    "crash_point": crash_point,
                }
            )
        with self.telemetry.span(
            "agent.approval.resume",
            operation="resume",
            continuation=record.continuation_trace,
            attributes={"tenant": request.tenant_id, "run": request.run_id},
        ):
            state = self.graph.invoke(graph_input, config=config)
        if "__interrupt__" in state:
            raise RuntimeError("workflow remained interrupted after a valid decision")
        policy_result = PolicyResult.model_validate(state["policy_result"])
        effective_decision = state.get("approval", {}).get("decision", decision)
        if effective_decision == "reject":
            result = self._result(
                request,
                status="rejected",
                terminal_state="HUMAN_REJECTED",
                policy_result=policy_result,
            )
        else:
            result = self._result(
                request,
                status="completed",
                terminal_state=state["terminal_state"],
                policy_result=policy_result,
                draft=AccessRequestDraft.model_validate(state["draft"]),
            )
        self._record_completion(request, result, reviewer)
        if self.trajectory_store is not None:
            result = result.model_copy(
                update={
                    "trajectory_events": tuple(
                        event.event_type
                        for event in self.trajectory_store.load(request.session_id)
                    )
                }
            )
        self.approvals.finish(record.approval_id, result)
        return result

    def _compile(self):
        builder = StateGraph(_DurableState)
        builder.add_node("approval", self._approval_node)
        builder.add_node("execute_side_effect", self._execute_side_effect_node)
        builder.add_node("reject", lambda state: {"terminal_state": "HUMAN_REJECTED"})
        builder.add_edge(START, "approval")
        builder.add_conditional_edges(
            "approval",
            lambda state: (
                "execute_side_effect"
                if state["approval"]["decision"] == "approve"
                else "reject"
            ),
            {"execute_side_effect": "execute_side_effect", "reject": "reject"},
        )
        builder.add_edge("execute_side_effect", END)
        builder.add_edge("reject", END)
        return builder.compile(checkpointer=self.checkpointer)

    @staticmethod
    def _approval_node(state: _DurableState) -> dict[str, Any]:
        value = interrupt(
            {
                "schema_name": "enterprise.tool-approval",
                "schema_version": "1.0",
                "approval_id": state["approval_id"],
                "tool_name": state["policy_input"]["tool_name"],
                "tool_call_sha256": state["policy_input"]["normalized_arguments_sha256"],
                "policy_version": state["policy_input"]["policy_version"],
                "allowed_decisions": ["approve", "reject"],
            }
        )
        if value.get("decision") not in {"approve", "reject"}:
            value = {"decision": "reject", "crash_point": None}
        return {"approval": value, "crash_point": value.get("crash_point")}

    def _execute_side_effect_node(self, state: _DurableState) -> dict[str, Any]:
        with self.telemetry.span(
            "agent.tool.create_access_request_draft",
            operation="tool",
            attributes={"tool.name": "create_access_request_draft"},
        ):
            draft = self.side_effects.create_access_request_draft(
                ToolPolicyInput.model_validate(state["policy_input"]),
                DurableToolRunRequest.model_validate(state["request"]).arguments,
                crash_point=state.get("crash_point"),
            )
        return {"draft": draft.model_dump(mode="json"), "terminal_state": "DRAFT_CREATED"}

    def _policy_input(
        self,
        request: DurableToolRunRequest,
        *,
        acl_decision: Literal["ALLOW", "DENY"] | None = None,
    ) -> ToolPolicyInput:
        return ToolPolicyInput(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            roles=request.roles,
            session_id=request.session_id,
            run_id=request.run_id,
            tool_name=request.tool_name,
            normalized_arguments_sha256=normalized_arguments_sha256(request.arguments),
            acl_decision=acl_decision or request.acl_decision,
            budget_exhausted=request.budget_exhausted,
            deadline_at_ms=request.deadline_at_ms,
            authentication_expires_at_ms=request.authentication_expires_at_ms,
            evaluated_at_ms=float(self.clock_ms()),
            tool_risk=self.policy_hooks.policy.risk_for(request.tool_name),
            policy_version=request.policy_version,
        )

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}

    def _result(
        self,
        request: DurableToolRunRequest,
        *,
        status: Literal["needs_approval", "completed", "denied", "rejected"],
        terminal_state: str,
        policy_result: PolicyResult,
        approval: DurableApprovalRequest | None = None,
        draft: AccessRequestDraft | None = None,
    ) -> DurableToolRunResult:
        events = ()
        if self.trajectory_store is not None:
            events = tuple(
                event.event_type for event in self.trajectory_store.load(request.session_id)
            )
        return DurableToolRunResult(
            status=status,
            terminal_state=terminal_state,
            run_id=request.run_id,
            session_id=request.session_id,
            trace_id=request.trace_id,
            policy_decision=policy_result.decision,
            policy_reason=policy_result.reason_code,
            approval=approval,
            draft=draft,
            trajectory_events=events,
        )

    def _record_start(self, request: DurableToolRunRequest, approval_id: str) -> None:
        if self.trajectory_store is None:
            return
        self.trajectory_store.append(
            AgentEventDraft(
                session_id=request.session_id,
                trace_id=request.trace_id,
                event_type="session.started",
                payload={"orchestrator": self.name, "run_id": request.run_id},
            )
        )
        self.trajectory_store.append(
            AgentEventDraft(
                session_id=request.session_id,
                trace_id=request.trace_id,
                event_type="human_review.requested",
                payload={
                    "approval_id": approval_id,
                    "tool_name": request.tool_name,
                    "arguments_sha256": normalized_arguments_sha256(request.arguments),
                },
            )
        )

    def _record_completion(
        self,
        request: DurableToolRunRequest,
        result: DurableToolRunResult,
        reviewer: UserContext,
    ) -> None:
        if self.trajectory_store is None:
            return
        for event_type, payload in (
            (
                "human_review.completed",
                {"decision": result.status, "reviewer_sha256": _sha256(reviewer.user_id)},
            ),
            (
                "terminal.reached",
                {"terminal_state": result.terminal_state},
            ),
            (
                "session.completed",
                {"status": result.status},
            ),
        ):
            self.trajectory_store.append(
                AgentEventDraft(
                    session_id=request.session_id,
                    trace_id=request.trace_id,
                    event_type=event_type,
                    payload=payload,
                    terminal_reason=(result.terminal_state if event_type == "terminal.reached" else None),
                )
            )


def _stable_thread_id(request: DurableToolRunRequest) -> str:
    digest = _sha256(
        json.dumps(
            {
                "tenant": request.tenant_id,
                "user": request.user_id,
                "run": request.run_id,
                "session": request.session_id,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return f"durable-{digest[:48]}"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "DurableApprovalRequest",
    "DurableLangGraphOrchestrator",
    "DurableToolRunRequest",
    "DurableToolRunResult",
    "SQLiteApprovalStore",
]
