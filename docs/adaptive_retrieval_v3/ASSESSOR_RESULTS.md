# Adaptive Retrieval V3 Assessor Results

## G1 Decision: `REJECTED` as a Default Retry Router

This is a retrospective development-only diagnostic on the consumed 200-item
WixQA ExpertWritten cohort. It evaluates retrieval sufficiency only: the gold
label is whether the first post-Guard Top-5 evidence set contains every gold
article. It is not answer correctness or independent validation.

The model was local `qwen3:8b` (digest
`a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f`),
temperature 0, `think=false`, 120 output tokens, and stable per-question
seeds. It received the original question, first-pass query, ledger summary,
and only post-ACL/post-Guard admitted evidence. It received neither gold nor
a rewrite field nor tool authority.

| Metric | Run 1 | Run 2 | Run 3 | Mean / decision |
|---|---:|---:|---:|---|
| Retry precision | 52.80% | 52.80% | 52.80% | 52.80% |
| Retry recall | 90.43% | 90.43% | 90.43% | 90.43% |
| Retry F1 | 66.67% | 66.67% | 66.67% | 66.67% |
| False retry rate | 72.38% | 72.38% | 72.38% | 72.38% |
| Missed retry rate | 9.57% | 9.57% | 9.57% | 9.57% |
| Unavailable assessor outputs | 1 | 1 | 1 | 1 |
| Three-way per-case prediction agreement | - | - | - | 200 / 200 |

Each run has `TP=85`, `FP=76`, `FN=9`, and `TN=29` over 199 parseable
assessments. The one unparseable model output remains explicitly unavailable;
it is not silently converted to a retry or a sufficient verdict.

The assessor is stable but materially over-triggers: 76 of 105 evidence-
sufficient cases would incur an unnecessary corrective retrieval. It must not
become the default V2 Agent router. The default serving runtime remains
unchanged. G2 may still use an Oracle trigger to answer the separate causal
question of whether a valid corrective retrieval can recover first-pass misses.

Public, hash-only evidence: [run 1](evidence/g1-assessor-run1-e304212-summary.json),
[run 2](evidence/g1-assessor-run2-summary.json), and
[run 3](evidence/g1-assessor-run3-summary.json). Private raw questions,
admitted evidence, gold IDs, and model responses remain under ignored
`.private/adaptive_retrieval_v3/g1/`.
