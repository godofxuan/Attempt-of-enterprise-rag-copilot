from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools_v2 import V2ToolRegistry
from app.agent_runtime.durable_store import (
    ApprovalRecord,
    CompletionEnvelope,
    DurableStoreConflict,
    InjectedIntegrityCrash,
    IntegrityCrashPoint,
    ResumeOutcome,
    SQLiteDurableWorkflowStore,
)
from app.agent_runtime.side_effects import (
    AccessRequestDraft,
    AccessRequestDraftArguments,
)
from app.agent_runtime.telemetry import AgentTelemetry, TraceIdentity
from app.agent_runtime.tool_policy import (
    POLICY_VERSION,
    PolicyDecision,
    PolicyHookDispatcher,
    PolicyResult,
    ToolPolicyInput,
    normalized_arguments_sha256,
)
from app.agent_runtime.trajectory import AgentEventDraft, AgentEventType, SQLiteTrajectoryStore
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
    status: Literal[
        "needs_approval",
        "completed",
        "denied",
        "rejected",
        "already_resuming",
        "expired",
        "failed_recoverable",
    ]
    terminal_state: str
    run_id: str
    session_id: str
    trace_id: str
    policy_decision: PolicyDecision
    policy_reason: str
    approval: DurableApprovalRequest | None = None
    draft: AccessRequestDraft | None = None
    trajectory_events: tuple[str, ...] = ()
    resume_outcome: ResumeOutcome | None = None


class _DurableState(TypedDict, total=False):
    request: dict[str, Any]
    policy_input: dict[str, Any]
    policy_result: dict[str, Any]
    approval_id: str
    approval: dict[str, Any]
    crash_point: str | None
    draft: dict[str, Any]
    terminal_state: str


class DurableAccessRequestWorkflow:
    """Durable workflow only for the access-request DRAFT approval path."""

    name: Literal["durable_access_request"] = "durable_access_request"

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
        acl_revalidator: Callable[[DurableToolRunRequest], Literal["ALLOW", "DENY"]] | None = None,
        resume_lease_ms: float = 30_000.0,
        after_resume_acquired: Callable[[ApprovalRecord], None] | None = None,
    ) -> None:
        if resume_lease_ms <= 0:
            raise ValueError("resume lease must be positive")
        self.registry = registry
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.clock_ms = clock_ms or (lambda: time.time() * 1000.0)
        self.policy_hooks = policy_hooks or PolicyHookDispatcher()
        # Reuse the v1 approval file so pending approvals survive an in-place upgrade.
        self.store = SQLiteDurableWorkflowStore(self.state_dir / "approvals.sqlite3")
        self.approvals = self.store
        self.side_effects = self.store
        self.trajectory_store = trajectory_store
        self.telemetry = telemetry or AgentTelemetry()
        self.tenant_status_checker = tenant_status_checker or (lambda tenant_id: True)
        self.acl_revalidator = acl_revalidator or (lambda request: request.acl_decision)
        self.resume_lease_ms = float(resume_lease_ms)
        self.after_resume_acquired = after_resume_acquired
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
            record, raw_token = self.store.create(
                request_json=request.model_dump_json(),
                approval_expires_at_ms=request.approval_expires_at_ms,
                thread_id=thread_id,
                tool_call_sha256=policy_input.normalized_arguments_sha256,
                continuation_trace_json=continuation_trace.model_dump_json(),
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
        crash_point: IntegrityCrashPoint | None = None,
    ) -> DurableToolRunResult:
        record = self.store.by_token(approval_token)
        request = DurableToolRunRequest.model_validate_json(record.request_json)
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
        if record.status in {"COMPLETED", "REJECTED", "EXPIRED"}:
            claim = self.store.claim_resume(
                approval_id=record.approval_id,
                approval_token=approval_token,
                decision=decision,
                resumed_by=reviewer.user_id,
                now_ms=now,
                lease_ms=self.resume_lease_ms,
            )
            return self._stable_claim_result(claim, request, decision)
        if now >= request.approval_expires_at_ms:
            claim = self.store.claim_resume(
                approval_id=record.approval_id,
                approval_token=approval_token,
                decision=decision,
                resumed_by=reviewer.user_id,
                now_ms=now,
                lease_ms=self.resume_lease_ms,
            )
            return self._stable_claim_result(claim, request, decision)
        current_policy = self.policy_hooks.pre_tool_use(
            self._policy_input(
                request,
                acl_decision=self.acl_revalidator(request),
            )
        )
        if current_policy.decision != PolicyDecision.ASK:
            raise PermissionError("current policy no longer permits approval")
        claim = self.store.claim_resume(
            approval_id=record.approval_id,
            approval_token=approval_token,
            decision=decision,
            resumed_by=reviewer.user_id,
            now_ms=now,
            lease_ms=self.resume_lease_ms,
        )
        if claim.outcome not in {ResumeOutcome.ACQUIRED, ResumeOutcome.RECOVERED}:
            return self._stable_claim_result(claim, request, decision)
        if claim.owner_token is None:
            raise RuntimeError("acquired approval is missing an owner token")
        if self.after_resume_acquired is not None:
            self.after_resume_acquired(claim.record)

        try:
            state = self._resume_graph(claim.record, decision)
            policy_result = PolicyResult.model_validate(state["policy_result"])
            effective_decision = state.get("approval", {}).get("decision", decision)
            if effective_decision != decision:
                raise ValueError("approval decision conflicts with checkpointed state")
            continuation = TraceIdentity.model_validate_json(claim.record.continuation_trace_json)
            with self.telemetry.span(
                "agent.approval.resume",
                operation="resume",
                continuation=continuation,
                attributes={
                    "tenant": request.tenant_id,
                    "run": request.run_id,
                    "approval.outcome": claim.outcome.value,
                    "approval.version": claim.record.version,
                },
            ):
                if decision == "reject":
                    result = self._completion_result(
                        self._result(
                            request,
                            status="rejected",
                            terminal_state="HUMAN_REJECTED",
                            policy_result=policy_result,
                            resume_outcome=claim.outcome,
                        )
                    )
                    result_data = self.store.finalize_rejected(
                        approval_id=record.approval_id,
                        owner_token=claim.owner_token,
                        version=claim.record.version,
                        now_ms=float(self.clock_ms()),
                        result=result.model_dump(mode="json"),
                        completion=self._completion_envelope(
                            record.approval_id,
                            request,
                            result,
                            reviewer,
                            decision,
                        ),
                    )
                    result = DurableToolRunResult.model_validate(result_data)
                else:
                    with self.telemetry.span(
                        "agent.side_effect.commit",
                        operation="side_effect",
                        attributes={
                            "tool.name": request.tool_name,
                            "side_effect.status": "COMMITTED",
                            "approval.version": claim.record.version,
                        },
                    ):
                        _, result_data = self.store.finalize_approved(
                            approval_id=record.approval_id,
                            owner_token=claim.owner_token,
                            version=claim.record.version,
                            now_ms=float(self.clock_ms()),
                            policy_input=ToolPolicyInput.model_validate(state["policy_input"]),
                            arguments=request.arguments,
                            result_factory=lambda draft: self._completion_result(
                                self._result(
                                    request,
                                    status="completed",
                                    terminal_state="DRAFT_CREATED",
                                    policy_result=policy_result,
                                    draft=draft,
                                    resume_outcome=claim.outcome,
                                )
                            ).model_dump(mode="json"),
                            completion_factory=lambda data: self._completion_envelope(
                                record.approval_id,
                                request,
                                DurableToolRunResult.model_validate(data),
                                reviewer,
                                decision,
                            ),
                            crash_point=crash_point,
                        )
                    result = DurableToolRunResult.model_validate(result_data)
        except (InjectedIntegrityCrash, DurableStoreConflict):
            raise
        except Exception as exc:
            try:
                self.store.mark_failed_recoverable(
                    approval_id=record.approval_id,
                    owner_token=claim.owner_token,
                    version=claim.record.version,
                    now_ms=float(self.clock_ms()),
                    failure_code=type(exc).__name__,
                )
            except DurableStoreConflict:
                pass
            raise

        self._drain_completion(record.approval_id)
        return result

    def _stable_claim_result(
        self,
        claim,
        request: DurableToolRunRequest,
        decision: Literal["approve", "reject"],
    ) -> DurableToolRunResult:
        if claim.outcome in {ResumeOutcome.ALREADY_COMPLETED, ResumeOutcome.REJECTED}:
            if claim.record.result_json is None:
                raise RuntimeError("terminal approval has no persisted result")
            result = DurableToolRunResult.model_validate_json(claim.record.result_json)
            persisted_decision = "reject" if result.status == "rejected" else "approve"
            if persisted_decision != decision:
                raise ValueError("approval decision conflicts with completed result")
            self._drain_completion(claim.record.approval_id)
            return result.model_copy(update={"resume_outcome": claim.outcome})
        policy_result = PolicyResult(
            decision=(
                PolicyDecision.DENY
                if claim.outcome == ResumeOutcome.EXPIRED
                else PolicyDecision.ASK
            ),
            reason_code=(
                "approval_expired"
                if claim.outcome == ResumeOutcome.EXPIRED
                else "approval_already_resuming"
            ),
        )
        return self._result(
            request,
            status=("expired" if claim.outcome == ResumeOutcome.EXPIRED else "already_resuming"),
            terminal_state=claim.outcome.value,
            policy_result=policy_result,
            resume_outcome=claim.outcome,
        )

    def _resume_graph(
        self,
        record: ApprovalRecord,
        decision: Literal["approve", "reject"],
    ) -> dict[str, Any]:
        config = self._config(record.thread_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.next and snapshot.values.get("approval"):
            persisted_decision = snapshot.values["approval"].get("decision")
            if persisted_decision != decision:
                raise ValueError("approval decision was already checkpointed")
            return dict(snapshot.values)
        if "prepare_side_effect" in snapshot.next:
            persisted_decision = snapshot.values.get("approval", {}).get("decision")
            if persisted_decision != decision:
                raise ValueError("approval decision was already checkpointed")
            graph_input = None
        else:
            graph_input = Command(resume={"decision": decision})
        state = self.graph.invoke(graph_input, config=config)
        if "__interrupt__" in state:
            raise RuntimeError("workflow remained interrupted after a valid decision")
        return state

    def _completion_result(
        self,
        result: DurableToolRunResult,
    ) -> DurableToolRunResult:
        if self.trajectory_store is None:
            return result
        events = list(result.trajectory_events)
        for event_type in (
            "human_review.completed",
            "terminal.reached",
            "session.completed",
        ):
            if event_type not in events:
                events.append(event_type)
        return result.model_copy(update={"trajectory_events": tuple(events)})

    @staticmethod
    def _completion_envelope(
        approval_id: str,
        request: DurableToolRunRequest,
        result: DurableToolRunResult,
        reviewer: UserContext,
        decision: Literal["approve", "reject"],
    ) -> CompletionEnvelope:
        return CompletionEnvelope(
            approval_id=approval_id,
            session_id=request.session_id,
            trace_id=request.trace_id,
            decision=decision,
            result_status=result.status,
            terminal_state=result.terminal_state,
            reviewer_sha256=_sha256(reviewer.user_id),
        )

    def _drain_completion(self, approval_id: str) -> None:
        envelope = self.store.completion(approval_id)
        if envelope is None:
            return
        if self.trajectory_store is not None:
            for event_type, payload, terminal_reason in (
                (
                    "human_review.completed",
                    {
                        "decision": envelope.result_status,
                        "reviewer_sha256": envelope.reviewer_sha256,
                    },
                    None,
                ),
                (
                    "terminal.reached",
                    {"terminal_state": envelope.terminal_state},
                    envelope.terminal_state,
                ),
                (
                    "session.completed",
                    {"status": envelope.result_status},
                    None,
                ),
            ):
                self.trajectory_store.append(
                    AgentEventDraft(
                        session_id=envelope.session_id,
                        trace_id=envelope.trace_id,
                        event_type=event_type,
                        payload=payload,
                        terminal_reason=terminal_reason,
                    ),
                    idempotency_key=f"{approval_id}:{event_type}",
                )
        self.store.mark_completion_delivered(
            approval_id,
            delivered_at_ms=float(self.clock_ms()),
        )

    def _compile(self):
        builder = StateGraph(_DurableState)
        builder.add_node("approval", self._approval_node)
        builder.add_node("prepare_side_effect", self._prepare_side_effect_node)
        builder.add_node("reject", lambda state: {"terminal_state": "HUMAN_REJECTED"})
        builder.add_edge(START, "approval")
        builder.add_conditional_edges(
            "approval",
            lambda state: (
                "prepare_side_effect" if state["approval"]["decision"] == "approve" else "reject"
            ),
            {"prepare_side_effect": "prepare_side_effect", "reject": "reject"},
        )
        builder.add_edge("prepare_side_effect", END)
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
        return {"approval": value}

    @staticmethod
    def _prepare_side_effect_node(state: _DurableState) -> dict[str, Any]:
        return {"terminal_state": "DRAFT_READY"}

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
        status: Literal[
            "needs_approval",
            "completed",
            "denied",
            "rejected",
            "already_resuming",
            "expired",
            "failed_recoverable",
        ],
        terminal_state: str,
        policy_result: PolicyResult,
        approval: DurableApprovalRequest | None = None,
        draft: AccessRequestDraft | None = None,
        resume_outcome: ResumeOutcome | None = None,
    ) -> DurableToolRunResult:
        events: tuple[AgentEventType, ...] = ()
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
            resume_outcome=resume_outcome,
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


class DurableLangGraphOrchestrator(DurableAccessRequestWorkflow):
    """Deprecated name retained for import compatibility only."""

    def __init__(self, *args, **kwargs) -> None:
        warnings.warn(
            "DurableLangGraphOrchestrator only covers the access-request DRAFT "
            "workflow; use DurableAccessRequestWorkflow",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)


SQLiteApprovalStore = SQLiteDurableWorkflowStore


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
    "DurableAccessRequestWorkflow",
    "DurableLangGraphOrchestrator",
    "DurableToolRunRequest",
    "DurableToolRunResult",
    "SQLiteApprovalStore",
]
