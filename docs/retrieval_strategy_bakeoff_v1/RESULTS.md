# Retrieval Strategy Bake-off v1 Results

## Dataset and Boundary

All S0-S2 rows use the same consumed 200-question WixQA ExpertWritten cohort,
the same BGE-M3 index (`d21b...daa09`), the same question-id hash
(`ec11...76110`), and a final budget of five articles. They are retrieval
metrics only, not answer correctness or an independent blind result.

## Deterministic Comparison

| Strategy | Recall@5 | nDCG@5 | MRR@5 | Multi-doc complete@5 | p95 | Delta vs S0 | Status |
|---|---:|---:|---:|---:|---:|---|---|
| S0 hybrid RRF Top-5 | 59.25% | 47.16% | 45.89% | 19.23% | 197.18ms | reference | EXPERIMENTAL_KEEP |
| S1 RRF Top-20 + diversity | 58.75% | 46.92% | 45.74% | 19.23% | 182.99ms | R@5 -0.50pp; nDCG -0.24pp; MRR -0.15pp | REJECTED |
| S2 RRF Top-40 + diversity | 58.75% | 46.92% | 45.74% | 19.23% | 184.50ms | same quality loss as S1 | REJECTED |

S1 and S2 selected the same final five articles for every case. The fixed
`alpha=0.75` diversity objective is therefore not a promising mechanism on
this cohort. The correct action is to stop this line of tuning, not search for
a more flattering `alpha` on already consumed labels.

Evidence: [S0](evidence/wixqa-expertwritten-s0-b158a69-v1.json),
[clean S1](evidence/wixqa-expertwritten-s1-a296d32-v2.json), and
[S2](evidence/wixqa-expertwritten-s2-a296d32-v1.json). The earlier S1 export
is retained as an audit artifact; it has identical rankings but was produced
while the S0 evidence file was uncommitted.

## S3 Historical BGE Reranker

The existing guarded raw-chunk `BAAI/bge-reranker-v2-m3` GPU profile remains
`EXPERIMENTAL_KEEP`. On the same consumed ExpertWritten 200-question cohort it
reported Dense Recall@5 `66.42% -> 70.83%`, nDCG@5 `52.16% -> 57.18%`, and MRR@5
`49.61% -> 55.91%`; however multi-document completeness declined `30.77% ->
26.92%` and p95 increased `44.56ms -> 224.34ms`. It was compared with Dense,
not the S0 hybrid baseline above, and must not be presented as a direct bake-off
winner or default runtime change. Its hash-bound source is
[`raw_chunk_bge_evidence.json`](../wixqa_reranker/raw_chunk_bge_evidence.json).
