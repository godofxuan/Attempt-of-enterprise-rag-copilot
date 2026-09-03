# Retrieval Strategy Bake-off v1 Decision

## P3-P8 Decision

| Strategy | Status | Decision |
|---|---|---|
| S0 baseline hybrid RRF | EXPERIMENTAL_KEEP | Remains the current runtime reference. This bake-off provides no independent validation sufficient to relabel it a `DEFAULT_CANDIDATE`. |
| S1 diversity Top-20 | REJECTED | It reduced all three relevant quality metrics against S0. Do not tune `alpha` on the consumed cohort. |
| S2 diversity Top-40 | REJECTED | It produced the same quality loss as S1 with no compensating multi-document benefit. |
| S3 guarded raw-chunk BGE reranker | EXPERIMENTAL_KEEP | Existing GPU-only, consumed-cohort evidence has positive ranking metrics but a multi-document completeness and latency trade-off. It is not a default path. |
| S4 bounded multi-query expansion | EXPERIMENTAL_KEEP | Three runs improved Recall@5/nDCG@5 and multi-document completeness, but added about 951ms p95 and slightly lowered MRR/Hit@1. Keep offline; do not integrate. |
| S5 bounded adaptive retry | REJECTED | It recovered only 2/17 against a frozen 3/17 gate, and only 15/17 full outcome tuples repeated. Do not tune or promote it. |

No serving integration is approved. No arm reached `DEFAULT_CANDIDATE`: the
only observed positive LLM arm is too slow for the interactive default and was
measured on consumed labels. A future promotion decision requires an untouched
validation protocol and end-to-end answer/citation evidence, not more tuning of
this cohort.
