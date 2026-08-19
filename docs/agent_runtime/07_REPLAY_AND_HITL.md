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

Stage G adds a bounded review flow only for a real reachable partial-evidence
terminal. Its exact persistence and restart limitation are documented after the
implementation; it must not be confused with general durable execution.

