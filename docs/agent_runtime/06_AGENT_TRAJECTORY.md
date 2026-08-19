# Durable Agent Trajectory

## Storage model

vNext uses `SQLiteTrajectoryStore`, an append-only semantic event ledger. Each
session has a strictly increasing sequence and SHA-256 hash chain. SQLite
transactions serialize append operations; database triggers reject UPDATE and
DELETE. `PRAGMA synchronous=FULL` is used for local durability.

This is stronger than an in-memory trace, but it is not an external immutable
WORM store. A database owner can still replace the file or drop triggers, so the
project claims tamper-evident local storage, not tamper-proof storage.

## Recorded semantics

Runs record session start, user message, step/tool activity, retrieval summary,
admitted or rejected evidence identifiers, budget updates, accepted claims,
citation checks, terminal output, and session completion. Model events are only
recorded when an actual model integration supplies them; they are never
fabricated to make the trace look more agentic.

Tool results store document/chunk/version identifiers and security counters,
not raw matched text, parent context, or opened document content. The final
answer is stored only after the existing response/citation gate has produced it.

## Redaction

The recorder recursively redacts authorization headers, API keys, passwords,
secrets, access/refresh tokens, session handles, JWT-like values, OpenAI-style
key values, and raw retrieval content fields. Payloads are capped at 64 KiB and
session/trace identifiers use a path-safe allowlist.

Redaction is defense in depth, not a data-classification product. Deployments
must place the SQLite file in private application storage with retention and
access controls appropriate to their organization.

## Trajectory versus observability

Trajectory captures domain meaning: which action occurred, what evidence IDs
were admitted, why execution stopped, and what was published. Existing request
tracing captures operational latency and status. They correlate through
`session_id`, `trace_id`, and `step_id`; neither grants authorization.

