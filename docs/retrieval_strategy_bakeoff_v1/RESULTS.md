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
| S4 bounded two-query expansion, 3-run mean | 62.83% | 48.44% | 45.79% | 21.79% | 1147.98ms | R@5 +3.58pp; nDCG +1.28pp; MRR -0.10pp; complete +2.56pp | EXPERIMENTAL_KEEP |

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

## S4 Bounded Multi-query Expansion

The three runs use pinned local `qwen3:8b`, temperature `0`, `think=false`,
160 output tokens, and the same per-question seed policy. The model proposes
two alternatives; host validation accepts them only when they retain protected
capitalized entities/dates/numbers and meet the fixed JSON contract. All three
runs accepted 110/200 and fell back safely for 90/200. There were zero transport
errors and zero transport retries.

The relevant retrieval direction was positive in all three runs: Recall@5 was
`62.75%, 62.75%, 63.00%`; nDCG@5 was `48.41%, 48.41%, 48.49%`; multi-document
completeness@5 was `21.15%, 21.15%, 23.08%`. MRR was slightly lower than S0 in
all runs and p95 increased from `197.18ms` to `1144.37-1152.87ms`. It is thus a
bounded offline quality experiment, not an interactive default or a resume
claim of answer accuracy. Public evidence is
[run 1](evidence/wixqa-expertwritten-s4-b762b84-run1.json),
[run 2](evidence/wixqa-expertwritten-s4-b762b84-run2.json), and
[run 3](evidence/wixqa-expertwritten-s4-b762b84-run3.json).

## S5 Existing Bounded Adaptive Retry

On the frozen 20-case multi-document diagnostic, each of three runs had 17
baseline failures, 11 retry-attemptable cases, and only 2 fully recovered cases;
the pre-registered gate requires at least 3. The updated verifier compared the
full outcome tuple and found only 15/17 matches across run 1 vs run 2 and run 1
vs run 3. Raw model outputs matched 11/17 and parsed proposals 13/17. This is
a negative result: retain the historical stop and do not promote, tune, or
integrate the adaptive retry. Evidence:
[run 1](evidence/wixqa-adaptive-s5-run1-summary.json),
[run 2](evidence/wixqa-adaptive-s5-run2-summary.json),
[run 3](evidence/wixqa-adaptive-s5-run3-summary.json),
[comparison 1-2](evidence/wixqa-adaptive-s5-compare-1-2.json), and
[comparison 1-3](evidence/wixqa-adaptive-s5-compare-1-3.json).
