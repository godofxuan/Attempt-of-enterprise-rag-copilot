# Adaptive Retrieval V3 Engineering Journal

## G0: Repository and Dataset Audit

- **Stage:** G0 Repository + dataset audit
- **Git SHA:** `827306d7aad4d9d3160e9bb3cf8f90d58fd43e9e`
- **Dataset:** WixQA and repository-visible external evaluation records.
- **Dataset status:** WixQA ExpertWritten 200 and the 17-case adaptive subset
  are `CONSUMED_DEVELOPMENT`.
- **Hypothesis:** None. This gate records facts before any V3 model call.
- **Arms:** None.
- **Primary question:** Can V3 separate assessment, rewrite, and routing without
  altering historical conclusions or authority boundaries?
- **Result:** Yes. The existing V2 runtime is bounded and Guard/ACL/Gateway
  owned. The old local assessor combines verdict and rewrite in one call, so it
  cannot answer V3's component questions unchanged. Existing S4 has a separate
  two-query validator/retrieval harness that can be reused offline.
- **Interpretation:** Build a new evaluation-only assessor contract; do not
  change `controller_v2.py`, `runner_v2.py`, `ToolGateway`, or serving policy.
- **Decision:** G0 complete. Proceed to G1 assessor quality only.
- **Next:** Freeze the assessor contract and three-run quality protocol.

## G1: Separated Evidence-Sufficiency Assessor

- **Stage:** G1 assessment-only evaluation; no rewrite or retry execution.
- **Dataset:** WixQA ExpertWritten 200, `CONSUMED_DEVELOPMENT`.
- **Arms:** Identical local `qwen3:8b` assessor run three times.
- **Result:** 200/200 per-case retry predictions agreed across all three runs.
  On each run: TP 85, FP 76, FN 9, TN 29; retry recall 90.43%, retry
  precision 52.80%, and false-retry rate 72.38%. One response was a parse
  error in every run and was recorded as unavailable.
- **Interpretation:** The assessor consistently catches most first-pass
  insufficiency but would impose a corrective retrieval on most already
  sufficient cases. Stability is necessary but does not make its operating
  point useful for the default interactive path.
- **Decision:** `REJECTED` as a default retry router. No serving code changes.
- **Next:** G2 Oracle-triggered causal retrieval comparison: distinguish the
  benefit of a corrective query from merely retrieving deeper with the same
  query.

## G2: Oracle-Triggered Corrective Retrieval

- **Stage:** The original historical G2 artifact selected 88 cases from S4
  fused outcomes.
- **Result:** It was later found to have post-treatment selection bias.
- **Decision:** Preserve `g2-oracle-historical-v4.json` for audit, but mark it
  `SUPERSEDED_INVALID_POST_TREATMENT_SELECTION`. It cannot answer the causal
  question and cannot support the default decision.

## F0-F10: Final Evidence Repair and Closure

- **Stage:** Final closure at repair SHA `eedce3b843f5b1bc26d32d0c3d9f9b0afee15c24`.
- **Dataset:** WixQA ExpertWritten, 200 questions, `CONSUMED_DEVELOPMENT`.
- **Question:** Does frozen S4-style corrective retrieval improve evidence when
  a frozen G1 first-pass post-Guard retrieval is actually incomplete?
- **Code changed:** Evaluation-only Oracle selection now uses only
  `gold_document_ids` and `post_guard_document_ids`; tests prohibit a corrective
  arm input to the selector.
- **Arms:** R0 frozen first pass; R2 frozen S4 multi-query corrective retrieval.
- **Metrics:** Recall@5, nDCG@5, MRR@5, multi-document completeness, recovery
  counts, expansion calls, and search calls.
- **Result:** The corrected Oracle slice contains 95 incomplete and 105 complete
  cases. R2 improved Recall@5 from 14.21% to 22.63%/23.16% across the three
  frozen repeats, with 8/8/9 full recoveries and four harms per repeat.
- **Decision:** `CORRECTIVE_REWRITE_POSITIVE`, but `REJECTED_AS_DEFAULT_ROUTER`:
  G1's executable assessor still over-triggers at 72.38% false retries.
- **F3:** Same-harness simple baselines identify BGE-M3 Dense as
  `BEST_SIMPLE_BASELINE` (66.42% Recall@5; 52.16% nDCG@5; 50.06 ms p95 local).
- **F5:** Not run. The evidence does not justify changing a frozen validator or
  fusion rule on consumed labels.
- **F6-F8:** No compatible unused question-label cohort is verified, so no V3
  `FINALIST` or candidate-specific answer/citation evaluation is claimed.
- **F9:** Bounded Hybrid RRF remains `FINAL_DEFAULT`; Dense and S4 are scoped
  experimental profiles.
- **Next:** `PROJECT_FEATURE_SCOPE_FROZEN` after release verification.
