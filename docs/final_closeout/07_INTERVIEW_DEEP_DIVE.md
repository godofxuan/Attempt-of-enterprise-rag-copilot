# Interview Deep Dive

## The 90-second project story

I started with an enterprise RAG path and treated the hard problem as authority,
not prompt fluency. Documents become versioned indexes; authenticated questions
can retrieve only visible evidence; server code controls tools, budgets, Guard,
evidence, citations, and safe stopping. I then extracted orchestration behind a
runtime interface, kept the bounded controller as default, and implemented a
real LangGraph alternative without duplicating the security path. Finally I
added MCP tool integration, hash-chained trajectories, replay, HITL, and an
EvalOps artifact. External retrieval and large-corpus evidence remain separate
from the five-case runtime diagnostic.

## Design questions worth inviting

### Why keep the bounded controller?

Both orchestrators used identical tools, ACL, budget, fixtures, and response
builder. After fixing cold-start order bias with one discarded warm-up per arm,
both passed 5/5 and had behavioral parity; LangGraph showed no quality gain and
higher diagnostic p95. The bounded loop therefore stays default, while
LangGraph remains useful for explicit state and HITL.

### Where is authority enforced?

ToolContext is server-issued. ToolGateway compares identity fingerprints,
session/request/sequence, allow-list, deadline, and stateful budgets. ACL scope
may narrow authenticated groups but cannot expand them. Retrieval filters ACL
before Guard admission; citation verification controls publication.

### Why MCP cannot access the database directly

MCP standardizes tool transport and schemas, not authorization. Direct database
access would create a second authority path. The adapter therefore resolves an
opaque context handle and dispatches through the same ToolGateway and guarded
registry as direct calls.

### What does the hash chain prove?

It detects mutation, reordering, deletion, or inconsistent linkage in the
supplied event sequence and binds the exported artifact to the final event
hash. Without signatures, trusted timestamps, WORM media, and hardened key/
storage operations, it does not prove production immutability.

### How does HITL retry safely?

A token entry moves PENDING -> RESUMING before graph execution. Concurrent
resume sees RESUMING and fails. An invocation exception restores PENDING. A
successful result is cached as COMPLETED: the same decision returns the cached
result; a different decision fails. Tenant and reviewer role are checked on
every call. Restart durability is intentionally out of scope.

## Evidence stories

- WixQA: fixed 200 ExpertWritten retrieval questions; Dense beat BM25 on
  Recall@5 and nDCG@5. Equal RRF lost to Dense and was not promoted.
- EnterpriseRAG-Bench: FTS5 avoided requiring the full lexical corpus in
  application memory and produced a recoverable 511,962-row one-host index.
- Clean replay: fresh roots rebuilt 11,975 embeddings and matched 63 frozen
  quality observations exactly.
- Agent A/B: a mechanism test answering “can orchestration change without
  changing authority or behavior?”, not “is Agent accuracy 100%?”

## Negative results and trade-offs

The project records rejected approaches: equal-weight RRF added latency and
reduced Recall@5 versus Dense; the bounded multi-document candidate produced no
complete-case fixes and hurt citation precision; LangGraph added overhead
without measured quality benefit. This is why the final architecture is smaller
than the list of implemented experiments.

## Production follow-up, only if requirements exist

Real deployment would need durable encrypted trajectory storage and retention,
persistent HITL/checkpoints, network MCP authentication/isolation, operational
telemetry/SLOs, load/failure testing, and possibly distributed state. Those are
requirements-driven follow-ups, not missing resume features.

