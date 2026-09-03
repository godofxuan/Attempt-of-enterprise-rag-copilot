# Final Project Decision

## Project Status

`PORTFOLIO_READY`

This repository is an enterprise-oriented Agentic RAG portfolio. It is not a
production deployment and does not claim production traffic, service-level
objectives, blind answer accuracy, or universal security.

## Final Default Strategy

`FINAL_DEFAULT = bounded Hybrid RRF runtime`

The default preserves server-owned identity and ACL enforcement, retrieved-content
Guard admission, typed ToolGateway budgets, Evidence Ledger tracking, citation
validation, grounding validation, and auditable trajectories. The LLM performs
bounded semantic work; it does not own user identity, permissions, filters,
budgets, tool authority, or final publication.

## Optional Profiles

| Profile | Status | Evidence boundary |
|---|---|---|
| BGE-M3 Dense retrieval | `USEFUL_EXPERIMENTAL` | Best simple arm on consumed WixQA ExpertWritten: Recall@5 66.42%, nDCG@5 52.16%, local p95 50.06 ms. No fresh promotion. |
| S4 validated multi-query | `USEFUL_EXPERIMENTAL` | Consumed quality profile: mean Recall@5 59.25% to 62.83%, but local p95 about 197 ms to 1148 ms and MRR down 0.10pp. |
| Oracle corrective rewrite | `CORRECTIVE_REWRITE_POSITIVE` | Corrected evaluation Oracle recovers first-pass misses; no precise executable retry trigger was demonstrated. |
| BGE reranker | `HISTORICAL_GPU_QUALITY_PROFILE` | Separate Dense/GPU experiment, not a direct comparison with the current Hybrid default. |

## Rejected Experiments

- Equal-RRF diversity variants: reduced retrieval ranking quality.
- G1 LLM evidence assessor as default router: 72.38% false retries on the
  consumed benchmark cohort.
- Previous G2 Oracle artifact: superseded because its cohort used a corrective
  arm outcome to select cases.
- S5 short-addendum adaptive retry: insufficient recovery and unstable outcomes.
- Final V3 retuning: intentionally not performed on consumed labels.

## Fresh and End-to-End Status

`NO_FRESH_VALIDATION_AVAILABLE` for the final V3 strategy comparison: the
repository does not establish an unused, compatible question-label cohort.
No V3 strategy is called a `FINALIST`, and no candidate-specific answer or
citation quality result is claimed. Existing contract tests cover citation,
grounding, Guard, ACL, evidence tracking, and terminal safety.

## Scope Freeze

`PROJECT_FEATURE_SCOPE_FROZEN`

Further retrieval or Agent capabilities require a new explicit project phase
with an unused evaluation protocol or a real operational failure signal.

Related evidence: [final V3 comparison](adaptive_retrieval_v3/FINAL_COMPARISON.md),
[dataset ledger](adaptive_retrieval_v3/DATASET_LEDGER.md), and
[resume metric ledger](handoffs/RESUME_METRIC_LEDGER.md).
