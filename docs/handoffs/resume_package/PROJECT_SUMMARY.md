# Project Summary

## One sentence

An evidence-controlled enterprise RAG/Agent portfolio that separates retrieval,
identity/ACL, retrieved-content admission, evidence completeness, citation
filtering, lifecycle activation, and release evaluation.

## Architecture

```text
authenticated principal
  -> rule-first query analysis
  -> bounded typed tools
  -> ACL-filtered retrieval
  -> retrieved-content Guard
  -> Evidence Ledger
  -> candidate claims
  -> deterministic citation/grounding filter
  -> safe answer/refusal/partial terminal state
```

Python host code owns authority, tool budgets, evidence visibility, terminal
states, and final claim publication. Local models provide embeddings or candidate
text but cannot expand identity scope or grant tools.

## Strongest measured evidence

1. WixQA ExpertWritten, 200 fixed public-label retrieval questions: Dense versus
   BM25 Recall@5 `42.75% -> 66.42%`, nDCG@5 `32.15% -> 52.16%`.
2. EnterpriseRAG-Bench: FTS5 index over 511,962 rows/9 source types, 1.37 GiB,
   231.35 seconds, about 1.83 GiB peak RSS on one host.
3. Pinned garak subset: Guard OFF/ON observed ASR `4/12 -> 0/12`, context
   exposure `12/12 -> 0/12`, mean scan 1.42 ms; only two benign controls.

## Engineering judgment evidence

- Equal RRF was rejected: Recall@5 59.25% versus Dense 66.42%, p95 304.64
  versus 157.41 ms.
- A bounded 20-case multi-document candidate was rejected: zero complete-case
  fixes, 0pp completeness gain, -5.83pp precision, and 1.859x p95 latency.
- Feature development stopped because the available multi-document cohort is
  consumed and no new legally usable validation cohort exists.

## Current status

`PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW`

This does not mean production-ready, blind answer-accuracy validated, universally
secure, or independently reproduced by a third party.
