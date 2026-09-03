# Adaptive Retrieval V3 Final Comparison

## F3 Same-Harness Simple Baselines

All three arms use the same consumed 200-question WixQA ExpertWritten cohort,
the same index manifest, article-level deduplication, final `K=5`, question-ID
set, and metric implementation. This is a one-pass identification comparison,
not hyperparameter tuning or fresh validation.

| Strategy | Recall@5 | nDCG@5 | MRR@5 | Multi-doc complete@5 | Mean / p50 / p95 local latency | Status |
|---|---:|---:|---:|---:|---:|---|
| B0 BM25 only | 42.75% | 32.15% | 31.16% | 11.54% | 83.73 / 74.37 / 164.89 ms | comparison arm |
| B1 BGE-M3 Dense only | 66.42% | 52.16% | 49.61% | 30.77% | 42.98 / 41.88 / 50.06 ms | `BEST_SIMPLE_BASELINE` |
| B2 Hybrid RRF | 59.25% | 47.16% | 45.89% | 19.23% | 126.93 / 116.86 / 209.55 ms | current runtime path |

Evidence: [F3 public aggregate](evidence/f3-simple-baselines-7d08d84.json).
The result confirms the existing public WixQA Dense comparison under a current,
identical harness. It does not alone promote Dense to the global serving
default because the cohort has already been consumed during development.

## Corrective-Rewrite Evidence

The prior G2 result is superseded: its Oracle cohort was selected using an S4
outcome, which is post-treatment selection and invalid for system selection.
The corrected cohort selects 95 baseline-incomplete questions exclusively from
G1 first-pass post-Guard evidence. On that Oracle slice, frozen S4 corrective
retrieval has a positive signal across all three historical repeats:

| Arm | Recall@5 | nDCG@5 | MRR@5 | Multi-doc complete@5 | Recovery |
|---|---:|---:|---:|---:|---|
| R0 first-pass baseline | 14.21% | 12.00% | 16.91% | 0.00% | reference |
| R2 corrective, S4 run 1/2 | 22.63% | 15.44% | 17.65% | 2.38% | 8 full, 5 partial, 4 harms |
| R2 corrective, S4 run 3 | 23.16% | 15.69% | 17.65% | 4.76% | 9 full, 5 partial, 4 harms |

This establishes `CORRECTIVE_REWRITE_POSITIVE` only under an evaluation Oracle.
It does not establish an executable retry policy: the independent G1 assessor
would retry 72.38% of already-complete cases on this consumed cohort.
Evidence: [corrected cohort](evidence/g2-corrected-oracle-cohort-v1.json) and
[corrected comparison](evidence/g2-corrected-baseline-eedce3b.json).

## F6-F9 Final Selection

- `C0`: BGE-M3 Dense is the best simple benchmark arm, but remains
  `USEFUL_EXPERIMENTAL` because no compatible fresh cohort was verified.
- `C1`: the bounded Hybrid RRF runtime remains `FINAL_DEFAULT`; its server-side
  identity, ACL, Guard, tool budget, Evidence Ledger, citation, and grounding
  boundaries are unchanged.
- `C2`: S4 always-on multi-query remains an offline `USEFUL_EXPERIMENTAL`
  quality profile. It improved consumed aggregate recall but increased local
  p95 from about 197 ms to 1148 ms and slightly reduced MRR.
- `C3`: Oracle corrective rewrite is `CORRECTIVE_REWRITE_POSITIVE`, not a
  deployable profile. No safe, conservative executable trigger is supported by
  the G1 evidence.
- Historical BGE reranker results are shown separately because they are not an
  F3/F6 same-harness comparison against the current Hybrid runtime.

## F7/F8 Boundaries

`NO_FRESH_VALIDATION_AVAILABLE`: no repository evidence verifies an unused,
compatible question-label cohort for V3. No candidate becomes a `FINALIST`.
Consequently F8 does not add a candidate-specific end-to-end answer/citation
claim. Existing citation, grounding, ACL, Guard, and Evidence Ledger tests are
contract coverage, not answer-quality benchmark evidence.
