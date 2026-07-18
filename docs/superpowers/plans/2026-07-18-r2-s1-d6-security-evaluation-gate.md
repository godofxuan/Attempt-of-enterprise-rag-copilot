# R2-S1 D6 Security Evaluation and Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run the frozen 72-case deterministic retrieved-content indirect-injection evaluation, prove a meaningful Guard OFF baseline and a zero-failure Guard ON release gate, without changing R1 data or running the D7 live-model trial.

**Architecture:** A strict dataset layer owns taxonomy, quotas, fixture references and test-set hash verification. A paired evaluator runs the same synthetic ranked candidates through the real `V2ToolRegistry -> RetrievedContentAdmission -> V2AgentController -> GenerationV2ResponseBuilder` path twice, changing only an evaluator-injected pass-through Guard versus the production Guard. A dedicated immutable writer publishes content-free per-case diagnostics and complete provenance under ignored `security_runs/<run_id>/` directories.

**Tech Stack:** Python 3.11+, Pydantic v2 strict models, pytest, existing Agent V2/Guard components, standard-library JSON/CSV/hashlib/pathlib/tempfile/subprocess.

## Global Constraints

- D1 protocol at `docs/security/r2_s1/04_evaluation_protocol.md` is authoritative.
- Dev and test each contain exactly 24 attack plus 12 benign cases; eight attack and four benign categories each have exactly three variants.
- Test is a visible frozen regression set, never described as unseen or held-out.
- Guard OFF exists only as evaluator dependency injection; no API, service setting or environment switch may disable the production Guard.
- Deterministic fake-generator evidence proves propagation only; Qwen/BGE-M3 live evaluation remains `NOT RUN` until D7 approval.
- R1 hashes remain exactly `92b4753df4e69bb570e9ea202420b46124207f15a07cdbb421fb00e6990082bd`, `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338`, and `fc9151daee0d6a0ac1ecfd1b6a3e361bc985d3f8512a8bc76927528ecd32f253` as frozen in D1.
- Security outputs contain synthetic IDs, counts and booleans, never raw retrieved text, prompt messages, canaries, secrets, real identity or absolute local paths.
- Publishing uses same-parent staging, rejects an existing run ID and provides no force/overwrite option.

---

### Task 1: Freeze strict dataset and fixture contracts

**Files:**
- Create: `app/evaluation/indirect_injection_contracts.py`
- Test: `tests/evaluation/test_indirect_injection_contracts.py`

**Interfaces:**
- Produces: `IndirectInjectionDataset`, `IndirectInjectionCase`, `FixtureManifest`, `FixtureCase`, `FixtureCandidate`, `TestFreezeManifest`, taxonomy/format/surface/scenario constants.
- Enforces: exact fields, strict types, unique IDs, category-label agreement, 3 variants/category, 24/12/36 counts, cross-split ID uniqueness and D1 scenario quotas.

- [x] **Step 1: Write failing contract tests**

  Cover unknown fields, coercion, duplicate case/unit IDs, wrong category counts, missing format coverage, insufficient scenario quotas, wrong expected unit outcomes and a valid minimal full bundle.

- [x] **Step 2: Verify RED**

  Run: `.\.venv\Scripts\python.exe -m pytest -q tests/evaluation/test_indirect_injection_contracts.py`

  Expected: collection/import failure because the contract module does not exist.

- [x] **Step 3: Implement strict Pydantic models and validators**

  The final dataset API must reject before evaluation, not silently repair malformed data.

- [x] **Step 4: Verify GREEN**

  Run the same command and require all contract tests to pass.

### Task 2: Build and freeze reproducible synthetic data

**Files:**
- Create: `app/evaluation/indirect_injection_dataset.py`
- Create: `scripts/build_indirect_injection_dataset_v1.py`
- Create: `tests/evaluation/test_indirect_injection_dataset.py`
- Create: `data/v2/security/indirect_injection_dev_v1.json`
- Create: `data/v2/security/indirect_injection_test_v1.json`
- Create: `data/v2/security/indirect_injection_test_v1.manifest.json`
- Create: `data/v2/security/fixtures_v1/dev/manifest.json`
- Create: `data/v2/security/fixtures_v1/test/manifest.json`

**Interfaces:**
- Produces: `build_v1_bundle(root, frozen_at_utc, freeze_git_head)`, `load_security_bundle(...)`, `verify_test_freeze(...)`, `sha256_file(path)`.
- Consumes: Task 1 strict contracts.

- [x] **Step 1: Write failing loader/builder tests**

  Assert hash verification occurs before case execution, path traversal is rejected, missing/tampered fixture manifests fail, destinations cannot be overwritten, checked-in bytes reproduce exactly, and dev/test payload text/canaries/source placements differ.

- [x] **Step 2: Verify RED**

  Run: `.\.venv\Scripts\python.exe -m pytest -q tests/evaluation/test_indirect_injection_dataset.py`

  Expected: import failure for the missing builder/loader.

- [x] **Step 3: Implement deterministic bundle creation and atomic publication**

  Generate 72 synthetic cases from explicit category templates, use inert `.invalid` destinations, store normalized retrieved-content fixtures rather than private corpus data, and create the test freeze manifest from exact bytes.

- [x] **Step 4: Generate checked-in v1 data once**

  Run: `.\.venv\Scripts\python.exe -m scripts.build_indirect_injection_dataset_v1 --output-root data/v2/security --frozen-at-utc 2026-07-18T00:00:00Z --freeze-git-head 0946ad90a7d9b54e219006b271c7c7bdc440863c`

  Expected: five immutable files are created and all counts/hashes are printed.

- [x] **Step 5: Verify GREEN and checked-in integrity**

  Run the Task 1 and Task 2 test files together; require exact byte reproduction in a temporary directory.

### Task 3: Implement the production-path paired evaluator

**Files:**
- Create: `app/evaluation/indirect_injection_runner.py`
- Test: `tests/evaluation/test_indirect_injection_runner.py`

**Interfaces:**
- Produces: `evaluate_paired(dataset, fixtures, config) -> PairedSecurityResult` and strict per-case/summary metric models.
- Uses: evaluator-only `_PassThroughGuard`, recording Guard/admission/controller adapters, deterministic compliant fake chat, and an in-process no-egress boundary.
- Keeps constant: question, candidate order, fixture text, user context, top-k=1, candidate-k=4, fake generator and nonce source across OFF/ON.

- [x] **Step 1: Write failing behavioral tests**

  Prove OFF exposes at least one attack unit and document canary; ON removes attack text from Controller/ledger/prompt/verifier/response/trace; top-ranked poison recovers clean evidence; poison-only returns `security_filtered`; benign units remain available; split fragments are blocked; zero denominators are `not_applicable`; nearest-rank p50/p95 and all numerators/denominators are exact.

- [x] **Step 2: Verify RED**

  Run: `.\.venv\Scripts\python.exe -m pytest -q tests/evaluation/test_indirect_injection_runner.py`

  Expected: missing evaluator import.

- [x] **Step 3: Implement the minimum paired path**

  Build synthetic `RankedSearchPool`/`OpenResult` objects, execute the existing Agent V2 stack, record content-free boundary booleans, map fixture unit IDs to final admitted/quarantined outcomes, and compute all D1 metrics.

- [x] **Step 4: Verify GREEN and regression**

  Run focused runner tests plus existing D2/D4/D5 security and Agent tests.

### Task 4: Implement immutable run artifacts and CLI

**Files:**
- Create: `app/evaluation/indirect_injection_writer.py`
- Create: `scripts/eval_indirect_injection.py`
- Create: `tests/evaluation/test_indirect_injection_writer.py`
- Create: `tests/evaluation/test_indirect_injection_cli.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `publish_security_run(...) -> Path`, strict `SecurityRunManifest`, and CLI exit `0` only when the applicable paired gate passes.
- Artifacts: exact D1 names `manifest.json`, `summary.json`, `per_case.jsonl`, `failures.csv`, `red_green_evidence.md`, `commands.txt`, `test_output.txt`, `checksums.sha256`.

- [x] **Step 1: Write failing writer/CLI tests**

  Cover no-overwrite, same-parent staging cleanup, output hashes/bytes, no raw content/canaries/absolute paths, test-manifest mismatch before evaluator call, absence of `--force`/`--live`, R1 hash mismatch, and non-zero exit on a failed gate.

- [x] **Step 2: Verify RED**

  Run the two new test files and confirm missing implementation failures.

- [x] **Step 3: Implement strict provenance, writer and deterministic-only CLI**

  Record Git status/diff hash, requirements hash, detector/ruleset/resource bounds, synthetic fixture hashes, evaluator hash/argv, fixed budgets and artifact hashes; never serialize raw prompts or payloads.

- [x] **Step 4: Verify GREEN**

  Run all D6 evaluation tests and the repository config/audit tests.

### Task 5: Run dev diagnostics and frozen-test release gate

**Files:**
- Generate ignored: `security_runs/r2-s1-d6-dev-<id>/...`
- Generate ignored: `security_runs/r2-s1-d6-test-<id>/...`
- Modify: `docs/security/r2_s1/05_results.md`
- Create: `docs/security/r2_s1/08_d6_engineering_journal.md`
- Modify: `docs/roadmap/r2_s1_indirect_injection_implementation.md`
- Modify: `docs/superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: checked-in dev/test bundle and the deterministic evaluator CLI.
- Produces: cited aggregate results, immutable artifact identities, failure analysis and the exact D7 approval gate.

- [x] **Step 1: Run dev paired evaluation**

  Use a unique run ID. Any failure stays recorded; change detector/runtime behavior only from a reproduced dev failure with a new regression test.

- [x] **Step 2: Re-freeze/recheck test bytes before first release result**

  Verify dataset and fixture SHA-256 against the checked-in test manifest. Do not edit v1 test data after this point.

- [x] **Step 3: Run frozen test paired evaluation**

  Require the exact D1 ON gates, plus at least one OFF model-context exposure and one OFF fake-generator document-canary exposure.

- [x] **Step 4: Run R1 non-regression and repository-wide verification**

  Recheck all three R1 hashes, full pytest, compileall, `pip check`, public repository audit, `git diff --check`, marker/sensitive scans and absence of project background listeners.

- [x] **Step 5: Write the teaching journal and status updates**

  Explain every file, data flow, formula, RED/GREEN failure, correction, result, limitation and interview question. State clearly that D7 live Qwen/BGE-M3 remains `NOT RUN`.

### Task 6: Independent review and closeout

**Files:**
- Modify only files implicated by valid review findings.

**Interfaces:**
- Consumes: complete D6 diff, D1 protocol and verification evidence.
- Produces: review findings with severity/file/line, regressions for valid bugs, final clean verification and one local D6 commit.

- [x] **Step 1: Request independent read-only review**

  Review schema/provenance, metric correctness, OFF isolation, path/content leakage, immutability and gate completeness.

- [x] **Step 2: Reproduce each valid finding with a failing test**

  Do not patch from opinion alone; preserve RED/GREEN evidence in the journal.

- [x] **Step 3: Run final verification from current HEAD**

  Require the focused D6 suite, full suite and all closeout checks to pass after the final edit.

- [x] **Step 4: Commit and stop at D7**

  Stage only D6-owned files, exclude `.superpowers/` and ignored runs, commit locally, do not push without a separate user request, and ask for `批准D6，执行D7本地真实模型成对评测`.
