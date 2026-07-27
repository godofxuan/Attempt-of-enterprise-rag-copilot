# R2-S8 Independent Reviewer Runbook

## Current boundary

This runbook executes the 12-case development calibration pilot in
`data/v2/quality_review/r2-s8-calibration-v4`. It is not the final 60-case
independent held-out acceptance.

Two different people are required. Codex, an LLM judge, or one person using two
identities cannot satisfy this gate.

## Initialize once

From a normal terminal running as the intended Windows account, initialize the
campaign:

```powershell
.\.venv\Scripts\python.exe -m scripts.init_quality_review_campaign `
  --campaign-id r2-s8-human-pilot-v1
```

Do not run this command through Codex or another delegated Windows account.
The initializer binds the private coordinator ACL to the effective operating
system token and rejects a token/host-account mismatch. It publishes with
no-overwrite semantics, verifies every hash, and leaves the campaign at
`NOT_RUN` with zero judgements.

Verify readiness:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_quality_review_campaign `
  --campaign-dir .private\quality\campaigns\r2-s8-human-pilot-v1
```

The operator gives each reviewer only their matching directory:

```text
.private/quality/campaigns/r2-s8-human-pilot-v1/reviewer-kits/reviewer-a/
.private/quality/campaigns/r2-s8-human-pilot-v1/reviewer-kits/reviewer-b/
```

Do not give reviewers:

- `coordinator/`, `inbox/`, `submissions/`, or `evidence/`;
- source case IDs;
- source run failures;
- machine pass/fail labels;
- model identity;
- the other reviewer's completed template.

Reviewers should not inspect the repository or evaluation dataset while
grading. The reference answer and authorized evidence inside the packet are the
grading reference.

## Reviewer task

Each reviewer independently fills their own `completed_template.csv`.

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

## Private coordinator files

Each reviewer supplies one stable organizational identity to the coordinator
through a private channel. The coordinator writes them to the two pre-created,
zero-length placeholders:

```text
.private/quality/campaigns/r2-s8-human-pilot-v1/coordinator/reviewer-a.identity.txt
.private/quality/campaigns/r2-s8-human-pilot-v1/coordinator/reviewer-b.identity.txt
```

The initializer already created the one campaign-wide private pepper:

```text
.private/quality/campaigns/r2-s8-human-pilot-v1/coordinator/identity-pepper.bin
```

Do not replace it or create per-reviewer peppers. Aggregation rejects different
identity domains, and changing peppers would defeat duplicate-person detection.
Raw identity and pepper never enter reviewer kits or published submissions.
The submission stores only HMAC-SHA256(identity) and SHA-256(pepper) as a
non-secret domain identifier.

## Submit

Save the returned reviewer CSVs as `inbox/reviewer-a.csv` and
`inbox/reviewer-b.csv`. Exact commands for both slots are generated in:

```text
.private/quality/campaigns/r2-s8-human-pilot-v1/coordinator/COMMANDS.md
```

Do not use `--fixture-only` for real human work.

This procedure detects duplicate normalized IDs inside one campaign. The
operator must still verify that the two identity files belong to two real
people; cryptography cannot prove human independence by itself.

## Aggregate

```powershell
$reviewerAFiles = @(Get-ChildItem `
  -LiteralPath .private\quality\campaigns\r2-s8-human-pilot-v1\submissions\reviewer-a `
  -Filter submission.json -Recurse -File)
$reviewerBFiles = @(Get-ChildItem `
  -LiteralPath .private\quality\campaigns\r2-s8-human-pilot-v1\submissions\reviewer-b `
  -Filter submission.json -Recurse -File)
if ($reviewerAFiles.Count -ne 1 -or $reviewerBFiles.Count -ne 1) {
  throw "Expected exactly one immutable submission for each reviewer"
}
$reviewerA = $reviewerAFiles[0].FullName
$reviewerB = $reviewerBFiles[0].FullName

.\.venv\Scripts\python.exe -m scripts.aggregate_quality_reviews `
  --evidence-id r2-s8-human-pilot-v1 `
  --packet-dir data\v2\quality_review\r2-s8-calibration-v4 `
  --submission $reviewerA `
  --submission $reviewerB `
  --out-dir .private\quality\campaigns\r2-s8-human-pilot-v1\evidence
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
