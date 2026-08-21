# Production Runtime Architecture

Status: mechanism candidate, not production readiness evidence.

## Runtime planes

```text
trusted API / harness fixture
  -> AgentOrchestrator (bounded default; LangGraph alternatives optional)
  -> ToolGateway
       -> deterministic ToolPolicy: DENY > ASK > ALLOW
       -> pre_tool_use hooks
       -> identity / ACL / budget / deadline checks
       -> guarded V2 tool registry
       -> post_tool_use schema + guarded-payload validation
  -> citation/publication gate

ASK side-effect path
  -> DurableLangGraphOrchestrator
  -> persistent checkpoint + JSON interrupt
  -> server-side approval record (raw token is never stored)
  -> resume identity/policy/hash revalidation
  -> idempotent SQLite command + access-request DRAFT transaction

observability plane
  -> append-only SHA-256 trajectory (replay/integrity)
  -> W3C/OpenTelemetry spans (cross-process operations)
  -> enterprise.agent-run/1.0 (EvalOps exchange)
```

## Trust boundaries

- Tenant, user, roles, ACL scope, budget, and expiry come from trusted server
  context or a closed harness fixture registry. The model cannot supply them.
- `ToolGateway` remains the single read-tool enforcement point. LangGraph and MCP
  do not call the navigator directly.
- The durable workflow supports one side-effect tool:
  `create_access_request_draft`. It creates a `DRAFT`; it has no API or SQL path
  that changes ACLs.
- `mutate_acl`, `unrestricted_fetch`, `raw_database_query`, and unregistered tools
  fail closed.
- Bounded controller remains the default. Durable LangGraph is an optional
  runtime for approval workflows, not a quality or latency improvement.

## Storage ownership

| Store | Purpose | Integrity/consistency |
|---|---|---|
| LangGraph SQLite/PostgreSQL checkpointer | Thread-scoped graph snapshots | Framework persistence; requires retention and database operations |
| Approval SQLite store | Token hash and immutable binding inputs | Raw token excluded; completed result persisted for idempotent resume |
| Side-effect SQLite store | Command/result and draft | `BEGIN IMMEDIATE`; command and draft commit atomically |
| Trajectory SQLite store | Semantic event history | Append-only triggers plus SHA-256 hash chain |
| OTel exporter | Operational spans | Best effort; exporter failure is fail-open for business execution |

## Default and optional paths

The default application behavior is unchanged: `BoundedControllerAdapter`.
`LangGraphOrchestratorAdapter` remains the non-durable parity/HITL adapter.
`DurableLangGraphOrchestrator` adds a separate persisted approval workflow and
still satisfies the `AgentOrchestrator.run()` shape for normal answer runs.

## External harness contract

`scripts/run_agent_harness.py` accepts `enterprise.agent-harness-request/1.0`
JSON and returns `enterprise.agent-harness-result/1.0`. Public request/result
schemas live under `docs/production_runtime/schemas/` and are tested for exact
equality with the Pydantic models. `attempt_id` prevents repeated execution of
the same case from reusing an immutable trajectory session.
