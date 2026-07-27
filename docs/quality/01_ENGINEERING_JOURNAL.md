# R2-S8 Engineering Journal

## QEV-001 - G0 baseline audit

Status: COMPLETE

Observed:

- `app/evaluation/human_review.py` selects up to 50 cases, prioritizes machine
  failures, and appends eight blank free-form judgement fields.
- `scripts/generate_human_review_v2.py` combines dev and test into one
  regression sheet.
- `app/evaluation/writer.py` hashes the CSV as a run artifact, but the review
  labels themselves have no schema, ingestion, consensus, or agreement logic.
- repository documentation correctly records all 400 historical judgement
  cells as blank and human semantic review as pending.

Decision:

- preserve the old exporter for backward compatibility;
- create a separate strict quality-evidence module rather than silently
  changing the semantics of the old CSV;
- treat existing public dev/test data as calibration/regression evidence, not
  as a new independent holdout;
- fail closed when human evidence is absent.

Result:

- R2-S8 G0 contract frozen;
- no human or semantic-quality claim changed;
- first implementation target is an immutable model/verdict-blinded,
  reference-guided packet.

## QEV-002 - G1 immutable reviewer packet

Status: COMPLETE

RED:

- `tests/evaluation/test_quality_review.py` failed because
  `app.evaluation.quality_review` did not exist.

GREEN:

- added strict packet, source, evidence, item, threshold, and manifest models;
- added atomic no-overwrite publication;
- added a verifier that reparses every JSONL item, validates evidence-content
  hashes, checks the exact file set, verifies all artifact hashes, and validates
  the blank submission template;
- reviewer-visible items omit source case ID, model identity, model variant,
  machine pass/fail, and machine failure stage;
- packet claim status is fixed to `NOT_RUN`.

## QEV-003 - G2 strict human submission

Status: COMPLETE

RED:

- the first submission test could not import a submission schema.

GREEN:

- added pseudonymous reviewer ID hashes, timezone-aware timestamps, blind and
  independence attestations, strict enum labels, applicability checks, complete
  item coverage, and atomic no-overwrite submission publication;
- an answered item must grade factuality, completeness, and citations;
- refusal items must grade refusal appropriateness;
- access safety is always applicable;
- fixture submissions are permanently marked `fixture_only`.

## QEV-004 - G3 disagreement and adjudication

Status: COMPLETE

Implemented:

- exactly two distinct reviewers in schema v1;
- preservation of both pre-adjudication label sets;
- raw agreement and Cohen's kappa;
- unresolved disagreements force `INCONCLUSIVE`;
- a third adjudicator must be distinct from both reviewers and bind the exact
  two submission hashes;
- adjudication resolves every disagreement exactly once.

## QEV-005 - Human retrieval relevance

Status: COMPLETE (tooling)

The independent audit found that the expanded deterministic retrieval suite was
`56/56` while mean `precision@5` was only `0.2461538462` and mean invalid extras
at five was `3.6153846154`. The old pass criterion therefore established recall,
authority, and ACL behavior, but not a clean relevant candidate set.

The review schema now requires one ordinal relevance grade for every returned
document. Aggregation reports:

- retrieval label count;
- reviewer raw relevance agreement;
- ordinal weighted kappa;
- human relevance precision@5;
- human nDCG@5;
- uncertain relevance count.

## QEV-006 - Windows source/display hash split

Status: RESOLVED

Failure:

- the first CLI fixture hashed raw CRLF file bytes, then `read_text()` supplied
  LF-normalized content to the evidence model;
- the shared strict model also stripped trailing whitespace before validation.

Resolution:

- `source_artifact_sha256` binds original file bytes;
- `content_sha256` binds exactly the normalized text shown to reviewers;
- evidence content uses a strict model that does not mutate whitespace.

This preserves both provenance claims instead of disabling hash validation.

## QEV-007 - Real calibration packet

Status: COMPLETE (blank packet only)

Commands produced:

- private deterministic source run:
  `r2-s8-calibration-source-v1`;
- tracked reviewer packet:
  `data/v2/quality_review/r2-s8-calibration-v3`;
- private control map and blinding key under `.private/quality/`.

Verified packet:

- 12 dev-only stratified cases;
- 8 answered, 2 not-found, 2 permission;
- 37 returned evidence documents;
- 37 candidate evidence documents;
- 10 reference evidence documents;
- source dev SHA-256
  `92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd`;
- source commit `f081ccbb284feba6af30f38024e87d1c7b273a9d`;
- `population_kind=public_synthetic`;
- `independence_status=not_independent`;
- `claim_status=NOT_RUN`.

No human label was generated or inferred.

The earlier v2 blank packet was moved to the ignored private superseded area
after candidate-pool review showed that ranking only within returned documents
could hide missed relevant candidates. V3 adds a returned-plus-reference
calibration candidate pool. A final held-out packet must use
`pooled_variants`, not this calibration-only pool.

V3's 37 candidate documents equal its 37 returned documents because every
reference document in this small dev sample was already retrieved. That is
acceptable for annotation-flow calibration, but it cannot estimate miss-aware
recall. The held-out gate therefore rejects this pool strategy.

## QEV-008 - Weak blinding-key failure

Status: RESOLVED

Failure:

- the local PowerShell runtime did not support static
  `RandomNumberGenerator.Fill`;
- PowerShell continued after the non-terminating error and wrote 32 zero bytes;
- the first generated packet therefore had predictable opaque IDs.

Resolution:

- moved the rejected v1 reviewer/control artifacts under
  `.private/quality/failed_packets`;
- regenerated v2 with `RandomNumberGenerator.Create().GetBytes(...)`;
- added a regression test and pre-publication rejection for obviously weak
  blinding keys.

## QEV-009 - Recomputable evidence bundle

Status: COMPLETE (tooling)

The evidence publisher now packages the reviewer packet, two immutable
submissions, optional adjudication, and summary under one append-only directory.
Its verifier checks every recursive artifact hash, reloads all schemas,
recomputes all metrics and the claim decision, and rejects a changed summary.

Focused result at this checkpoint: `10 passed`, 3 unrelated SWIG deprecation
warnings.

## QEV-010 - G4 LLM-judge calibration contract

Status: COMPLETE (tooling); real calibration NOT RUN

Implemented:

- a separate `QualityJudgeRun` schema rather than reusing human identity fields;
- local-only provider contract (`ollama_local`);
- exact judge model digest, model family, answer-model family, prompt hash, and
  inference-config hash;
- at least three repeated trial indices for calibration;
- retrieved-content-is-data attestation;
- `security_gate_authority=none` and `release_authority=false`;
- agreement with resolved human consensus, Cohen's kappa, overall-answer
  agreement, cross-trial stability, false-pass count, and security-false-pass
  count;
- same-family correlation risk and fail-closed status;
- immutable calibration publication and verifier-side recomputation.

RED/GREEN:

- the initial test failed because `app.evaluation.quality_judge` did not exist;
- after implementation, three perfect fixture trials returned `FIXTURE_ONLY`;
- a single non-fixture trial with perfect labels returned `INCONCLUSIVE`
  because trial count was below three and stability was undefined.

One implementation error placed an exported name outside `__all__`, causing an
`IndentationError` during test collection. Moving it into the list restored
collection; this was a code-edit error, not a model/evaluation failure.

## QEV-011 - Candidate-pool semantic correction

Status: RESOLVED

The first aggregation design graded only returned documents. That could report
perfect nDCG when the evaluated ranking returned one relevant document but
missed another relevant document entirely. The correction:

- adds an explicit `retrieval_candidate_evidence` pool and pool strategy;
- requires reviewers to grade every candidate;
- computes ideal DCG over the full candidate pool;
- reports human relevance recall@5;
- requires `pooled_variants` for a held-out decision;
- adds a regression where one of two relevant candidates is missed, producing
  precision@5 `1.0`, recall@5 `0.5`, and nDCG@5 about `0.6131`.

The v2 packet was superseded instead of silently overwritten. V3 was generated
and verified against the corrected schema.

## QEV-012 - Apparent Chinese mojibake diagnosis

Status: RESOLVED (display-only)

`Get-Content` without an explicit encoding displayed the UTF-8 Chinese packet
as mojibake in the current PowerShell session. Direct Python UTF-8 parsing and
Unicode-escaped inspection showed the stored question and answer were correct;
`Get-Content -Encoding utf8` also displayed them correctly. No artifact was
rewritten. This check prevented replacing a valid hash-bound packet in response
to a terminal rendering problem.

Current focused quality result after the candidate-pool correction:
`13 passed`, 3 unrelated SWIG deprecation warnings.

## QEV-013 - CI and broader regression

Status: COMPLETE

- CI now runs `python -m scripts.verify_quality_review_packet`;
- it requires the tracked packet to remain `NOT_RUN`, `public_synthetic`, and
  `not_independent`;
- all evaluation tests: `999 passed, 16 skipped`;
- full repository tests: `2379 passed, 30 skipped`;
- public audit: `745 candidates, 0 findings`;
- quality-focused tests after hardening: 20 tests across packet, submission, evidence,
  CLI, and judge calibration behavior.

## QEV-014 - G5 execution boundary

Status: READY FOR TWO HUMANS; NOT RUN

All automatable preparation is complete. G5 requires two actual independent
reviewers. Codex cannot satisfy this by generating two identities or using an
LLM as either reviewer. The exact operating procedure is frozen in
`docs/quality/05_REVIEWER_RUNBOOK.md`.

## QEV-015 - Independent hardening review

Status: COMPLETE; G5 remains NOT RUN

A separate read-only reviewer reported `6 P1 / 3 P2` validity risks after the
first all-green implementation. The main collaborator reproduced each finding
against the public schemas before deciding whether to fix or document it.

| Finding | Resolution |
|---|---|
| Same person can change salts and obtain two hashes | Replaced per-reviewer salts with one campaign identity domain and HMAC pseudonyms; mixed domains fail aggregation |
| Expected response mode is visible | Retained as an explicit reference-guided rubric decision; documentation now forbids calling it verdict-blind |
| `pooled_variants` is self-declared | Requires at least two sorted unique run-manifest hashes including the evaluated source run; held-out packet creation rejects non-pooled items |
| One uncertain candidate removes a query | Computes conservative metrics instead: returned uncertain=0, candidate-pool uncertain=2 |
| Heterogeneous pooled kappa | Uses dimension-macro raw agreement, overall-answer Cohen's kappa, and retrieval weighted kappa separately |
| Unweighted stratified population estimate | Held-out acceptance now requires `all_cases`; stratified sampling remains calibration-only |
| Same source ID can carry different content | Cross-list `QualityEvidence` equality is required |
| Packet succeeds but control-map publication fails | Exact packet recovery and idempotent exact control publication; mismatches fail closed |
| Judge stability uses first trial as anchor | Uses all unordered trial pairs; judge kappa is overall-answer only and agreement is dimension-macro |

Additional contract drift found by the main collaborator:

- packet candidates allowed 40 entries while reviewer labels allowed only 20;
- a 21-candidate public-interface test failed before the shared maximum was
  introduced;
- the fixed submission can now label all 40 allowed candidates.

RED/GREEN evidence added for candidate capacity, fake pooled provenance,
conflicting source content, mixed identity domains, selective uncertainty,
unweighted stratified held-out claims, packet/control failure recovery,
same-family judge correlation, security false-pass counting, and all-pairs
judge stability.

The hardened focused suite is `20 passed`; the broader evaluation suite is
`999 passed / 16 skipped`; the full repository is `2379 passed / 30 skipped`;
the public audit is `745 candidates / 0 findings`.

Ruff was probed as an additional lint gate but is not installed in the project
virtual environment (`No module named ruff`). No lint result is claimed. The
executed static/runtime gates are compileall, pip check, diff check, packet
verification, public audit, focused tests, evaluation tests, and full pytest.

## QEV-016 - Clean-checkout packet hash failure

Status: RESOLVED

GitHub Actions run `30234801613` failed on both Ubuntu and Windows in
`Verify frozen quality-review calibration packet`. A clean `git archive`
reproduction failed with `artifact hash mismatch: submission_template.csv`.
The original Windows packet builder used the `csv` module's platform-default
CRLF terminator, then hashed those bytes. `.gitattributes` normalized the
committed blob to LF, so the working tree passed while every fresh checkout
correctly rejected the changed bytes.

Resolution:

- pin `csv.DictWriter(lineterminator="\n")`;
- assert at byte level that generated templates contain no CRLF;
- keep v3 classified as a rejected preflight artifact rather than silently
  representing it as valid;
- publish immutable replacement `r2-s8-calibration-v4` with a separate private
  control map;
- point CI, reviewer runbook, traceability, status, and handoff records to v4;
- verify the exact committed archive before the replacement push.

This failure demonstrates why a clean-checkout gate is distinct from running
tests in the producer's working tree.

Post-fix verification:

- quality-focused tests: `20 passed`;
- exact Git index export verified packet v4 as `NOT_RUN`;
- full repository: `2379 passed / 30 skipped`;
- public audit: `751 candidates / 0 findings`.

## QEV-017 - CI clean-checkout dependency audit

Status: RESOLVED

GitHub Actions run `30235395861` proved that fixing the packet hash was
necessary but not sufficient. Both jobs passed packet v4 verification, then
the deterministic suite failed. A Git-index export reproduced 32 Windows
failures without using GitHub logs.

Root causes:

- formal G10 raw runs `02` through `04` were referenced by append-only
  experiment records and tests but hidden by a blanket ignore rule;
- six synthetic dataset metadata files were declared by public package
  manifests but hidden because their source-relative package path contained
  `.private`;
- one registration test passed locally only because this session redirected
  pytest TEMP below the repository root;
- Linux `os.open(..., dir_fd=...)` and Windows directory-move retry semantics
  were not represented by the original monkeypatches;
- traceability validation wrapped a precise symlink error in a generic message.

Resolution:

- track only immutable formal G10 runs `02`, `03`, and `04`; all other local
  lifecycle runs remain ignored;
- unignore and audit-allow exactly six manifest-bound synthetic metadata files,
  while an unexpected sibling remains forbidden and package verification
  rejects undeclared files;
- make the registration test bind its own temporary repository root;
- model `dir_fd` in the file-swap test and run sharing-denial retry assertions
  only on Windows;
- retain the lower-level symlink diagnosis in the public validation error;
- export the exact Git index and rerun the formerly failing scope and full suite.

Clean-index evidence:

- formerly failing/public scope: `138 passed / 1 skipped`;
- full repository: `2381 passed / 29 skipped`;
- public audit including formal evidence: `892 candidates / 0 findings`.

## QEV-018 - Linux no-replace publication semantics

Status: RESOLVED

GitHub Actions run `30236134185` reduced Ubuntu failures to four. Three tests
simulated Windows sharing-denial retries but were not platform-scoped. The
fourth exposed production behavior: POSIX `os.rename(source, destination)` may
replace an existing empty destination directory, unlike the no-replace behavior
observed on Windows.

Resolution:

- Windows sharing-denial retry tests now run only on Windows;
- Linux uses `renameat2(..., RENAME_NOREPLACE)` through libc, so the kernel
  performs the collision check atomically and returns `EEXIST`;
- platforms without `renameat2` use an explicit preflight collision check
  before `os.rename` as a compatibility fallback;
- the collision error remains `FileExistsError`, preserving all callers'
  immutable publication contract.

The affected Windows scope passes `54 passed`. Ubuntu CI is the execution proof
for the Linux syscall branch because this development host is Windows.
