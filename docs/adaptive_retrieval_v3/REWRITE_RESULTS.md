# Adaptive Retrieval V3 Rewrite Results

## Superseded G2 Artifact

`evidence/g2-oracle-historical-v4.json` is retained for audit but is invalid
for system selection. It selected its Oracle subset from historical S4 fused
results, which is post-treatment selection bias. It must not be cited as a
corrective-rewrite result.

## F1/F2 Corrected G2: `CORRECTIVE_REWRITE_POSITIVE`

The corrected cohort is selected exclusively from frozen G1 first-pass,
post-Guard evidence: a question is included if its gold document set is not a
subset of its `post_guard_document_ids`. S4 output, rewrite output, and
corrective outcome are absent from the selector. This yields 95 baseline-
incomplete and 105 baseline-complete questions.

| Arm | Recall@5 | nDCG@5 | MRR@5 | Multi-doc complete@5 |
|---|---:|---:|---:|---:|
| R0 G1 first-pass post-Guard Top-5 | 14.21% | 12.00% | 16.91% | 0.00% |
| R2 S4 corrective, run 1/2 | 22.63% | 15.44% | 17.65% | 2.38% |
| R2 S4 corrective, run 3 | 23.16% | 15.69% | 17.65% | 4.76% |

R2 produces 8/8/9 full recoveries, 5 partial improvements, 77-78 no-change
cases, and 4 harms across the three frozen S4 repeats. It uses 95 rewrite calls
and 201 search queries for this 95-case Oracle slice; 53 expansions are
accepted and 42 safely fall back. The effect is positive and repeatable on
consumed development data, but it does not justify a default runtime router:
G1's independent assessor still over-triggers at 72.38% false retries.

F5 is not run. The corrected result does not show the prescribed evidence for
original-biased fusion, and changing the validator or fusion now would turn
final closure into label-driven tuning.

Evidence: [corrected cohort](evidence/g2-corrected-oracle-cohort-v1.json) and
[corrected comparison](evidence/g2-corrected-baseline-eedce3b.json). Raw G1
and S4 contents remain private.
