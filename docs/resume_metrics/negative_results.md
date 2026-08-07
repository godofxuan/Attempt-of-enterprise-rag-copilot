# Negative Results and Constraints

## FinQA selective execution

On a 100-case development validation, strict execution moved from 0.53 to 0.55, but paired significance was `p=0.625` and one case regressed. Generation calls fell by 32% and calculator calls by about 30.52%. Because answer quality did not improve significantly, the policy was not promoted. Cost reduction may be discussed as a development result, not as a final quality gain.

## FinanceBench page reranker development result

The existing local-LLM page-reranker experiment was selected on development data and is not an independent generalization result. It cannot be presented as final improvement. The new round must compare deterministic retrieval arms and any cross-encoder on the development split before one fixed-test execution.

## FinanceBench parser hypothesis is not established

Historical diagnostics found all 63 development gold page references represented in chunks and 49/63 with high text overlap. On the fixed test, many failures had the correct document highly ranked but missed the exact page. This points first to page ranking/localization, not enough evidence to justify replacing the ingestion pipeline with Docling or MinerU. A parser ablation remains conditional on typed failure counts.

## Fixed test is not fresh blind data

The public FinanceBench release contains only 150 annotated examples. This repository already used a 49/101 development/test split and has disclosed aggregate test results. Repartitioning those same 150 cases would not create a new unseen test. New experiments must state that limitation and avoid repeated test-driven tuning.

## Synthetic evidence has limited external validity

The expanded enterprise corpus and custom prompt-injection pairs are valuable regression gates, but project authors control both data and implementation. Their perfect or near-perfect results do not establish external generalization.

## Tooling and execution incidents

- Running a package verifier from repository root caused `unexpected public artifact set`; explicit package paths fixed the invocation.
- `ruff` is not installed in the project virtual environment. Python tests and `git diff --check` passed; no lint result should be claimed for this checkpoint.
- Pytest attempted to clean historical files under the user C-drive temp directory and emitted permission warnings. Subsequent experiment commands set `TEMP` and `TMP` to `.private/tmp` on drive D.

## FinanceBench retrieval and cross-encoder ablation

On the 49-case development split, Dense reached Page Hit@5 44.90%, nDCG@5
0.3525, and p95 533.30 ms. BM25 and RRF were both worse. A pinned generic
cross-encoder top-10 reached Hit@5 46.94% but nDCG fell to 0.3472 and p95 rose
to 2466.12 ms. It was not promoted and the historical fixed test was not rerun.

## Parser and adaptive retrieval stop decisions

Only 1/31 typed retrieval failures showed deterministic parser risk, below the
pre-registered 20% trigger. A hindsight adaptive union could rescue four cases,
but no non-oracle selector was established and tested branches caused
regressions. Neither parser replacement nor automatic retry was enabled.

## External security summary export incident

The first holdout `summary.json` correctly stored all numeric 12-attack/2-benign
counts but its limitation sentence was hard-coded as `12-attack/4-benign`.
Commit `95fc114` made this text fixture-driven. The immutable private result hash
is the source for the corrected public evidence; the incident is disclosed in
`evidence/garak_latent_report_holdout_v1.json`.
