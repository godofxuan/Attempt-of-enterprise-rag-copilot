# Final Resume-Readiness Evidence Entry

## Coordinates

```text
repository          godofxuan/Attempt-of-enterprise-rag-copilot
branch              codex/final-resume-readiness-closeout-v1
base head           445cd642f46e90ff2f236217bb4bc671bcf6b6f9
implementation head 7a74fbd4bf368a9dedffe28a814a65c87c1219af
implementation CI   32554467461 / SUCCESS
status              IMPLEMENTATION_COMPLETE / EXACT_SHA_CI_REQUIRED
release             NOT_MERGED / NOT_RELEASED
portfolio           PORTFOLIO_READY
production          PRODUCTION_NOT_VERIFIED
durability scope    ACCESS_REQUEST_DRAFT_ONLY
```

Implementation CI:
<https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32554467461>

This entry is the second stage of a non-self-referential evidence process. It
binds implementation commit `7a74fbd...` and its completed CI. The evidence
commit containing this file must receive its own exact-HEAD CI before final
closeout; this file intentionally does not predict that commit SHA.

## What changed

The access-request DRAFT approval path now accepts an explicit
`start_idempotency_key`. SQLite hashes the key together with tenant, requester,
run, and session and enforces one row with a partial unique index. A different
key in the same session receives the next `approval_generation`; the graph
`thread_id` binds generation scope, generation number, and approval ID.

Start has its own database owner-token hash, lease, version, attempt, and CAS,
separate from Resume ownership. Checkpoint state is explicit as `NOT_STARTED`,
`IN_PROGRESS`, or `READY`; Start state is `STARTING`, `READY`, or
`FAILED_RECOVERABLE`. An expired Start owner can be reaped, but recovery still
enters through the normal Start method and repeats tenant, ACL, deadline,
authentication, and policy checks.

The client receives a persisted `approval_handle_id`. It is deliberately a
locator, not a bearer authorization token. Lost Start responses can be retried
with the same key to recover the same Approval ID, generation, checkpoint, and
Handle. Resume still revalidates active tenant, exact reviewer, reviewer role,
current ACL/policy, expiry, authentication/deadline, and tool arguments hash.
Handle acknowledgement and reissue are explicit, and full Handle values are
not admitted to typed telemetry or errors.

Later approval generations use approval-scoped trajectory sessions. This keeps
the append-only `session.completed` event from an older generation from blocking
the next generation. Start and completion trajectory events use stable,
approval-scoped idempotency keys.

## Start crash matrix

| Failure | Expected recovery | Actual deterministic evidence |
|---|---|---|
| F1 before Approval INSERT | Retry creates generation 1 once | passed |
| F2 after INSERT, before Checkpoint | Lease/reaper, same row and Handle | passed |
| F3 during Checkpoint | Inspect/rebuild one generation-bound checkpoint | passed |
| F4 after Checkpoint, before READY | Reuse existing interrupt, then mark READY | passed |
| F5 after READY, before Start trajectory | Stable result plus idempotent projection | passed |
| F6 after trajectory, before response | Same persisted result and no duplicate events | passed |
| F7 response interrupted | Same persisted result and Handle | passed |
| F8 response received, ACK absent | Same-key retry, then idempotent ACK | passed |

The test asserts one approval row, one valid checkpoint identity, one
`session.started`, and one `human_review.requested` after each recovery. It does
not claim a cross-store distributed transaction.

## Concurrency and final facts

- Two threads and two Windows `spawn` processes use independent workflow/store
  objects against one SQLite database. Same-key Start produces one Approval ID,
  one Handle, one generation, and `start_attempt == 1`.
- A stale Start owner cannot update checkpoint state after a recovered owner
  increments `start_version`.
- Existing two-caller Resume CAS tests still produce one owner and one finalizer.
- Start retry racing an authorized Resume converges to one approval, one draft,
  one effect command, and one completion envelope.
- Same-key Start after completion returns the persisted completed result. A new
  key creates generation 2 with an independent thread and trajectory session.

## Verification record

| Command | Exit | Result | Environment |
|---|---:|---|---|
| `python -m pip check` | 0 | no broken requirements | local Windows / Python 3.11 venv |
| `python -m compileall -q app scripts streamlit_app tests` | 0 | passed | local Windows |
| scoped `python -m ruff check ...` | 0 | passed | local Windows |
| scoped `python -m ruff format --check ...` | 0 | 14 files formatted | local Windows |
| scoped `python -m mypy --follow-imports=skip ...` | 0 | 8 source files passed | local Windows |
| `python -m pytest tests/agent_runtime -q` | 0 | 123 passed, 2 skipped | local; skips require `TEST_POSTGRES_DSN` |
| `python -m pytest tests/agent_runtime/test_start_lifecycle.py -q` | 0 | 21 passed | local; includes two-process Start |
| `python -u -X faulthandler -m pytest -q -p no:cacheprovider` | 0 | 3368 passed, 31 skipped | local Windows |
| `python -m scripts.audit_public_repo` | 0 | 1699 candidates, 0 findings | local public tree |
| GitHub Actions run `32554467461` | 0 | four job groups succeeded | Ubuntu, Windows, PostgreSQL 17.6, read-only Linux container |

The three local warnings are existing SWIG `__module__` deprecation warnings.
The two local Agent Runtime skips are real PostgreSQL tests; both executed and
passed in the dedicated PostgreSQL 17.6 CI job.

## Safe resume claims

1. Implemented idempotent Start/Resume recovery for one access-request DRAFT
   approval workflow, including response-loss recovery and approval generations.
2. Used database CAS, leases, owner-token hashes, versions, and checked row
   counts to fence concurrent Start and Resume ownership.
3. Kept one local draft command, completion outbox fact, and approval terminal
   update in a SQLite transaction, with idempotent trajectory projection.
4. Preserved deterministic `DENY > ASK > ALLOW` and revalidated identity, tenant,
   reviewer role, ACL/policy, expiry, and argument binding at Resume.
5. Used operation-typed telemetry allowlists with content capture off and no
   full approval Handle in spans.

## Forbidden claims

Do not claim that the entire Agent runtime is durable, that arbitrary side
effects are exactly-once, that the project is production HITL, that it supports
multi-instance HA or automatic failover, or that LangGraph improved answer
quality. This implementation is a local, SQLite-backed, retry-safe candidate
for one access-request DRAFT workflow.

## Remaining non-P0/P1 boundaries

Production IAM integration, approval inbox/notifications, retention and
revocation operations, external outbox delivery, multi-host load, database
failover, network partition, clock-skew qualification, and production SLOs were
not implemented or verified. They are deployment/product boundaries, not hidden
claims in this portfolio closeout.
