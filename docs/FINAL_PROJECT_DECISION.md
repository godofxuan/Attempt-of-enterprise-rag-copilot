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
| BGE reranker | `OPTIONAL_GPU_QUALITY_PROFILE` | Final paired Guard-before-rerank Raw Top-20 on consumed WixQA: Recall@5 66.42% to 72.50%, nDCG@5 52.16% to 59.35%, MRR@5 49.61% to 57.92%, total local p95 296.48 ms. It does not change the fast global default. |

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

## Post-Closure Peer Reproduction

An explicit user-requested isolated reproduction of peer branch `79ba431`
confirmed an article-level BGE reranker peak of 71.25% Recall@5 on the consumed
WixQA cohort. It did not reproduce a 75% result and was not merged because that
offline branch bypasses the current retrieved-content Guard. This is additional
evaluation evidence, not a reopened feature-development phase or a change to
the final default. See
[peer reproduction aggregate](wixqa_reranker/peer_branch_article_reproduction_v1.json).

## Final Safe Raw-Chunk Closure

The peer's raw-chunk idea was then evaluated in a final paired protocol: one
official-LF index, one frozen raw candidate artifact, shared scorer, Shadow
Guard diagnostics for OFF arms, enforced Guard for ON arms, no Dense backfill,
and full-text tokenizer truncation. Guarded Raw Top-50 reached Recall@5
`74.50%`, but its `677.93 ms` total local p95 exceeded the protocol's fixed
`650 ms` limit. Guarded Raw Top-20 is therefore the sole optional GPU quality
profile. Guard-off `74.75%`/`75.00%` values remain diagnostic ceilings and are
not runtime eligible. See [final paired evidence](wixqa_reranker/RAW_CHUNK_GUARD_FINAL_RESULTS.md).

Related evidence: [final V3 comparison](adaptive_retrieval_v3/FINAL_COMPARISON.md),
[dataset ledger](adaptive_retrieval_v3/DATASET_LEDGER.md), and
[resume metric ledger](handoffs/RESUME_METRIC_LEDGER.md).
