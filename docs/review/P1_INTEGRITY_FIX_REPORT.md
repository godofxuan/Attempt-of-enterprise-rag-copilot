# P1 Durable Approval Integrity Fix Report

Status: implementation and local evidence in progress. Remote CI coordinates
are bound only after the implementation commit is pushed.

## Review coordinates

| Field | Value |
|---|---|
| Repository | `godofxuan/Attempt-of-enterprise-rag-copilot` |
| Branch | `codex/durable-runtime-integrity-fix-v1` |
| Required implementation ancestor | `e848d8e6090267b28d351758fe8d3cb557dcd586` |
| Start HEAD | `2e1c93cc8713bb2804a665221af38457b79afa44` |
| Default Agent runtime | bounded controller, unchanged |
| Durable scope | `create_access_request_draft` approval only |

## Defects and fixes

### 1. Concurrent resume ownership

Before this overlay, approval completion relied on a conditional update but did
not check its row count, and no database ownership state prevented two callers
from progressing after both observed `PENDING`.

`SQLiteDurableWorkflowStore.claim_resume()` now starts `BEGIN IMMEDIATE`, reads
the bound token row, and conditionally changes `PENDING`,
`FAILED_RECOVERABLE`, or an expired `RESUMING` row to `RESUMING`. The update
must affect exactly one row. Ownership stores only a random token's SHA-256,
lease expiry, attempt, version, reviewer hash, and resume time. Active losers
receive `ALREADY_RESUMING`; terminal repeats receive stable outcomes.

Finalization checks approval ID, `RESUMING`, owner-token hash, version, and an
unexpired lease. A recovered caller increments the fence version, so a stale
process cannot finish later.

The unified store intentionally reuses and migrates the prior
`approvals.sqlite3` file. This preserves v1 pending approval rows during an
in-place code upgrade; choosing a new filename would silently orphan them.

### 2. Atomic local completion boundary

The previous approval, side-effect, and trajectory facts lived in separate
SQLite files. The new durable store puts these facts in one local transaction:

1. stable idempotent side-effect command and access-request DRAFT;
2. one immutable completion outbox envelope per approval;
3. approval terminal status and persisted result.

Trajectory remains a separate tamper-evident store. It is an outbox projection,
not part of the transaction. Each projected completion event has a stable
idempotency key, and the trajectory store enforces uniqueness and semantic
equality. A delivery receipt is separate from the immutable envelope.

### 3. Failure semantics

`PENDING`, `RESUMING`, `COMPLETED`, `REJECTED`, `EXPIRED`, and
`FAILED_RECOVERABLE` are explicit. A graph/checkpoint failure before local
effect commit becomes `FAILED_RECOVERABLE`. Crashes that intentionally model a
dead process leave `RESUMING`; lease expiry allows recovery. Every pre-commit
fault rolls back effect, completion, and final approval. A
post-commit/before-response fault leaves all three committed and retry returns
the same result.

### 4. Telemetry privacy

Telemetry now uses an operation-specific typed allowlist rather than key-name
denylisting as its primary privacy boundary. Unknown and structured attributes
are discarded. Identity-like strings are hashed; accepted statuses/tool names
are finite enums. Neutral keys, nested/list secrets, exception messages, and
metadata on the wrong operation surface are tested as absent. Content capture
remains OFF.

### 5. Hook isolation

`pre_tool_use` remains fail closed and `post_tool_use` still blocks unsafe
output. Exceptions in `tool_error` and `run_stop` are caught and recorded in an
append-only failure table using hashed IDs, hook type, and exception type only.
They cannot replace the original business exception or undo a completed call.

### 6. Naming and scope

The public type is `DurableAccessRequestWorkflow`. The former
`DurableLangGraphOrchestrator` is a deprecated compatibility alias with no
generic `run()` method. This workflow does not make ordinary answers,
partial-answer HITL, arbitrary tools, or the whole Agent runtime crash durable.

## Failure injection matrix

| Injection point | Immediate durable state | Recovery expectation |
|---|---|---|
| before effect | `RESUMING`, zero effect/completion | lease recovery commits one set |
| after effect, before completion | transaction rollback, zero effect/completion | lease recovery commits one set |
| after completion, before approval | transaction rollback, zero effect/completion | lease recovery commits one set |
| after approval update, before commit | transaction rollback, zero effect/completion | lease recovery commits one set |
| after commit, before response | `COMPLETED`, one effect/completion | repeat returns same result and projects events once |

## Local validation recorded so far

| Command | Result |
|---|---|
| `python -m pytest tests/agent_runtime/test_durable_orchestrator.py tests/agent_runtime/test_tool_policy.py -q` | `32 passed, 2 skipped`; PostgreSQL tests skipped because local DSN is absent |
| `python -m pytest tests/agent_runtime -q` | `103 passed, 2 skipped`; same PostgreSQL reason |
| `python -m ruff check ...` and `python -m ruff format --check ...` | passed on integrity-fix surfaces |
| `python -m mypy --follow-imports=skip ...` | passed on seven changed runtime modules; this is not a whole-repository mypy claim |
| `python -u -X faulthandler -m pytest -q -p no:cacheprovider` | final rerun: `3344 passed, 31 skipped`, 3 existing SWIG warnings |
| first public audit | expected development failure: credential-like fixture assignment plus not-yet-created commit-bound manifest; both fixed before closeout |
| final pre-commit public audit | `1695 candidates / 0 findings` |

Clean-worktree verification, exact implementation SHA, manifest hashes, push
result, and new-branch CI are intentionally not claimed until they run.

## Claim boundary

Safe: database-fenced, restart-recoverable approval and idempotent completion
for one access-request DRAFT workflow.

Unsafe: general durable Agent runtime, arbitrary side-effect durability,
distributed exactly-once, production HITL, multi-host HA, automatic failover,
or any retrieval/answer-quality improvement.
