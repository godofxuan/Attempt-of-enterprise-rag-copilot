# FinQA Gate E9 Current Handoff

## Authoritative state

- Train-only CV: `E9_CV_CHALLENGER_ELIGIBLE_FOR_ONE_DEVELOPMENT_RUN`
- Formal development: `E9_DEVELOPMENT_GATE_FAILED_KEEP_E8_CHAMPION`
- Development evaluation ordinal/budget: `1/1`, consumed
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- E9 serving: `DISABLED`
- Internal validation: `NOT_RUN`
- Frozen test: `UNTOUCHED`

## Results

Company-disjoint OOF Descriptor Recall@4 improved from 88.76% to 90.84%
(+2.08pp), with 1.24pp fold standard deviation. The single disclosed 60-case
development run then regressed Descriptor Recall@4 from 84.55% to 78.86% and
Candidate Recall@8 from 78.86% to 75.61%. Conditional candidate retention
improved from 93.27% to 95.88%, but that did not offset first-stage losses.

Paired role transitions were 93 retained, 11 regressed, 4 gained and 15 missed
by both. E8 remains champion. Do not alter the E9 artifact and rerun the 60-case
cohort under the same protocol.

## What is complete

1. Pinned train SHA and company-disjoint 5-fold protocol.
2. 23-feature value-free linear ranker with a self-hashing artifact.
3. Fail-closed E8 champion fallback.
4. Full 3,068-case preparation ledger and aggregate failure accounting.
5. Train-only OOF evidence, one formal development result and paired postmortem.
6. Public evidence verification tests and beginner learning chapter.

## Next admissible work

E10 must be a new train-only protocol, not an E9 rerun. It should evaluate:

1. retrieval-realistic train evidence that does not force gold inclusion;
2. pairwise/listwise role-level Top-4 ranking;
3. a bounded learned residual around E8 rather than full score replacement;
4. coefficient stability and feature ablations across company folds;
5. a new evidence source for later confirmation.

Do not consume the 40-case internal validation or frozen test. Do not claim E9
improved answer accuracy or production ranking.

Recommended model for E10 protocol and leakage review: **5.6 Sol / Extra High**.

