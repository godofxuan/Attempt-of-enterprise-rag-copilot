# R2-S3 Exposure-Aware Ablation Engineering Journal

Status: `COMPLETE` for the approved measurement-only development scope.

This journal explains why R2-S3 exists, how the implementation was hardened,
what the evidence says, and where the result stops. It contains no private
source text, canaries, questions, or raw unit identifiers.

## 1. Starting Problem: What Did `13/28` Mean?

The R2-S2 S2-1 live development run produced two numbers that initially looked
uncomfortable together:

```text
Guard reached and quarantined: 15/15
all labeled units quarantined:  15/28
unreached labeled units:        13/28
```

A beginner might call the remaining 13 detector misses. That would be wrong.
The Guard cannot miss content it never receives. Before changing a detector or
scanning more documents, the team needed to locate each labeled unit in the
actual runtime data flow:

```text
candidate pool -> ranking -> selection/navigation -> Guard -> downstream use
```

R2-S3 was created to separate those stages without changing the system being
measured.

## 2. Rank-2 Discovery

Read-only inspection found that all 13 unreached units were attached to the
persisted runtime rank-2 search candidate. In every affected case:

- a clean candidate occupied rank 1;
- `top_k=1` selected that clean candidate;
- the attack-bearing rank-2 candidate remained inside `candidate_k=4`;
- the runtime path answered after search rather than navigating to rank 2;
- downstream exposure signals were `0/13`;
- legitimate task success was preserved.

This is a ranking/consumption observation, not detector evidence. The full
rank-2 stratum contains 16 units: three were already reached through existing
bounded admission behavior and 13 were not reached. All rank-1, rank-3,
rank-4, and recorded-open units were reached.

## 3. Alternatives Considered

### Pre-scan every candidate

Rejected for this stage. It would make the all-labeled quarantine numerator
larger by scanning content that the request never consumes. That also adds
Guard calls, scanned characters, latency, and false-positive opportunities.
There was no observed downstream bypass to offset those costs.

### Raise `top_k` from 1 to 2

Rejected. This changes retrieval selection, model context, answer evidence,
and runtime cost at the same time. It could create exposure absent from the
baseline and would not isolate the security variable.

### Infer reach from category or authored rank

Rejected. Historical candidate ordering differed between embedding regimes,
and split payloads can be reached by adjacent-window scans even when their
candidate rank is greater than 1. Only persisted runtime rank and actual scan
provenance are valid.

### Scan source text with a new static detector

Rejected. R2-S3 had to replay the production admission path and bind the exact
Guard and source live evaluator hashes. The accepted private run separately
binds the exposure evaluator that produced it. A parallel scanner would measure
different behavior.

### Measurement-only deterministic replay

Selected. It preserves the source run and production behavior, attributes
actual Guard aggregates to content-free unit rows, and estimates bounded depths
`1/2/4` without executing a new production path.

## 4. Specification Review: Actual Versus Replay Attribution

An important issue was found before implementation: the live source records
actual reached/quarantined counts per case, but not the labeled unit identity
on every scan event. It would be unsupported to relabel reconstructed unit
states as direct live observations.

The design therefore created a strict separation:

- `live_case_guard_*` is the actual immutable source aggregate;
- `replay_guard_*` is unit attribution reconstructed through production
  admission and Guard scan provenance;
- replay must equal live per case and globally or the evidence is invalid;
- downstream fields remain `case_*` because they cannot identify which unit
  caused a case-level signal.

The provenance identities are also separate: the frozen source live evaluator
is `app/evaluation/indirect_injection_live_runner.py` at SHA-256
`a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958`.
The original `-01` exposure evaluator was
`app/evaluation/indirect_injection_exposure.py` at SHA-256
`e043f198c669708d1da2acd5afeb1503bd04f2849d0488ea845d120ee1842bfb`;
the first final-review fix wave produced the superseded `-02` evaluator at
`86d87d018948f1276a8c9ce3f7105fb7cd90f7ce78bc98aeae1e79bba6699b33`.
The fixed-HEAD re-review then added source-bound publication and exact source-row
snapshot checks. The current accepted `-04` evaluator SHA-256 is
`d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88`;
the preceding `-03` evaluator is superseded immutable history.

This distinction later prevented a second attribution error in the private
writer: `failures.csv` originally repeated a case-level exposure once per unit.
Review changed it to one case-scoped row with no unit attribution.

## 5. Material RED/GREEN History

Tests were written or strengthened before each production repair. Counts below
are the focused evidence recorded in Tasks 1-7; broader suites followed each
wave.

| Wave | RED evidence | GREEN repair and result |
|---|---|---|
| Task 1 source admission | Collection failed because the exposure module/API did not exist. | Added strict source models, exact run/hash/pair/protocol admission, and real source verification: `10 passed`. |
| Task 1 evidence-boundary review | `7 failed, 18 passed`: raw filesystem/verifier errors escaped and boolean-like metadata was accepted. | Normalized bounded evidence errors, added strict arm metadata, and covered source integrity boundaries: `25 passed`. |
| Task 1 boolean arm position | `1 failed`: Python equality let `True` satisfy a `Literal[1,2]` contract. | Replaced it with strict bounded integer validation: complete module `26 passed`. |
| Task 2 location mapping | `12 failed`: mapping API was absent. | Added exact fixture-to-runtime location mapping across search metadata and open: `12 passed`. |
| Task 2 contradictory location state | `16 failed`: invalid operation/surface/rank combinations validated. | Added strict cross-field location invariants: focused `28 passed`, module `55 passed`. |
| Task 3 deterministic replay | `6 failed`: replay contracts/API were absent. | Reconstructed persisted candidate order and production admission; final replay selection `6 passed`. An intermediate `3 failed, 3 passed` exposed test selectors tied to a private ordering, so tests were changed to assert persisted properties rather than hidden ordering. |
| Task 3 review hardening | `12 failed, 7 passed`: sanitized-parent selection, state invariants, source live evaluator binding, open ambiguity, scan accounting, invalid provenance, and duplicate quarantine summaries were not all rejected. | Bound selected evidence to sanitized production outputs, exact source live evaluator/Guard bytes, scan counts/chars, and one-to-one provenance: `20 passed`. A stronger parent-provenance test separately failed once before the final fixture-binding repair. |
| Task 3 open metadata repair | Source replay initially added 17 characters by reconstructing a document open with a section path production does not emit. | Matched `DocumentNavigator` document-open metadata exactly; source audit became `36` cases, `90` scans, `8768` chars, `15` reached, `15` quarantined, `0` selected. |
| Task 4 benign denominator | `1 failed`: benign quarantine incorrectly used 12 benign cases rather than all 32 benign units. | Derived benign units from admitted source rows: `1 passed`, final metric `0/32`. |
| Task 4 decision binding | `5 failed`: contradictory decision/summary/finding combinations validated. | Recomputed exact decision precedence at the strict result boundary: `5 passed`. |
| Task 4 counterfactual row binding | `3 failed`: forged search numerators/denominators and a double-counted total union validated. | Recomputed rank-based search reach and the per-unit actual-or-counterfactual union. |
| Task 4 conditional invariants | `2 failed`: conditional quarantine could disagree with live quarantine and attack success could exceed downstream exposure. | Bound both numerators to their source predicates: `2 passed`. |
| Task 4 stratum binding | `12 failed`: category, surface, rank, and tag depth metrics could be coherently forged. | Rebuilt every stratum from rows, including zero-search `open/not_applicable` groups: `12 passed`; module `117 passed`. |
| Task 5 private writer | Collection failed because writer/verifier did not exist. | Added canonical seven-file immutable run, strict recomputation, checksums, and no-replace publication: `22 passed, 1 platform skip`. |
| Task 5 CLIs | Collection failed because evaluator/verifier CLIs did not exist. | Added thin operator wrappers and canonical exit behavior: `6 passed`. |
| Task 5 review: forbidden strings | JSON-special and non-ASCII forbidden values survived raw-byte-only scanning. | Recursively scanned decoded JSON/JSONL/CSV/text values and retained final-byte scans. |
| Task 5 review: final handoff race | A destination created after precheck could be replaced by ordinary POSIX directory rename. | Added Windows `MoveFileExW` and Linux `renameat2(RENAME_NOREPLACE)` fail-closed publication with cleanup. |
| Task 5 review: replay/live redistribution | A coherent two-case count redistribution preserved global totals and verified. | Required replay/live equality for each case before global aggregation. |
| Task 5 review: failure attribution | One risky case with two units produced two unsupported unit-scoped failures. | Emitted one case-scoped row and separate bounded tool-path findings. Focused writer result: `26 passed, 1 platform skip`. |
| Task 5 re-review race test | The first regression raced a non-empty target, which ordinary rename already rejects. | Raced an empty destination and asserted it remained empty with staging removed; targeted and full writer tests passed. |
| Task 6 public package | Collection failed because exporter/verifier modules did not exist; fixture registration then caused ten setup errors. | Added the exact eight-file content-free package and standalone verifier; corrected fixture registration and two test assumptions: `16 passed`. |
| Task 6 hardening wave 1 | `14 failed, 18 passed, 1 skip`: coherent verifier replacement, non-exact JSON primitives, a test-only tag, incomplete metric definitions, path variants, verifier-authentication text, and final symlink handling were exposed. | Pinned packaged verifier bytes in trusted verification, enforced exact JSON types/schema, expanded definitions, hardened path/target checks, and documented verifier trust: `39 passed, 1 skip`. |
| Task 6 hardening wave 2 | `2 failed` plus targeted failures: colon-adjacent POSIX paths escaped and 12 aggregate/witness definitions were absent; clean-task applicability used the wrong denominator. | Unified path matching, expanded catalog `23 -> 35`, and corrected clean-case semantics: `41 passed, 1 skip`. |
| Task 6 hardening wave 3 | `2 + 2 + 1` failures: doubled/tripled slash-root paths escaped and projected row fields lacked definitions/classification. | Added allowlisted network-URI elision, unified remaining path checks, and expanded exact definitions `35 -> 62`: `46 passed, 1 skip`. |
| Task 6 hardening wave 4 | Two malformed-authority cases failed in both scan paths; expanded RED was `4 + 4` for empty/userinfo-only hosts, malformed IPv6, and invalid ports. | Forced URL parsing, hostname, and port evaluation before elision and failed closed on every parsing error: `54 passed, 1 skip`. |
| Task 6 hardening wave 5 | `4 + 4` failures: non-empty but invalid DNS authorities were elided. | Added standard-library DNS/IP/IDNA, userinfo, and port grammar while preserving seven valid authority controls: `68 passed, 1 skip`. |
| Task 6 hardening wave 6 | `5 failed` valid rooted-DNS exports plus `1 failed` valid maximum wire-length boundary. | Allowed exactly one trailing DNS root marker after IDNA conversion and enforced presentation/wire limits: `81 passed, 1 skip`. Final independent review approved spec and code/security quality. |
| Task 7 private leak gate | `2 failed, 1 passed`: private exposure root was neither ignored nor fully audited. | Added scoped ignore, forbidden-prefix, and private-runtime-reference rules without rejecting the public package: `3 passed`. |
| Task 8 status-document contract | Fresh focused verification first returned `2 failed, 245 passed, 2 skipped`: the synchronized root status header had removed the required historical `2026-07-19` marker and `V1-V5` stage token. | Preserved the historical update marker with an explicit R2-S3 addendum date and restored the canonical stage token without changing claims. Targeted tests returned `2 passed`; the complete focused gate returned `247 passed, 2 skipped`. |

The skipped Task 5/6 tests are platform-dependent symlink/junction variants
unavailable on this host. They are platform-gated, not silently counted as
passes.

## 6. File-by-File Code Map

| File | Responsibility |
|---|---|
| `.gitignore` | Keeps accepted private `exposure_runs/` artifacts untracked. |
| `app/evaluation/indirect_injection_exposure.py` | Strict source admission, unit location mapping, production-path replay, counterfactual metrics/strata, and decision policy. |
| `app/evaluation/indirect_injection_exposure_writer.py` | Canonical immutable private writer/verifier, recomputation, forbidden-content scans, checksums, and atomic no-replace publication. |
| `app/evaluation/indirect_injection_exposure_public.py` | Verifies the private run, projects allowlisted content-free fields, scans paths/private content, and atomically exports the public package. |
| `app/evaluation/indirect_injection_exposure_public_verifier.py` | Standard-library package verifier that validates exact bytes/schema, recomputes metrics/strata/decision, and applies trusted-verifier pinning in repository use. |
| `scripts/eval_indirect_injection_exposure.py` | One-shot private evaluator CLI with exact source-manifest binding. |
| `scripts/verify_indirect_injection_exposure.py` | Private-run verification CLI. |
| `scripts/export_indirect_injection_exposure_public.py` | Public export CLI; loads forbidden source values privately and requires an externally supplied private manifest hash. |
| `scripts/verify_indirect_injection_exposure_public.py` | Trusted repository public verification CLI. |
| `scripts/audit_public_repo.py` | Rejects private exposure paths/references from public Git candidates. |
| `tests/evaluation/test_indirect_injection_exposure.py` | Source, mapping, replay, invariants, counterfactuals, strata, and decision regressions. |
| `tests/evaluation/test_indirect_injection_exposure_writer.py` | Private artifact schema, tamper, content scan, atomic handoff, and CLI-adjacent contracts. |
| `tests/evaluation/test_indirect_injection_exposure_cli.py` | Evaluator/verifier CLI success and failure behavior on generated local evidence. |
| `tests/evaluation/test_indirect_injection_exposure_public.py` | Projection privacy, exact package, standalone verification, tamper, type/schema, path, URI, DNS, and trust-boundary regressions. |
| `tests/test_public_repository.py` | Git/public leak prevention for private exposure runs while allowing the eight-file public package. |
| `data/v2/public/r2_s3_exposure/README.md` | Public identity, verification instructions, and trust/limitation language. |
| `data/v2/public/r2_s3_exposure/manifest.redacted.json` | Content-free package/source identities, counts, hashes, limitations, and decision. |
| `data/v2/public/r2_s3_exposure/summary.json` | Recomputable aggregate metrics, costs, strata, witness, and decision. |
| `data/v2/public/r2_s3_exposure/per_unit.redacted.jsonl` | 28 fingerprinted allowlisted attack-unit observations with no private IDs/text. |
| `data/v2/public/r2_s3_exposure/metric_definitions.json` | Exact versioned definitions for aggregate and row fields. |
| `data/v2/public/r2_s3_exposure/source_run.sha256` | Binds the public package to the accepted private exposure manifest hash. |
| `data/v2/public/r2_s3_exposure/checksums.sha256` | Internal checksums for all package files except itself. |
| `data/v2/public/r2_s3_exposure/verify.py` | Copied standard-library verifier for isolated eight-file execution. |

Production files under `app/security`, `app/retrieval`, and `app/agent` were
not modified by R2-S3. Replay imports their existing admission behavior for
measurement; it does not replace runtime behavior.

## 7. Successful Results

- Exact immutable source admission and replay/live equality succeeded.
- All 13 unreached units were explained by persisted rank 2, not by a Guard
  false-negative observation.
- Those 13 affected cases had `0/13` observed downstream exposure and `0/13`
  attack success while clean task success was `12/12` overall.
- Actual reached units were quarantined `15/15`; benign quarantine was `0/32`.
- Diagnostic depth 2 covers `22/26` search units and total `28/28`; depth 4
  covers `26/26` search units and total `28/28`.
- Private and public artifacts are independently recomputed and content-free;
  the accepted public package has exactly eight files and 28 rows.
- Independent reviews closed all material Task 4-7 findings before acceptance.

## 8. Imperfect Results and Residual Risk

- Actual all-labeled live quarantine remains `15/28`; counterfactual `28/28`
  is not executed behavior.
- Depth 2 would add 29 scans and 3845 input characters; depth 4 would add 33
  scans and 4200 characters. Wall-clock latency and false-positive impact were
  not measured.
- The evidence uses a visible synthetic dev cohort and one fixed local
  BGE-M3/Qwen configuration.
- The existing narrow raw-canary/forbidden-action signals do not measure broad
  semantic instruction following.
- An isolated package proves internal consistency, not its own verifier
  authenticity or cryptographic projection provenance.
- Standard-library IDNA behavior is frozen rather than IDNA 2008/UTS #46.
- Windows symlink-permission tests remain platform-skipped here.
- Independent holdout, semantic judge calibration, cross-model replication,
  multimodal attacks, manual red team, and production traffic are `NOT RUN`.

## 9. Production-Change Admission Decision

The derived decision is `NO_CURRENT_BYPASS_OBSERVED`.

No production prefilter, `top_k`, `candidate_k`, ranking, navigation, Guard,
prompt, retrieval, or Agent change is admitted. The deciding evidence is not
the attractive counterfactual coverage number; it is that every case containing
an unreached unit had zero observed downstream exposure, every consumed path
had Guard evidence, replay equaled live, and there was no concrete unguarded
future path finding.

A future runtime experiment requires a new approved design, a measured bypass
or reachable unguarded path, and explicit latency, utility, false-positive, and
rollback gates. This decision is not a release pass.

## 10. Next Independent and Owner Boundaries

The next security-validity step belongs to independent reviewers, not the Guard
developer:

1. An independent reviewer authors the raw holdout package under the frozen
   R2-S2 protocol.
2. A second reviewer verifies coverage, separation attestations, hashes, and
   the clean Git/code baseline.
3. Only after freeze may a one-shot holdout model run occur.
4. Blind double review, agreement/adjudication, semantic judge calibration, and
   a separately approved cross-model matrix follow without tuning on holdout.

Those steps are `NOT RUN`. The 50-row human semantic review and owner code/oral
acceptance are also `NOT RUN`; automated engineering work cannot sign them.

## 11. Interview Questions and Concrete Answers

### 1. Why are `15/15` and `15/28` not contradictory?

`15/15` conditions on the 15 units that reached Guard. `15/28` uses all 28
labeled units. The remaining 13 never reached Guard, so they affect end-to-end
coverage but not conditional detector recall.

### 2. What was the root cause of the 13 unreached units?

Every one was the persisted runtime rank-2 search candidate behind a clean
rank-1 result while `top_k=1`. They remained inside the four-candidate pool but
were not consumed by the recorded path.

### 3. Why not simply raise `top_k` to 2?

That would alter evidence selection, model context, answer behavior, cost, and
security exposure simultaneously. The ablation needed to measure ranking depth
without changing the live system.

### 4. What is the difference between candidate presence and selection?

Presence means a unit exists in the bounded candidate pool. Selection means a
post-Guard admitted evidence chunk survives into the Agent's evidence. R2-S3
observed candidate presence `26/28` and selected attack evidence `0/28`.

### 5. Why is replay necessary if live counts already exist?

Live evidence has trustworthy per-case counts but lacks labeled unit identity
on every scan. Replay reconstructs per-unit attribution from exact persisted
order and production scan provenance, then must equal the live counts.

### 6. Is replay the same as a second model run?

No. It uses no embeddings, Ollama, generation, Agent runner, HTTP, or network.
It deterministically replays production content admission against frozen
fixture-backed evidence.

### 7. Why are open units excluded from search-depth coverage?

They have no search candidate rank. They are reached only through an actual
recorded `open` operation. Giving them a hypothetical search rank would
fabricate behavior and corrupt the denominator.

### 8. Why does depth 1 search reach equal `6/26` while total reach is `15/28`?

Search reach counts only rank-1 search units. Total reach unions that diagnostic
rank result with actual replay reach, which also includes adjacent-window scans
and two recorded open units.

### 9. Why is depth-2 total coverage `28/28` not a production result?

No production request executed the added rank-2 scans. It is a deterministic
counterfactual. The estimate also omits measured latency and false-positive
impact.

### 10. How are additional scan costs prevented from double-counting?

Each scan uses the exact case/operation/chunk/surface identity, existing scans
are subtracted, and repeated per-unit case fields are collapsed to one case
representative before summing units and `scanned_length`.

### 11. What would change the decision to mitigation required?

Any observed Controller, ledger, model-context, verifier, response,
forbidden-action, external-egress, or attack-success signal in a case containing
an unreached unit takes precedence and yields `RUNTIME_MITIGATION_REQUIRED`.

### 12. What does `NO_CURRENT_BYPASS_OBSERVED` actually authorize?

It authorizes only the narrow statement that this frozen dev evidence does not
justify a production retrieval-prefilter change. It does not authorize release,
deployment, universal safety, or claims about unseen attacks or other models.

## 12. Final Review Fix Wave and Evidence Migration

The final whole-branch review found nine Important and seven same-wave Minor
issues in result recomputation, source semantic joining, replay dependency byte
binding, public auditing, path identity, snapshot export, URI scanning,
delivery authority, and operator documentation. Each behavior repair was driven
by a recorded RED test before production edits. Private/public verifiers retain
v1 compatibility, while new producers emit explicit v2 manifests.

The current accepted evaluator was executed exactly once against the unchanged
source before this migration. The accepted evidence identity is:

```text
accepted private run          r2-s3-dev-exposure-20260721-04
source manifest SHA-256       3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e
private manifest schema       indirect_injection_exposure_run_manifest_v2
private manifest SHA-256      4c8cfb6ad826fc1ca9c24afb0157129df661f3cd463aa3448ec161c0608c5f1f
accepted evaluator SHA-256    d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88
public manifest schema        indirect_injection_exposure_public_manifest_v2
public manifest SHA-256       09fda4aa81d15757e8de7cadec32e057a1c01d23a5b646dbcd5c0f9ae9038033
packaged verifier SHA-256     dbe814605220058c0bf2453ee1cac0450253bd788b64f9979ab1eb77c2413897
```

The `r2-s3-dev-exposure-20260721-01` v1 artifact, first v2
`r2-s3-dev-exposure-20260721-02` artifact, and superseded `-03` artifact are
superseded local history. None was changed or rerun, and all remain independently
verifiable. The `-03` and `-04` private `summary.json` and `per_unit.jsonl`
files are byte-identical.

### Fixed-HEAD source-binding follow-up

The first whole-branch re-review correctly observed that the result model's
hashes established self-consistency, not an independent source authority. A
caller able to rewrite rows or non-row witnesses together with their hashes and
recomputed summary could create a different internally valid result before the
writer ran. It also found that `load_exposure_inputs()` verified the source run
and then reread `per_case.jsonl` without checking the bytes of that second read
against the verified manifest.

The RED suite covered four coherent row rewrites, one coherent witness rewrite,
one post-verifier source-row mutation, and one writer-boundary rejection. All
seven failed before implementation. The fix made the supported
`publish_exposure_run()` reload the source by its trusted manifest hash, rerun
the deterministic analysis, and require exact typed-result equality before any
staging directory is created. The source loader now compares the exact bytes
and SHA-256 of the consumed `per_case.jsonl` with manifest artifact evidence
before parsing. A same-length fingerprint mutation proves the SHA check itself,
not only the byte-count check. The byte-only `_publish_exposure_run()` helper is
private, absent from `__all__`, and referenced only by synthetic test fixtures.

The change was committed as `33104e1f99fbb67d3a63dabf1c5808611b4d1cdb`.
At that exact commit, before the one-time evaluator invocation, gates were
`1316 passed / 5 skipped`, compile clean, `pip check` clean, and public audit
`451/0`. The now-superseded `-03` evaluator was then invoked
exactly once. Private verification passed, and its `summary.json` and
`per_unit.jsonl` hashes remained exactly
`115d9f1e973c1341e4059d4c4bd28615e31a76104922e10ab877dbfbf5d2e50c` and
`d747d895c26450dd53c9a61623f3ba9572eaf25d0e292775b2f5ea3eedd0bb98`,
matching `-02`; the security result did not change, only its publication trust
boundary did.

Both v2 manifests carry these exact replay implementation dependencies:

```text
app/security/retrieved_content.py                    78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2
app/security/retrieved_admission.py                  1f835ba3aa79b1450e8ae906946bba019c21b531fce114cd375b094411c88afb
app/evaluation/indirect_injection_runner.py          c2c5c5e1815d8a77beebb5027384ea58dd3e73b8536533c8d7898d40668ed36c
app/evaluation/indirect_injection_live_runner.py     a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958
```

Private v2 verification and trusted plus isolated public verification all
recomputed the unchanged metrics: candidate presence `26/28`, live/replay reach
`15/28`, conditional quarantine `15/15`, unreached downstream exposure `0/13`,
search reach `6/26 -> 22/26 -> 26/26`, total reach
`15/28 -> 28/28 -> 28/28`, and additional scan units/characters
`0/0 -> 29/3845 -> 33/4200`. Final local gates were focused
`457 passed / 10 skipped / 3 known warnings`, full
`1395 passed / 13 skipped / 3 known warnings`, compile/pip clean, and public
audit `454/0`. The skips are platform-dependent symlink/junction variants
unavailable on this host. Push is allowed only after fixed-HEAD reviews and
local gates pass; actual delivery and CI state are established by Git and
GitHub Actions.

## Static Path Re-review Trust Boundary

The calibrated path re-review rejects POSIX symlinks and Windows reparse
points at each caller-declared root and its validated descendants before
canonicalization. This includes private exposure snapshot/export source roots,
each private exposure artifact snapshot and identity check, live-run snapshot
roots/artifacts, and the live-run verifier CLI's lexical run-path handoff.
Verification and publication assume a trusted local
operator, a clean reviewed checkout, a stable filesystem during one
verification/publication call, and a trusted Python interpreter, import cache,
dependencies, and runtime memory. Redirecting ancestors above the declared
root are not part of that root's lexical policy.

Hashes identify selected canonical source files on disk. They identify source
text, not loaded bytecode, a complete transitive implementation closure,
behavior, or producer identity. Concurrent ABA replacement by a local writer
and compromised runtime/import state are outside the frozen threat model.
Stronger guarantees require an external immutable execution/attestation
boundary.

## Final Re-review Public-Audit Pair Alignment (Wave 2)

Strict per-file schemas were necessary but not sufficient for the four files
that seed the public leak corpus. `FixtureCase.open_results` defaults to an
empty tuple, so deleting that raw key from an otherwise canonical manifest
still produced a valid `FixtureManifest`. Replacing a canonical nonempty list
with `[]` also left the manifest individually valid. In both cases the old
audit built a smaller sensitive-value corpus and silently lost protected source
content because it never checked the fixture against its dataset.

The audit now preserves raw `candidates` and `open_results` presence and shape
checks before Pydantic validation. It then loads all four sources as strict
`IndirectInjectionDataset` or `FixtureManifest` instances, requires each model's
split to match its declared source path, rejects duplicate or missing split
state, and calls `validate_dataset_fixture_alignment` for the dev and test
pairs. Any load, split, or pair-alignment failure yields deterministic
`invalid_security_corpus` findings and prevents construction of even a partial
`SecuritySensitiveValueCorpus`.

The first RED command targeted the two canonical open-result omissions:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_repository.py -k "omits_canonical_open_results"
```

It produced `2 failed, 59 deselected, 3 warnings`: removing the key and
emptying the original nonempty list both passed the base audit. The expanded
RED command covered raw fixture shapes, both omission mutations, and misplaced
dataset/fixture splits; it produced `10 failed, 6 passed, 47 deselected, 3
warnings`. After implementation, that same expanded command produced `16
passed, 47 deselected, 3 warnings`, and the complete audit module produced `63
passed, 3 warnings`.

Fresh final gates on the resulting code were:

```text
focused six-file R2-S3/public pytest   457 passed / 10 skipped / 3 warnings
full repository pytest                1395 passed / 13 skipped / 3 warnings
compileall                             exit 0
pip check                              no broken requirements
public repository audit               454 candidates / 0 findings
```

The skips are platform-dependent symlink/junction variants unavailable on this
host. The three warnings are the existing SWIG deprecations. No evaluator,
publisher, live model, source/private/public verifier, isolated verifier, or
evidence-generation command was run, and no immutable run or evidence file was
changed.

## CI #12 Cross-platform Test Remediation

GitHub Actions run
[`29837884737`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/29837884737)
is the immutable RED result for exact SHA
`ffcda1b37ceb68712ad004174309aaae9cba401c`: its clean Ubuntu clone reported
`2 failed, 1396 passed, 10 skipped, 5 warnings`. The failures were test-only
cross-platform assumptions, not evidence or production verifier defects.

First, the real POSIX `summary.json` symlink regression still expected the
legacy `regular files` failure, while the hardened lexical path check correctly
rejects it earlier as `exposure artifact summary.json has a redirecting path
component`; the adjacent mocked artifact-reparse regression already establishes
that precise contract. Second, the documented isolated-verifier test performed
platform-neutral document and command-order checks correctly, but then
unconditionally launched `powershell.exe`, which is absent on Ubuntu.

The local Windows gate did not expose either failure: symlink creation is not
available in this environment, so the real-symlink test skips, and Windows
PowerShell is present. The minimal repair updates only the stale symlink
expectation and, after all static assertions, skips command execution on
non-Windows hosts with an explicit unavailable-Windows-PowerShell reason.
Windows retains its existing real execution and package assertions. No
production validation, evidence, evaluator, publisher, or dependency changed.
The next exact-SHA GitHub CI run remains the delivery gate.
