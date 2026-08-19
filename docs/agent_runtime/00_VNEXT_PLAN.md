# Agent Runtime vNext Plan

## Frozen baseline

- Base branch: `main`
- Base commit: `cbc0780d83524efec255cc301d1b393d1077f141`
- Development branch: `codex/agent-runtime-vnext`
- Baseline policy: preserve retrieval, ACL, identity, retrieved-content admission,
  evidence ledger, citation verification, safe terminal behavior, indexing, and
  existing evaluation evidence.

The branch starts from the canonical release commit. Historical references to
`codex/rag-eval-system` describe earlier evidence generation; that branch is no
longer the active repository baseline.

## Objective

Turn the existing bounded Agent into one implementation behind a stable Agent
Runtime contract. Add protocol adapters, durable semantic trajectories, replay,
a meaningful human-review state, and EvalOps export without moving security
authority into a model or orchestration framework.

## Stage gates

| Stage | Deliverable | Promotion gate |
|---|---|---|
| A | Current runtime architecture | Documentation matches executable code and baseline tests pass |
| B | Orchestrator and tool contracts | Invalid identity, arguments, budget, deadline, stale context, and denied access fail closed |
| C | MCP adapter | MCP reaches retrieval only through the tool contract |
| D | Bounded and LangGraph-style orchestrators | Both use the same tools, evidence and terminal policy |
| E | Append-only trajectory | Ordered persistence, redaction, correlation, and tamper detection pass |
| F | Deterministic replay | Export reconstructs input, calls, evidence, output, and terminal reason |
| G | Human review | A real evidence ambiguity can pause and complete with an auditable decision |
| I | A/B evaluation | Same cases, model, retrieval, ACL, tools, and budgets; no quality claim without evidence |
| J | EvalOps artifact | Versioned schema, serializer, verifier, sample artifact, CI, and closeout |

Stage H (skills) is deferred until trajectories prove a repeated capability.
Multi-agent execution is explicitly out of scope.

## Authority invariants

1. Authenticated server context supplies tenant and identity. A model, MCP
   client, graph state, or tool arguments cannot replace it.
2. Existing navigation and retrieval remain the data path.
3. Existing ACL and retrieved-content admission remain mandatory.
4. Host code enforces budgets, deadlines, tool allowlists, evidence admission,
   citation checks, and terminal publication.
5. Orchestrators can propose work; they cannot publish unchecked output.
6. Trajectory records are semantic audit records, not an authorization source.
7. New resume claims require a frozen protocol and an artifact tied to a commit.

## Compatibility policy

The existing `POST /agent/v2/chat` behavior remains the default until an A/B
result justifies changing it. vNext components are additive and are introduced
behind explicit construction or configuration. A framework dependency is not
itself evidence of quality, safety, or production readiness.

## Evidence policy

Each stage records its tests, known limits, and commit. Existing public metrics
remain attributed to their original evidence commits. vNext mechanism tests may
support implementation claims, but cannot be reported as answer-quality gains.

