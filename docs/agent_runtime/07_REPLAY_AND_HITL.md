# Replay and Human Review

## Deterministic replay

`replay_trajectory` first verifies event order, previous-hash links, and every
event hash. It then reconstructs the user message, tool requests and outcomes,
admitted evidence identifiers, final output, and terminal reason without
calling a model, retriever, tool, or network service.

```powershell
python -m scripts.replay_agent_trajectory `
  --store .private/agent_runtime/trajectory.sqlite3 `
  --session-id SESSION_ID
```

This is historical reconstruction, not re-execution. It is deterministic with
respect to the persisted events and fails closed when the hash chain is invalid
or no terminal output exists.

## Resume boundary

The current implementation does **not** claim crash-safe Agent resume. Raw tool
content is intentionally absent from trajectory storage, so reconstructing an
executable controller state after process loss would require a separately
secured checkpoint design and stale-index/version checks. Re-running tools and
calling it resume would produce a different execution and is rejected as a
misleading implementation.

## Human review

The LangGraph adapter can enable `hitl_on_partial`. When the bounded controller
reaches a real `partial_evidence` terminal, the graph calls LangGraph
`interrupt()` before publication. The caller receives no answer, only a review
request containing an evidence summary and one-time opaque review token.

A reviewer may choose `accept_partial` or `reject`. Resume requires the same
tenant and the `knowledge_reviewer` role. The token is stored by SHA-256 digest,
is never written to trajectory, and is consumed once. Both request and decision
produce `human_review.*` events. Rejecting returns a source-free terminal.

The graph checkpoint and pending-token map are intentionally in memory. A
process restart invalidates the review, so this is a real in-process
pause/resume workflow but not crash-durable HITL. Persisting executable state
would require encrypted private checkpoints, expiry, index-version pinning, and
an operational cleanup policy; those are not implied by trajectory replay.
