# Retrieval Strategy Bake-off v1 Protocol

## Purpose and Status

This is a new, offline comparison of retrieval-selection strategies. It does
not alter the deployed Agent runtime, ACL, Evidence Ledger, retrieved-content
Guard, grounding gate, or historical Adaptive Retrieval decision.

The historical `GLOBAL_ADAPTIVE_STOPPED` decision remains true for the old
17-case causal-promotion experiment. In this protocol, its frozen behavior may
only appear as an `EXPERIMENTAL_KEEP` candidate after three newly observed runs;
it is not prompt-tuned using those 17 cases.

## Common Contract

- Corpus and embedding: existing WixQA flat index, `bge-m3`, manifest/hash
  verified before every run.
- Cohort: 200 WixQA ExpertWritten questions. This cohort is **consumed** and
  retrospective, not a blind test or answer-accuracy benchmark.
- Final evidence budget: exactly five unique articles.
- Candidate generation: BM25 Top-200 articles plus BGE-M3 dense Top-200
  articles, fused with the index's frozen RRF `k=60`.
- Metrics: Article Hit@1, Recall@1/3/5, MRR@5, nDCG@5, multi-article
  completeness@5, mean/p50/p95 local retrieval latency, and candidate-window
  gold recall diagnostics.
- No strategy may weaken retrieved-content Guard, ACL, evidence provenance, or
  grounding boundaries. This phase is offline only, so serving security checks
  remain protected by their existing tests.

## Strategy Arms

| ID | Frozen behavior |
|---|---|
| S0 | Existing hybrid RRF, first five articles. |
| S1 | First 20 RRF articles, greedy diversity selector, final five. Relevance is `1 / RRF_position`; redundancy is maximum cosine similarity to an already selected article's query-best stored chunk; `alpha=0.75`. |
| S2 | Same as S1 with the first 40 RRF articles. |
| S3 | Existing guarded raw-chunk `BAAI/bge-reranker-v2-m3` Top-20 GPU evidence. Imported as consumed historical evidence; it is not rerun under the CPU-only project environment. |
| S4 | Future bounded multi-query expansion: exactly two validated alternatives from `qwen3:8b`, three runs, fallback to original question. |
| S5 | Future existing bounded adaptive retry: at most one retry, three runs, no prompt changes based on the prior 17 failures. |

## Decision Rules

Allowed statuses are `REJECTED`, `EXPERIMENTAL_KEEP`, and `DEFAULT_CANDIDATE`.

A deterministic arm is `EXPERIMENTAL_KEEP` when at least one relevant metric
improves against S0, no key metric declines by more than 5 percentage points,
and no security boundary fails. It becomes `DEFAULT_CANDIDATE` only after an
unseen validation result improves a relevant metric, has no other degradation
over 2 percentage points, and has acceptable p95 latency. An LLM arm also needs
a positive direction in at least two of three repeated runs.

No consumed-cohort result may be presented as general answer accuracy, a blind
external validation, or a production latency SLA.
