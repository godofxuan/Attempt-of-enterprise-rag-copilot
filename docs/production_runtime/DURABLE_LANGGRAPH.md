# Durable Access-Request Interrupt and Resume

Implementation: `app/agent_runtime/durable_orchestrator.py`.

## Why the old adapter was insufficient

`LangGraphOrchestratorAdapter` used `InMemorySaver` for partial-evidence HITL and
kept review tokens in a process dictionary. It proved interrupt mechanics but a
restart lost both checkpoint and pending review state.

## Durable flow

1. Server constructs `DurableToolRunRequest` with a caller-generated
   `start_idempotency_key`; the model cannot choose identity.
2. Policy must return `ASK`; `DENY` never creates an approval.
3. SQLite atomically gets or creates one Approval Generation for the hash of
   tenant, requester, run, session, and Start key, then acquires a fenced Start
   owner with a lease and version.
4. `thread_id` binds the generation scope, generation number, and approval ID.
   A new key in the same session creates a new generation and checkpoint thread.
5. LangGraph checkpoints state, enters a JSON-only `interrupt`, and the store
   moves checkpoint state from `NOT_STARTED` through `IN_PROGRESS` to `READY`.
6. The persisted `approval_handle_id` is returned in a stable Start result. It
   is a locator, not a bearer credential; a lost response is recovered by
   retrying with the same Start key.
7. Resume revalidates handle, tenant, exact reviewer, reviewer role, argument hash,
   expiry, authentication/deadline, ACL, and current policy.
8. The approval store atomically changes `PENDING` or recoverable state to
   `RESUMING` with a random owner-token hash, lease expiry, attempt, and version.
   A second live caller gets `ALREADY_RESUMING`; an expired owner can be fenced
   out by a new version.
9. `reject` terminates without a side effect. `approve` prepares the operation
   in LangGraph, but the database store executes the local draft write.
10. One SQLite transaction commits the effect command/draft, immutable
   completion outbox envelope, and terminal approval result. Every terminal
   update checks owner token, version, state, lease, and `rowcount == 1`.
11. Completion trajectory events are projected from the outbox with stable
    idempotency keys. Repeated authorized resume returns the persisted result.

## Explicit state machine

```text
STARTING / NOT_STARTED -> STARTING / IN_PROGRESS -> READY / READY / PENDING
          |                         |
          +-> FAILED_RECOVERABLE <-+

PENDING ---------------------------> RESUMING
   |                                  |  owner token hash
   +-> EXPIRED                        |  lease expiry
                                      |  attempt/version
FAILED_RECOVERABLE -----------------> |
expired RESUMING -------------------> |  (RECOVERED, new fence)
                                      +-> COMPLETED
                                      +-> REJECTED
                                      +-> FAILED_RECOVERABLE
```

An expired Start lease is reaped to `FAILED_RECOVERABLE`; a same-key retry must
pass current tenant, ACL and policy checks before acquiring a new Start version.
Client acknowledgement is separate from readiness, so response loss does not
create a second approval or checkpoint.

`COMPLETED`, `REJECTED`, and `EXPIRED` are stable terminal outcomes. An active
`RESUMING` owner is never stolen. A stale owner cannot finalize after another
caller increments the version, even if the stale process later continues.

## Crash behavior

Seven Start failure injection points surround approval insertion, checkpoint
creation, READY, trajectory projection, and response delivery. Five Resume
failure injection points surround effect creation, completion insertion,
approval update, transaction commit, and response return. Every pre-commit
failure rolls back all three facts. A post-commit response loss leaves all three
facts committed; retry returns the same result and idempotently projects one
set of completion trajectory events. A graph/checkpoint failure before the
effect is marked `FAILED_RECOVERABLE` so another attempt can retry immediately.

## Checkpointers

- Local development: official `SqliteSaver` with a file-backed connection.
- PostgreSQL: official `PostgresSaver`, `setup()`, and a real service-backed CI
  integration test selected by `TEST_POSTGRES_DSN`.
- In-memory saver remains only in the older non-durable adapter's mechanism
  tests.

This is replay-tolerant, database-fenced execution for one local transactional
draft operation. The checkpoint and trajectory databases are outside the final
transaction, so this is not a distributed atomicity or exactly-once claim.
