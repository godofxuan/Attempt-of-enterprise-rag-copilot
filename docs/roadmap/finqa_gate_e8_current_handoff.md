# FinQA Gate E8 Current Handoff

## Authoritative state

- Gate: `E8_DEVELOPMENT_PROGRESS_GATE_FAILED`
- Cohort: disclosed 60-case development calibration, 58 typed cases, 123 roles
- Internal validation: `NOT_RUN`
- Frozen test: `UNTOUCHED`
- Serving: `DISABLED`
- Selected E8 configuration: descriptor priority `0`, candidate local weight `1`

## What E8 established

1. The v3 safe catalog represents 100% of 1,736 admitted operand candidates.
2. Gold descriptor selection plus the real reranker reaches 100% Candidate
   Recall@8, so the catalog/reranker interface has sufficient Top-8 capacity.
3. Runtime Descriptor Recall@4 improved from 83.74% to 84.55%.
4. Runtime Candidate Recall@8 stayed at 78.86%; Top-4 and complete-case quality
   regressed, so the challenger cannot replace E7.
5. Uniform descriptor-priority bonuses are rejected by disclosed ablation.

## Next proposed gate: E9 learned ranking without cohort leakage

Before implementation, freeze:

1. FinQA train-only feature/label construction and source hashes;
2. document/company-grouped cross-validation folds;
3. value-free descriptor features and host-only candidate features;
4. baselines E7 v2 and E8 selected configuration;
5. thresholds for descriptor Recall@4, Candidate Recall@4/@8, complete-case,
   calibration stability and all existing security/identity invariants;
6. a rule that the 40-case internal validation remains unread until the
   train/CV challenger passes the development gate.

Recommended implementation is a small interpretable ranker or calibrated
linear/tree model, not another free-form planner. It must publish feature
importance, fold variance, paired gains/regressions and a fail-closed fallback
to the current deterministic champion.

Recommended model for E9 contract and leakage audit: **5.6 Sol / Extra High**.
Routine fixture and documentation work can use **5.6 Terra / High** after the
protocol is frozen.

