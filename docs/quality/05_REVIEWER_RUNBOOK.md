# R2-S8 Independent Reviewer Runbook

## Current boundary

This runbook executes the 12-case development calibration pilot in
`data/v2/quality_review/r2-s8-calibration-v3`. It is not the final 60-case
independent held-out acceptance.

Two different people are required. Codex, an LLM judge, or one person using two
identities cannot satisfy this gate.

## Operator separation

The operator gives each reviewer only a copy of:

```text
data/v2/quality_review/r2-s8-calibration-v3/
```

Do not give reviewers:

- `.private/quality/control/`;
- source case IDs;
- source run failures;
- machine pass/fail labels;
- model identity;
- the other reviewer's completed template.

Reviewers should not inspect the repository or evaluation dataset while
grading. The reference answer and authorized evidence inside the packet are the
grading reference.

## Reviewer task

Each reviewer independently fills their own copy of
`submission_template.csv`.

For every source in `retrieval_candidate_evidence`:

```json
[{"source_id": "the exact source ID", "grade": "0|1|2|uncertain"}]
```

Then complete:

- factual correctness;
- completeness;
- citation support;
- refusal appropriateness;
- access safety;
- overall acceptability;
- primary failure stage;
- a short rationale.

Do not fill reviewer hash, attestations, or timestamp; the CLI owns those.

## Private identity files

Each reviewer supplies one stable organizational identity to the coordinator in
a private file outside Git:

```text
.private/quality/reviewers/<slot>/identity.txt
```

The coordinator creates one campaign-wide private pepper and uses the same file
for reviewer A, reviewer B, and any adjudicator:

```text
.private/quality/reviewers/identity-pepper.bin
```

The pepper must contain at least 32 CSPRNG bytes. Do not let each reviewer use a
different pepper: aggregation rejects different identity domains, and changing
peppers would defeat duplicate-person detection. Raw identity and pepper never
enter the published submission. The submission stores only HMAC-SHA256(identity)
and SHA-256(pepper) as a non-secret domain identifier.

## Submit

Run separately for reviewer A and reviewer B:

```powershell
.\.venv\Scripts\python.exe -m scripts.submit_quality_review `
  --packet-dir data\v2\quality_review\r2-s8-calibration-v3 `
  --completed-template <reviewer-completed.csv> `
  --reviewer-id-file <private-identity.txt> `
  --identity-pepper-file .private\quality\reviewers\identity-pepper.bin `
  --out-dir .private\quality\submissions `
  --attest-blind `
  --attest-independent
```

Do not use `--fixture-only` for real human work.

This procedure detects duplicate normalized IDs inside one campaign. The
operator must still verify that the two identity files belong to two real
people; cryptography cannot prove human independence by itself.

## Aggregate

```powershell
.\.venv\Scripts\python.exe -m scripts.aggregate_quality_reviews `
  --evidence-id r2-s8-human-pilot-v1 `
  --packet-dir data\v2\quality_review\r2-s8-calibration-v3 `
  --submission <reviewer-a-submission.json> `
  --submission <reviewer-b-submission.json> `
  --out-dir .private\quality\evidence
```

If the result is `needs_adjudication`, a third person creates a strict
`QualityReviewAdjudication` JSON bound to the exact packet and submission
hashes, then reruns with `--adjudication`.

## Interpret

- `CALIBRATION_COMPLETE`: dev rubric pilot completed; revise ambiguous rubric
  rules using disagreements, but do not claim held-out quality.
- `INCONCLUSIVE`: unresolved disagreement or insufficient reliability.
- `FIXTURE_ONLY`: software test data, never a project quality result.

The final held-out run is a separately frozen 60-case independent population.
Pilot cases and labels must not be reused as final acceptance evidence.
Held-out acceptance currently requires the complete frozen `all_cases`
population and a candidate pool bound to at least two retrieval run manifests.

The current packet is reference-guided: expected response mode and reference
material are visible. It is blind to model identity and machine verdicts, not
blind to the expected outcome.
