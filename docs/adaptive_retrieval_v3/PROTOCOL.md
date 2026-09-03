# Adaptive Retrieval V3 Protocol

## Purpose

V3 evaluates a bounded offline policy:

```text
first-pass hybrid retrieval -> post-ACL/post-Guard evidence -> assessor
-> at most one validated two-query corrective retrieval -> fixed Top-5 evidence
```

It asks separately whether evidence assessment, semantic query reformulation,
and conditional routing add measurable value. It does not modify the default
V2 controller or any authority boundary during evaluation.

## Immutable Boundaries

- The model may emit only an evidence-sufficiency verdict, bounded missing
  aspects, or validated query text.
- Identity, ACL, filters, candidate depth, Top-K, retry count, budgets,
  deadlines, Guard disposition, tool access, citations, and publication remain
  server-owned.
- Every future corrective search must use the ordinary `SearchRequest` through
  `ToolGateway`, ACL filtering, retrieved-content Guard, and Evidence Ledger.
- One corrective round maximum. No recursive rewrite, planner, critic, or
  hidden reasoning logging.

## Historical Boundaries

- `docs/adaptive_retrieval_v2/` remains the authoritative description of the
  earlier short-addendum experiment and its negative promotion decision.
- WixQA ExpertWritten 200 and its old 17-case adaptive-failure subset are
  consumed development data. They may diagnose and regress, but are never
  called blind, fresh, or independent validation.
- S4's always-on two-query result is historical consumed evidence. It is a
  causal control, not a result V3 may silently overwrite.

## G0-G9 Sequence

| Gate | Question | Change allowed |
|---|---|---|
| G0 | What code, data, and historical claims actually exist? | Documentation only. |
| G1 | Does `qwen3:8b` identify retrieval evidence insufficiency? | Offline assessor only. |
| G2 | Under an Oracle trigger, does rewrite beat same-query extra depth? | Offline evaluation only. |
| G3 | Why are expansions accepted/rejected, and is one bounded fix justified? | At most one validator/fusion change. |
| G4 | Does conditional V3 retain always-on quality at lower cost? | Offline composition only. |
| G5 | Is LLM routing worth more than deterministic routing? | Offline comparison only. |
| G6 | Are simple BM25/Dense/Hybrid controls fairly represented? | Evaluation harness only. |
| G7 | Do frozen finalists retain value on unused data? | No post-result tuning. |
| G8 | Do finalist retrieval gains survive answer/citation/grounding evaluation? | No runtime default change. |
| G9 | Which profile is the evidence-backed default? | Runtime integration only if `FINAL_DEFAULT`. |

## Metrics and Repetition

- Final retrieval evidence budget is five unique articles.
- G1 positive class is `gold_retrieval_insufficient`: first-pass Top-5 does not
  cover all gold articles. It is retrieval sufficiency, not answer correctness.
- Assessor metrics: retry precision/recall/F1, false-retry rate, missed-retry
  rate, sufficient precision/recall, confusion matrix, and 3/3 vs 2/3 semantic
  decision agreement.
- G2-G5 track Recall@5, nDCG@5, MRR@5, multi-document completeness, LLM calls
  split by assessor/rewrite, search-query count, validator outcomes, and local
  offline p95 latency.
- Each LLM strategy runs exactly three times with the same model digest,
  prompt/schema hashes, generation configuration, and per-question seed policy.
  Headlines use mean/min/max, never the best run.

## V3 Statuses

Only these maturity labels may be used:
`REJECTED`, `USEFUL_EXPERIMENTAL`, `FINALIST`, `FINAL_DEFAULT`.

A small repeatable positive result is still evidence. Promotion additionally
requires acceptable trade-offs, preserved security, and previously unused
validation; a desktop offline latency is never a production SLA.
