# Retrieval Strategy Bake-off v1 Decision

## P3-P8 Decision

| Strategy | Status | Decision |
|---|---|---|
| S0 baseline hybrid RRF | EXPERIMENTAL_KEEP | Remains the current runtime reference. This bake-off provides no independent validation sufficient to relabel it a `DEFAULT_CANDIDATE`. |
| S1 diversity Top-20 | REJECTED | It reduced all three relevant quality metrics against S0. Do not tune `alpha` on the consumed cohort. |
| S2 diversity Top-40 | REJECTED | It produced the same quality loss as S1 with no compensating multi-document benefit. |
| S3 guarded raw-chunk BGE reranker | EXPERIMENTAL_KEEP | Existing GPU-only, consumed-cohort evidence has positive ranking metrics but a multi-document completeness and latency trade-off. It is not a default path. |

No serving integration is approved. The next evaluation work is S4/S5 only if
the transport observations, deterministic validators, three-run protocol, and
outcome-tuple reproducibility check are in place first.
