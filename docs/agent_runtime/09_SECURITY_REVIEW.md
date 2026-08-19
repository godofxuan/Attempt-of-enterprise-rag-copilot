# Agent Runtime vNext Security Review

## 1. Review scope

This review covers the vNext path added on branch `codex/agent-runtime-vnext`:

```text
orchestrator -> Tool Gateway -> existing V2 tools -> ACL/retrieval/Guard
             -> trajectory -> replay/export
```

It does not certify the whole application as universally safe. The review asks a
narrower question: did the new orchestration, MCP, trajectory, replay, and HITL
paths preserve the host-owned controls already present in the baseline?

## 2. Authority model

| Decision | Authority | Why |
|---|---|---|
| tenant/user/groups | authenticated host context | model or MCP arguments must not invent identity |
| allowed tools and budget | `ToolGateway` session | prompt instructions are not an authorization boundary |
| document visibility | existing V2 retrieval/ACL path | denied content must never become model evidence |
| retrieved-content admission | existing deterministic Guard | retrieved text is untrusted data |
| citation publication | existing grounding/citation gate | a generated claim cannot self-certify |
| graph transitions | bounded Python routing | prevents unrestricted loops and tools |
| human resume | reviewer role + tenant + one-time token | pause/resume is an authorization event |

MCP is only a protocol adapter. LangGraph is only an orchestrator. Neither owns
identity, ACL, admission, or final publication authority.

## 3. Threat-to-test map

| Threat | Control | Regression evidence |
|---|---|---|
| unauthorized tool | allow-list in active `ToolGateway` session | `tests/agent_runtime/test_tool_contract.py` |
| forged identity / cross tenant | exact context fingerprint and tenant match | `test_forged_identity_and_cross_tenant_fail_before_backend` |
| stale or revoked context | expiry and active-session lookup | `test_expired_and_closed_sessions_are_stale` |
| malformed request | strict Pydantic contracts, literal tool names | tool contract and MCP malformed tests |
| MCP identity injection | opaque server-issued handle; identity absent from tool arguments | `tests/agent_runtime/test_mcp_adapter.py` |
| denied search/open | existing V2 permission error remains structured | MCP authorized/unauthorized tests |
| exhausted budget | stateful server-side `BudgetState` | gateway and MCP budget tests |
| timeout | session deadline plus backend elapsed-time rejection | gateway and MCP timeout tests |
| retrieved prompt injection | existing search/find/open admission Guard | A/B `retrieved-injection` case and existing Guard suites |
| oversized context | existing context budget rejects/discards oversized result | V2 tool/context-cap tests |
| cyclic/runaway graph | max steps, call budgets, LangGraph recursion limit | `test_graph_stops_at_budget_without_runaway_calls` |
| trajectory mutation | SQLite append-only triggers plus SHA-256 event chain | trajectory and replay tamper tests |
| trajectory secret leakage | recursive redaction and omission of raw matched/context text | trajectory and artifact leakage tests |
| forged HITL resume | hashed one-time token, role and tenant checks | `tests/agent_runtime/test_human_review.py` |
| artifact mutation | event-chain verification plus artifact-level SHA-256 | `tests/agent_runtime/test_evalops_artifact.py` |

## 4. Important implementation details

### 4.1 Server-owned context

`MCPContextBroker` returns an opaque random handle and stores only its digest.
The MCP schema accepts business arguments such as query or document target, but
does not accept tenant, user, group, deadline, or budget. The server resolves the
handle to a previously registered `ToolContext` and invokes `ToolGateway`.

This prevents a client from changing `tenant_id` in a JSON payload. It does not
replace authentication for a future network transport; a production transport
must bind the handle to a real authenticated connection.

### 4.2 Stateful budget

The gateway stores the authoritative budget state. A caller cannot reset its
search count by constructing a fresh request object. Calls consume budget before
the next call is evaluated, and a closed or expired session returns a structured
error before reaching the backend.

### 4.3 Trajectory privacy boundary

Trajectory is a semantic execution record, not a dump of prompts and documents.
It stores identifiers, decisions, admitted evidence metadata, safe outputs,
latency, and usage. It deliberately excludes raw `matched_text` and
`context_text`; common secret-shaped keys are recursively redacted and payloads
are size bounded.

### 4.4 HITL boundary

Only `partial_evidence` triggers the current review path. A reviewer must be in
the same tenant and have the `knowledge_reviewer` role. Tokens are random,
stored as hashes, and consumed once. Accept publishes the already bounded partial
response; reject publishes a source-free safe terminal response.

## 5. Residual risk and non-claims

1. SQLite triggers and hashes are tamper-evident, not WORM storage. A machine
   owner can replace the complete database or code. External signed storage is
   required for stronger non-repudiation.
2. HITL pending state uses LangGraph `InMemorySaver`; process restart loses the
   pending review. This is tested pause/resume, not durable execution.
3. MCP is tested through the official SDK's in-process dispatch. Network
   transport, OAuth, connection binding, rate limiting, and deployment hardening
   are not implemented or claimed.
4. Timeout enforcement is cooperative around the existing backend contract; it
   is not process isolation for a permanently stuck native call.
5. The five-case runtime A/B is a deterministic mechanism test. It cannot prove
   broad safety, answer quality, or production latency.
6. No multi-agent runtime or unrestricted code/file/SQL tool was added.

## 6. Review decision

The new paths preserve the intended deterministic security ownership and have
direct negative-path tests. They are suitable as a portfolio-grade, local
reference implementation. They are not a production security certification.

