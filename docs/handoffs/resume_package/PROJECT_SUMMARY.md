# Project Summary

Current public branch/state: `main` / `PORTFOLIO_READY`.
Stable snapshot: `portfolio-v1.0.0`. Legacy `codex/*` refs remain only for
submitted-resume and historical-review link compatibility. Portfolio, resume,
teaching, and interview use are supported within the evidence boundaries below;
production readiness is not established. `RAG_VNEXT_CLOSED` remains the
historical vNext closeout marker originally recorded on
`codex/agent-runtime-vnext`; neither value names the current public branch.

## One sentence

An evidence-controlled enterprise RAG system with a replaceable Agent Runtime,
host-owned tool and publication boundaries, reproducible retrieval evaluation,
and auditable failure-driven release gates.

## Current architecture

```text
authenticated principal
  -> AgentOrchestrator (bounded default | LangGraph alternative)
  -> typed search/find/open request
  -> ToolGateway (identity + ACL + budget + deadline)
  -> retrieval + retrieved-content Guard
  -> Evidence Ledger + citation gate
  -> safe answer/refusal/partial terminal state
  -> hash-linked trajectory + replay + enterprise.agent-run/1.0
```

MCP is a local/in-process official-SDK adapter in front of the same ToolGateway;
it cannot bypass identity, ACL, budget, deadline, or content admission. Generic
partial-answer HITL remains same-process. The optional durable path covers only
one restart-tested, draft-only access-request workflow and is not a general
durable Agent runtime.

## Measured evidence

The sole numeric authority is `docs/handoffs/RESUME_METRIC_LEDGER.md`. The
headline families are WixQA retrieval ranking, one-host FTS5 indexing, and one
pinned retrieved-content attack subset. Runtime parity and the public Agent Run
Artifact are mechanism evidence for interview explanation, not quality uplift.

## Engineering judgment

- Bounded remains default because the LangGraph alternative showed compatibility,
  not answer-quality gain, and added overhead in a tiny diagnostic.
- Equal RRF and a bounded multi-document candidate remain rejected historical
  experiments. The vNext runtime does not rewrite those results.
- New functionality requires a measured need and a fresh protocol; architecture
  breadth alone is not a release criterion.

## Historical state

The 2026-08-11 `PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW` snapshot is
retained in dated reports. It referred to the prior RAG/evaluation closeout and
the rejected multi-document candidate. It is not the current canonical state.

## Boundary

This project does not claim blind answer correctness, universal security,
production network MCP/OAuth, durable execution, WORM audit certification,
distributed high availability, production SLOs, or third-party validation.
