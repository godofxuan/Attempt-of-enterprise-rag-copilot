# R2-S8 Results

## Current status

G0-G4 tooling is complete. G5 real independent human review and G6 public
release evidence are `NOT RUN`.

## What is now implemented

- immutable model/verdict-blinded, reference-guided reviewer packets;
- source-run, dataset, commit, rubric, threshold, and artifact hashes;
- separate source-file and displayed-content hashes;
- dev/test/external-holdout purpose and independence controls;
- strict pseudonymous human submissions;
- shared-domain HMAC reviewer identities;
- complete per-item and per-candidate-document labels;
- two distinct reviewers;
- raw agreement, Cohen's kappa, and ordinal weighted kappa;
- preserved disagreements and third-person adjudication;
- human relevance precision@5, recall@5, and nDCG@5;
- bound pooled-run provenance and conservative uncertainty scoring;
- dimension-macro agreement, overall-answer kappa, and retrieval weighted kappa;
- exact recovery from packet/control partial publication;
- answer acceptance, safety failure, and uncertainty metrics;
- fail-closed `FIXTURE_ONLY`, `CALIBRATION_COMPLETE`, `INCONCLUSIVE`,
  `FAILED`, and `SUPPORTED` decisions;
- recomputable, no-overwrite evidence bundles.
- version-pinned, repeated LLM-judge calibration against human consensus;
- fail-closed single-trial and same-family-correlation handling;
- explicit no-release/no-security authority for the LLM judge.

## Verified public calibration packet

`data/v2/quality_review/r2-s8-calibration-v3`

| Property | Value |
|---|---|
| Item count | 12 |
| Split | dev |
| Sampling | stratified random, seed 1729 |
| Answered / not-found / permission | 8 / 2 / 2 |
| Returned / candidate / reference evidence | 37 / 37 / 10 |
| Candidate pool strategy | `returned_plus_reference` |
| Population | public synthetic |
| Independent holdout | no |
| Human labels completed | 0 |
| Claim status | `NOT_RUN` |

## Verification

Focused tests:

```text
20 passed
3 unrelated SWIG deprecation warnings
```

The real packet passed `verify_quality_review_packet`. A test evidence bundle
also passed full recomputation, and deliberate summary tampering was rejected.
This dev packet is suitable for reviewer-flow calibration only. Because all
reference evidence was already present in its returned rankings, its 37-item
candidate pool does not expose a known retrieval miss. Final held-out evidence
must use `pooled_variants`.

Broader evaluation regression:

```text
999 passed, 16 skipped, 3 warnings
```

Full repository regression:

```text
2379 passed, 30 skipped, 3 warnings
```

Public repository audit:

```text
745 candidates, 0 findings
```

## What these results do not prove

The current results prove software contracts and an executable annotation
workflow. They do not prove retrieval relevance, factuality, citation
entailment, refusal usefulness, or production quality because no real
independent labels have been supplied.

G4 also has no real calibration result. Its successful fixture and negative
tests establish calibration behavior only.

The current human protocol is reference-guided, not verdict-blind. Reviewers
see frozen expected response mode and reference material; this supports
criterion-based scoring but can anchor refusal judgements.
