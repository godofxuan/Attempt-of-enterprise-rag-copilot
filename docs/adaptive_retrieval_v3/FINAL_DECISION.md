# Adaptive Retrieval V3 Final Decision

## Project Status

`FINAL_CLOSURE_COMPLETE`

Further retrieval or Agent feature work is a new project phase, not an
unfinished requirement for this portfolio release.

## Final Runtime Strategy

`FINAL_DEFAULT = current bounded Hybrid RRF runtime`

The deployed default is unchanged: verified identity, ACL, retrieved-content
Guard, typed tool budgets, Evidence Ledger, citation/grounding gates and the
existing Hybrid retrieval path remain server-owned. F3 shows that Dense is the
best simple WixQA benchmark arm, but the cohort is consumed development data;
that alone is insufficient reason to silently change the global runtime.

## Optional Profiles

| Profile | Status | Boundary |
|---|---|---|
| BGE-M3 Dense retrieval | `USEFUL_EXPERIMENTAL` | Strongest simple arm on consumed WixQA ExpertWritten: Recall@5 66.42%, nDCG@5 52.16%, MRR@5 49.61%, p95 50.06ms. Not a fresh global promotion. |
| S4 always multi-query | `USEFUL_EXPERIMENTAL` | Historical consumed WixQA result improves aggregate Hybrid Recall@5 59.25% to mean 62.83%, with local p95 about 197ms to 1148ms and a small MRR loss. Offline quality profile only. |
| Oracle corrective rewrite | `CORRECTIVE_REWRITE_POSITIVE` | Corrected G2 demonstrates recovery value after an Oracle trigger, but G1 supplies no acceptable executable default trigger. |
| BGE reranker | `HISTORICAL_GPU_QUALITY_PROFILE` | Separate Dense-based, GPU-specific historical evidence. It is not a same-harness F6 delta. |

## Rejected Experiments

- G1 LLM assessor as default router: stable but 72.38% false retries.
- G2 historical post-treatment-selection artifact: invalid for decisions.
- S1/S2 diversity selection: historical negative results.
- S5 short-addendum adaptive retry: historical negative result.
- No F5 tuning: closure rule blocks extra optimization on consumed labels.

## Validation and End-to-End Status

`NO_FRESH_VALIDATION_AVAILABLE`: the V3 ledger establishes no verified unused,
compatible question-label cohort. No strategy is promoted to `FINALIST` from
V3 retrieval evidence. Therefore there is no new candidate-specific F8 answer
or citation claim; existing runtime grounding/citation tests remain contract
coverage, not a new answer-quality benchmark.

## Claim Boundary

V3 retrieval metrics are not answer accuracy, production latency, or global
quality claims. Local workstation timings are offline measurements.
