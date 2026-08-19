# Final Architecture

```text
enterprise sources (policy / Wiki / ticket / email / meeting notes)
  -> validated parsing and versioned chunks
  -> immutable FAISS/BM25 or recoverable SQLite FTS5 index
  -> authenticated question
  -> AgentOrchestrator
       -> BoundedControllerAdapter (default)
       -> LangGraph StateGraph adapter (alternative / HITL)
  -> shared Tool Contract and server-owned ToolGateway
  -> search / find / open (direct or official MCP SDK adapter)
  -> ACL filtering + deadline/budget + retrieved-content Guard
  -> Evidence Ledger
  -> answer / partial / refusal / stop
  -> claim and citation verification
  -> cited response
  -> hash-chained trajectory -> replay -> enterprise.agent-run/1.0
```

## Trust boundary

The model may propose queries, tool arguments, and claims. It cannot grant
identity, expand ACL scope, open arbitrary tools, extend a deadline/budget,
admit quarantined content, or publish an unsupported citation. Those decisions
remain in server-owned code.

## Orchestration decision

The bounded implementation remains default because its smaller state surface
already satisfies the frozen mechanism suite. LangGraph provides explicit graph
state and interrupt/resume but did not improve behavior in the controlled
comparison and added diagnostic overhead. Both remain valuable because the
abstraction proves orchestration can change without moving authority.

## Data and evidence lifecycle

Document revisions create versioned chunks and indexes. ACL filtering occurs
before content becomes an Agent observation. Admitted evidence populates the
ledger; terminal generation produces structured claims; citation verification
removes unsupported claims. Semantic runtime events are appended in order and
can be verified/replayed or exported to EvalOps.

## Deployment boundary

The portfolio verifies a local FastAPI service and hardened container contract.
It does not include a distributed scheduler, network MCP service, persistent
HITL store, multi-writer trajectory ledger, or operational SLO.

