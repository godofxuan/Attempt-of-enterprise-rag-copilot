# R2-S2 Independent Holdout Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed local holdout freezer and verifier that binds independently authored payloads, review rubric, coverage, and the exact Guard/evaluator Git baseline without committing raw holdout content.

**Architecture:** A focused evaluation module owns strict Pydantic contracts plus pure freeze/verify functions. Thin CLI scripts provide Git-baseline collection and operator output. Raw packages live only under `holdout_submissions/`, while the public audit rejects that path if it ever appears as a Git candidate.

**Tech Stack:** Python 3.11, Pydantic v2 strict models, SHA-256, argparse, pytest, existing public repository audit.

## Global Constraints

- Do not create or claim an independently authored holdout in this implementation.
- Do not modify the official R2-S1 frozen test dataset, fixture, manifest, D7 run, or V1 public package.
- Raw holdout files must remain outside Git under `holdout_submissions/`.
- Freeze is immutable: an existing `freeze_manifest.json` is an error.
- Verification performs no network, retrieval, embedding, or model calls.
- Every production behavior starts with a failing test.

---

### Task 1: Strict Holdout Package Contracts and Coverage Gate

**Files:**
- Create: `app/evaluation/indirect_injection_holdout.py`
- Create: `tests/evaluation/test_indirect_injection_holdout.py`

**Interfaces:**
- Produces: `HoldoutCaseCatalog`, `HoldoutPayloadEnvelope`, `HoldoutRubric`, `HoldoutCoverageSummary`, `load_holdout_inputs(submission_dir: Path) -> HoldoutInputs`.
- Required constants: `REQUIRED_ATTACK_FAMILIES`, `REQUIRED_SOURCE_SURFACES`, `REQUIRED_RUBRIC_DIMENSIONS`.

- [ ] **Step 1: Write a failing valid-package test**

Create a temporary 36-case package with 24 attack and 12 benign entries. Distribute every required attack family and source surface at least twice, include both `en` and `zh`, and align catalog `case_id/payload_key` pairs exactly with payload entries.

```python
def test_load_holdout_inputs_accepts_complete_aligned_package(tmp_path: Path):
    submission = write_valid_holdout_package(tmp_path)
    loaded = load_holdout_inputs(submission)
    assert loaded.coverage.case_count == 36
    assert loaded.coverage.attack_case_count == 24
    assert loaded.coverage.benign_case_count == 12
    assert set(loaded.coverage.attack_family_counts) == set(REQUIRED_ATTACK_FAMILIES)
```

- [ ] **Step 2: Run the test and observe RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_holdout.py::test_load_holdout_inputs_accepts_complete_aligned_package
```

Expected: collection/import failure because `indirect_injection_holdout` does not exist.

- [ ] **Step 3: Implement strict models and alignment**

Use strict frozen Pydantic models. Catalog entries contain `case_id`, `label`, `families`, `source_surfaces`, `language`, and `payload_key`. Payload entries contain the same IDs plus an opaque JSON object. Rubric requires exactly the four frozen dimensions and distinct non-empty blinded primary/secondary reviewer IDs.

`load_holdout_inputs()` must require exactly `case_catalog.json`, `payload.json`, and `rubric.json`, validate matching holdout IDs, unique IDs/keys, exact catalog/payload identity, and compute coverage from catalog entries rather than trusting author totals.

- [ ] **Step 4: Add one failing test per rejection class**

Tests must independently reject:

```text
duplicate case ID
catalog/payload ID mismatch
fewer than 36 total / 24 attack / 12 benign
missing required attack family or fewer than two occurrences
missing required source surface or fewer than two occurrences
missing en or zh language
benign entry without benign_hard_negative
attack entry containing benign_hard_negative
missing rubric dimension
same primary and secondary reviewer ID
extra file in the draft package
```

- [ ] **Step 5: Implement minimal validators and run the module tests**

Run the complete new test file. Expected: all contract and coverage tests pass.

### Task 2: Immutable Freeze Manifest and Repeatable Verification

**Files:**
- Modify: `app/evaluation/indirect_injection_holdout.py`
- Modify: `tests/evaluation/test_indirect_injection_holdout.py`

**Interfaces:**
- Produces: `HoldoutCodeBaseline`, `HoldoutSeparationAttestation`, `HoldoutFreezeManifest`.
- Produces: `freeze_holdout_submission(submission_dir: Path, *, baseline: HoldoutCodeBaseline, attestation: HoldoutSeparationAttestation, frozen_at_utc: datetime) -> Path`.
- Produces: `verify_holdout_submission(submission_dir: Path, *, baseline: HoldoutCodeBaseline) -> HoldoutFreezeManifest`.

- [ ] **Step 1: Write failing freeze and verify tests**

```python
manifest_path = freeze_holdout_submission(
    submission,
    baseline=baseline,
    attestation=all_true_attestation,
    frozen_at_utc=FROZEN_AT,
)
verified = verify_holdout_submission(submission, baseline=baseline)
assert manifest_path.name == "freeze_manifest.json"
assert verified.coverage.case_count == 36
assert verified.files["payload.json"].sha256 == sha256_file(submission / "payload.json")
```

Expected RED: freeze API does not exist.

- [ ] **Step 2: Implement deterministic freeze bytes**

Manifest fields bind:

```text
submission directory name
holdout ID
freeze UTC
three input SHA-256 values and byte counts
coverage summary
sorted case-ID digest
Git HEAD and branch
tracked-worktree clean flag
Guard/evaluator/freezer paths and SHA-256 values
four true separation attestations
```

Write canonical UTF-8 JSON through a temporary sibling file and atomically rename it to `freeze_manifest.json`.

- [ ] **Step 3: Add tamper and immutability RED tests**

Reject payload modification, catalog modification, rubric modification, baseline mismatch, directory/holdout ID mismatch, false attestation, dirty baseline, existing manifest, missing manifest, and any fifth file other than the generated manifest.

- [ ] **Step 4: Implement verification and run tests**

Verification reloads the three inputs, recomputes all hashes, counts, coverage and case-ID digest, compares the supplied exact code baseline, and round-trips the manifest model. Expected: all freeze/verify tests pass.

### Task 3: Operator CLIs and Git Baseline Collection

**Files:**
- Create: `scripts/freeze_indirect_injection_holdout.py`
- Create: `scripts/verify_indirect_injection_holdout.py`
- Create: `tests/evaluation/test_indirect_injection_holdout_cli.py`

**Interfaces:**
- Freeze CLI: `python -m scripts.freeze_indirect_injection_holdout <submission-dir> --frozen-at-utc <ISO8601> --author-independent --payload-not-shared --labels-not-tuned --single-run`.
- Verify CLI: `python -m scripts.verify_indirect_injection_holdout <submission-dir>`.
- Internal helper: `current_holdout_code_baseline(repo_root: Path) -> HoldoutCodeBaseline`.

- [ ] **Step 1: Write CLI RED tests**

Monkeypatch only baseline collection. Assert freeze emits a content-free JSON receipt containing IDs, counts, hashes and `FROZEN`, and verify emits `VERIFIED`. Assert missing attestation flags and dirty tracked baseline fail before writing a manifest.

- [ ] **Step 2: Implement baseline collection**

Use non-interactive Git commands:

```text
git rev-parse HEAD
git branch --show-current
git status --porcelain --untracked-files=no
```

Require a 40-hex commit, non-empty branch, and no tracked changes. Hash:

```text
app/security/retrieved_content.py
app/evaluation/indirect_injection_live_runner.py
app/evaluation/indirect_injection_holdout.py
```

- [ ] **Step 3: Implement thin CLIs and run CLI tests**

Do not print payload paths outside their local submission directory and do not print payload content, questions, canaries, prompts, reviewer identity beyond blinded IDs, or environment variables.

### Task 4: Git Leak Prevention and Public Audit Contract

**Files:**
- Modify: `.gitignore`
- Modify: `scripts/audit_public_repo.py`
- Modify: `tests/test_public_repository.py`

**Interfaces:**
- `.gitignore` ignores `holdout_submissions/`.
- Public audit treats `holdout_submissions/` as a forbidden prefix and private-runtime reference.

- [ ] **Step 1: Write RED tests**

Assert `.gitignore` contains the exact root path and `audit_repository(..., candidate_files=["holdout_submissions/sample/payload.json"])` reports `forbidden_runtime_artifact`.

- [ ] **Step 2: Extend ignore/audit rules minimally**

Add the one root ignore entry, one forbidden prefix, and one private-runtime regex alternative. Do not ignore checked-in holdout code, tests, specs, plans, or engineering journals.

- [ ] **Step 3: Run public repository tests and actual audit**

Expected: tests pass and actual audit reports zero findings for current Git candidates.

### Task 5: Evidence, Claims Boundary, and Full Verification

**Files:**
- Create: `docs/security/r2_s2/00_holdout_freeze_protocol.md`
- Create: `docs/security/r2_s2/01_s2_1_live_dev_results.md`
- Create: `docs/security/r2_s2/02_engineering_journal.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `README.md`
- Modify: `docs/known_limitations.md`
- Modify: `docs/industrialization_backlog.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`

**Interfaces:**
- Documents must preserve `independent holdout = NOT CREATED / NOT RUN`.
- S2-1 result must preserve `COMPLETED WITH OBSERVATIONS` and diagnostic gate failure, while distinguishing `15/15 reached recall` from `15/28 all-labeled recall` and `13 unreached`.

- [ ] **Step 1: Record S2-1 immutable evidence**

Record run ID `r2-s2-s1-dev-20260719-01`, manifest SHA-256, code HEAD `073d7356026954c26c1429fb9faddc5e9a5dcb87`, model digests, 36 cases, 72 events, 18/18 order, zero model/system errors, zero blocked egress, pair consistency, OFF/ON safety and utility metrics, and position-stratified observations.

- [ ] **Step 2: Explain the discovered classification bug and RED/GREEN fix**

Document that legacy `UnitOutcome` cannot represent unreached, future v2 `failures.csv` now uses `attack_unit_unreached` versus `attack_unit_missed_by_guard`, and the immutable run-01 CSV remains historical while the independent verifier derives the precise classification from live counts.

- [ ] **Step 3: Run final gates**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_live_writer.py tests\evaluation\test_indirect_injection_holdout.py tests\evaluation\test_indirect_injection_holdout_cli.py tests\test_public_repository.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app scripts streamlit_app tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m scripts.audit_public_repo
.\.venv\Scripts\python.exe -m scripts.verify_indirect_injection_live_run security_runs\r2-s2-s1-dev-20260719-01
git diff --check
```

- [ ] **Step 4: Commit and push explicit files**

Create one implementation/evidence commit after the already committed design/plan baseline, push `codex/rag-eval-system`, and verify the exact final HEAD through GitHub Actions. Do not merge, tag, change the default branch, or publish raw holdout inputs.
