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

- **Stage:** Offline retrieval-only causal comparison over 88 historical
  first-pass failures.
- **Arms:** R0 original Top-5, R1 original-query Top-10 then fixed Top-5, and
  R2 historical validated two-query fusion from each S4 repeat.
- **Result:** R1 exactly equals R0. R2 Recall@5 is 15.34%, 15.34%, and 15.91%
  versus R0 15.91%; nDCG and MRR are lower in every run.
- **Decision:** `REJECTED`. Do not tune the validator or route this strategy
  into the default Agent. G3 and G4 have no eligible expansion candidate.

## G3-G9: Final Closure

- **G3:** Not run; no G2-positive candidate exists for a bounded repair.
- **G4/G5:** `REJECTED`; no conditional policy is assembled from a rejected
  trigger and rejected corrective action.
- **G6:** Existing deterministic S0-S2 controls remain the reference evidence.
- **G7:** Not run; no verified unused compatible cohort is available.
- **G8:** Not run; no `FINALIST` retrieval strategy exists to validate
  end-to-end.
- **G9:** `REJECTED`; V3 makes no runtime or default-policy change.
