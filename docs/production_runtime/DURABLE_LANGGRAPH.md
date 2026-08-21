# Durable LangGraph Interrupt and Resume

Implementation: `app/agent_runtime/durable_orchestrator.py`.

## Why the old adapter was insufficient

`LangGraphOrchestratorAdapter` used `InMemorySaver` for partial-evidence HITL and
kept review tokens in a process dictionary. It proved interrupt mechanics but a
restart lost both checkpoint and pending review state.

## Durable flow

1. Server constructs `DurableToolRunRequest`; the model cannot choose identity.
2. Policy must return `ASK`; `DENY` never creates an approval.
3. A deterministic, hashed `thread_id` binds tenant, requester, run, and session
   and remains below PostgreSQL's length limit.
4. Approval store persists token SHA-256, expected reviewer, request binding,
   tool argument hash, policy version, and expiry. The raw token is returned once
   but not persisted.
5. LangGraph checkpoints state, enters a JSON-only `interrupt`, and returns
   `needs_approval` before any side effect.
6. Resume revalidates token, tenant, exact reviewer, reviewer role, argument hash,
   expiry, authentication/deadline, ACL, and current policy.
7. `reject` terminates without a side effect. `approve` advances to a separate
   side-effect node.
8. Completion is persisted in the approval store; repeated authorized resume
   returns the same result.

## Crash behavior

LangGraph may checkpoint the approval node and retry the side-effect node. After
an injected execute-node failure, `get_state().next` identifies that the graph is
already past the interrupt. Recovery clears only the injected fault field and
continues the pending node; it does not issue a second approval decision.

Tests destroy the first orchestrator and SQLite connection, construct a new one
on the same files, resume, and verify one committed draft. They also cover a
crash before commit and a crash after commit/before response.

## Checkpointers

- Local development: official `SqliteSaver` with a file-backed connection.
- PostgreSQL: official `PostgresSaver`, `setup()`, and a real service-backed CI
  integration test selected by `TEST_POSTGRES_DSN`.
- In-memory saver remains only in the older non-durable adapter's mechanism
  tests.

This is not exactly-once execution. It is replay-tolerant execution for the one
implemented transactional draft operation.
