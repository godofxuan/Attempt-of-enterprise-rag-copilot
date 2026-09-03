# Final Evaluation Summary

## Evaluation Boundary

The final closure keeps retrieval quality, answer quality, local latency, and
production claims separate. The F3 and corrected G2 results use the consumed
200-question WixQA ExpertWritten retrieval cohort; they are not blind validation
and do not measure answer correctness.

## Same-Harness Simple Retrieval Baselines

| Strategy | Recall@5 | nDCG@5 | MRR@5 | Multi-doc complete@5 | Local p95 |
|---|---:|---:|---:|---:|---:|
| BM25 | 42.75% | 32.15% | 31.16% | 11.54% | 164.89 ms |
| BGE-M3 Dense | 66.42% | 52.16% | 49.61% | 30.77% | 50.06 ms |
| Hybrid RRF | 59.25% | 47.16% | 45.89% | 19.23% | 209.55 ms |

`BEST_SIMPLE_BASELINE = BGE-M3 Dense`. The aggregate artifact binds cohort,
index, model, exact revision, and metrics: [F3 evidence](adaptive_retrieval_v3/evidence/f3-simple-baselines-7d08d84.json).

## Corrected Adaptive-Retrieval Result

The old G2 cohort used S4 outcomes and was invalid. The repaired Oracle cohort
is selected solely by whether G1 first-pass post-Guard retrieval omitted a gold
document: 95 incomplete and 105 complete cases. On those 95 baseline misses,
frozen S4 correction improved Recall@5 from 14.21% to 22.63%/23.16%, nDCG@5
from 12.00% to 15.44%/15.69%, and MRR@5 from 16.91% to 17.65% in three recorded
historical repeats. Full recoveries were 8, 8, and 9; each repeat had four harms.

This is positive evidence for **correction capacity under an Oracle trigger**,
not for a deployed adaptive policy. The runnable G1 LLM assessor would retry
72.38% of already-complete cases, so the adaptive controller is not enabled.
See [cohort evidence](adaptive_retrieval_v3/evidence/g2-corrected-oracle-cohort-v1.json)
and [comparison evidence](adaptive_retrieval_v3/evidence/g2-corrected-baseline-eedce3b.json).

## Cost and Latency

All latency figures are offline local-workstation measurements, not production
SLOs. Always-on S4 multi-query improved aggregate consumed recall but increased
local p95 from about 197 ms to 1148 ms. On the corrected 95-case Oracle slice,
the corrective path made 95 rewrite calls and 201 search queries; it reuses
historical S4 outputs, so a comparable corrected end-to-end latency was not
re-measured.

## Negative Results and Limits

- Equal-RRF diversity did not outperform the simple Dense arm.
- A high-recall LLM assessor was too imprecise for default retry routing.
- No compatible unused V3 question-label cohort is verified.
- No candidate-specific final answer/citation benchmark was run, because no V3
  candidate reached fresh-evidence finalist status.
- Security evidence is retained separately: the pinned Guard OFF/ON experiment
  is not a claim of universal injection safety.

The full system-selection rationale is in [FINAL_PROJECT_DECISION.md](FINAL_PROJECT_DECISION.md).
