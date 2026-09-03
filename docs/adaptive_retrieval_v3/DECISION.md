# Adaptive Retrieval V3 Decision

## Current State

`NO_RUNTIME_CHANGE`

The V2 bounded Hybrid RRF runtime remains the default. The repaired G2 result
changes the interpretation of corrective rewrite capacity, but does not change
the serving policy.

## Final V3 Outcome

- G1 separated LLM evidence assessor: `REJECTED_AS_DEFAULT_ROUTER`. Its retry
  recall was high, but it falsely requested retry for 72.38% of baseline-complete
  cases on the consumed WixQA cohort.
- Historical G2 Oracle artifact: `SUPERSEDED_INVALID_POST_TREATMENT_SELECTION`.
  It is retained for audit and cannot support a system decision.
- Corrected G2 Oracle evaluation: `CORRECTIVE_REWRITE_POSITIVE`. Starting from
  baseline first-pass misses, frozen S4 corrective retrieval improved Recall@5,
  nDCG@5, MRR@5, and multi-document completeness across its three recorded
  repeats.
- Adaptive runtime: `REJECTED_FOR_DEFAULT`. The project has evidence that a
  correction can help when needed, but not evidence for a sufficiently precise
  executable trigger.

Default routing, identity/ACL authority, Guard admission, tool budgets,
Evidence Ledger, grounding, and response behavior remain unchanged. This is a
deliberate evidence boundary, not a conclusion that LLM evidence assessment or
query rewriting can never be useful.
