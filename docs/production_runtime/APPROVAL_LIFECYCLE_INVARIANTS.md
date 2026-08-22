# Access-Request Draft Approval Lifecycle Invariants

Status: `IMPLEMENTATION_COMPLETE`, `EXACT_SHA_CI_REQUIRED`, `NOT_MERGED`,
`NOT_RELEASED`, `PORTFOLIO_READY`, `PRODUCTION_NOT_VERIFIED`.

`DURABILITY_SCOPE = ACCESS_REQUEST_DRAFT_ONLY`. These invariants apply only to
`DurableAccessRequestWorkflow` and its local access-request DRAFT side effect.
They do not describe the default bounded Agent runtime or arbitrary tools.

## State composition

Start and Resume have separate ownership domains in one approval record:

```text
Start:  STARTING + NOT_STARTED/IN_PROGRESS
          -> STARTING + READY
          -> READY + READY
          -> FAILED_RECOVERABLE -> STARTING (new owner/version)

Resume: PENDING -> RESUMING -> COMPLETED | REJECTED
          |           |
          +-> EXPIRED +-> FAILED_RECOVERABLE -> RESUMING (new owner/version)
```

`READY + READY + PENDING` means a durable interrupt exists and Resume is
allowed to compete for ownership. Client acknowledgement is recorded
separately; missing acknowledgement never creates a second approval.

## Enforced invariants

1. **I1 One Start key, one logical approval.** A partial unique SQLite index on
   the hash of `tenant + user + run + session + start_idempotency_key` prevents
   duplicate approval rows across independent connections and processes.
2. **I2 One generation, one thread.** `thread_id` binds the generation scope,
   `approval_generation`, and random `approval_id`. A new key in the same
   session receives the next generation and a different checkpoint thread.
3. **I3 At most one valid Start owner.** Start acquisition uses
   `BEGIN IMMEDIATE`, an owner-token hash, lease, version, and checked
   `rowcount`. An expired owner is fenced by the next version.
4. **I4 At most one valid Resume owner.** Resume uses a separate owner-token
   hash, lease, attempt, and version CAS. An active owner is not stolen.
5. **I5 At most one draft side effect.** The stable side-effect command key and
   database uniqueness constraints prevent duplicate draft creation.
6. **I6 At most one completion fact.** One immutable completion outbox row is
   keyed by approval; conflicting re-insertion fails closed.
7. **I7 Terminal retry is stable.** Repeated Start with the same key or Resume
   after completion reads the persisted terminal result; it does not create a
   new generation or side effect.
8. **I8 Approval never changes ACL.** The implemented effect creates a DRAFT.
   It does not grant membership, mutate an ACL, or write IAM state.
9. **I9 Authority is revalidated at Resume.** Active tenant, exact reviewer,
   reviewer role, expiry, tool-argument hash, authentication/deadline, current
   ACL, and current `DENY > ASK > ALLOW` policy are checked again.
10. **I10 Handle is not authentication.** `approval_handle_id` is a persisted,
    recoverable locator. Possession alone cannot authorize Resume; full handles
    are excluded from typed telemetry and error messages.

## Crash recovery

The deterministic matrix covers failures before approval insert; after insert;
during checkpoint creation; after checkpoint but before READY; after READY but
before trajectory; after trajectory but before response; and during response.
Retry uses the same Start key. An expired Start owner is moved to
`FAILED_RECOVERABLE` by `recover_stale_starts()`, then the normal Start entry
point re-runs current tenant, ACL, deadline, authentication, and policy checks
before it may acquire a new owner.

Start trajectory delivery uses approval-scoped idempotency keys. Generation 1
retains the caller's trajectory session ID for compatibility; later generations
use an approval-scoped trajectory session so a completed older generation
cannot make the new append-only stream immutable.

## Atomicity boundary

The draft command, draft row, completion outbox, and terminal approval update
share one SQLite transaction during approved Resume. LangGraph checkpoints and
trajectory projection are separate durable stores reconciled by idempotent
replay. Therefore the supported phrase is **retry-safe and database-fenced**,
not exactly-once, distributed transaction, multi-instance HA, or production
failover.
