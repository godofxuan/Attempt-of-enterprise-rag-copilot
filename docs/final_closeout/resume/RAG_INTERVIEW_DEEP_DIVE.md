# RAG / Agent Runtime Interview Deep Dive

## Agent Runtime

The orchestrator abstraction prevents framework choice from becoming the
security boundary. The bounded controller is the default; LangGraph is a real
StateGraph alternative. The five-case paired protocol froze retrieval, tools,
ACL, budget, fixtures, response builder, and cases. An earlier ordering bias was
removed by a discarded warm-up per arm. Both achieved 5/5 and 100% behavioral
parity with zero permission violations; LangGraph diagnostic p95 was 6.838 ms
versus 1.283 ms for bounded. These values are interview-only mechanism data.

## ToolGateway

Every tool call is bound to a server-created context: session/request/trace,
identity fingerprint, tenant, an ACL scope that may only narrow identity groups,
allow-listed tools, stateful budgets, monotonic sequence, issued/expiry time,
and post-call deadline. Forged identities, stale contexts, duplicate sequence,
budget exhaustion, and backend permission failures remain structured failures.

## MCP

MCP provides a standard tool schema and dispatch adapter. It must not own
authorization or query storage directly, because that would create a second
permission path. Current dispatch is in-process via the official SDK; there is
no production network server or OAuth claim.

## Trajectory and replay

Events are append-only at the application boundary, strictly sequenced, and
linked by SHA-256 over canonical JSON. Payloads are semantic and minimized, but
open payload fields still require export-time privacy policy. The verifier
detects mutation and ordering/linkage errors. This is tamper-evident, not WORM.
Replay reconstructs recorded behavior without network calls; it does not make
execution durable or repeat external side effects.

## HITL

Partial evidence can interrupt before terminal publication. Resume verifies the
opaque token, tenant, and `knowledge_reviewer` role. The in-process state
machine prevents duplicate concurrent graph execution, returns to PENDING after
invoke failure, caches a completed same-decision result, and rejects a changed
decision. `InMemorySaver` means restart loses pending state.

## Retrieval

BM25 gives a lexical baseline; BGE-M3 Dense is the promoted WixQA arm; equal
RRF was rejected because Recall@5 was 59.25% versus Dense 66.42% and p95 was
304.64 ms versus 157.41 ms on the same 200-case protocol. “Dense default” is an
evidence decision, not a universal rule.

## Large corpus

EnterpriseRAG-Bench contains 511,962 public records across nine source types.
SQLite FTS5 provided an on-disk, resumable lexical path with manifest/hash,
immutable build, activation, and recovery semantics. The recorded one-host
build took 231.35 seconds, produced 1.37 GiB, and peaked near 1.83 GiB RSS.

## Security evidence

The retrieved-content Guard has deterministic tests and a pinned 12-attack
garak subset where observed attack success changed 4/12 to 0/12 and context
exposure 12/12 to 0/12. This belongs in security-targeted interviews, not the
general resume, because it is neither full garak nor general Agent safety.

## Negative results to volunteer

- Equal RRF was not promoted.
- LangGraph was not made default.
- A bounded multi-document candidate had zero complete-case fixes and reduced
  citation precision.
- Runtime A/B is a mechanism suite, not an external Agent benchmark.
- Durable storage, network MCP, persistent HITL, distributed state, and
  production SLOs remain explicit gaps.

