# R2-S4 Cross-Model Security Replication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and execute a digest-bound Qwen2.5:3b versus Qwen3:8b dev security replication whose only changed variable is chat-model identity, with restart-safe operation and independently verifiable public evidence.

**Architecture:** Preserve the historical live CLI and extract its execution body behind an internal typed request. A new declarative matrix orchestrator validates a checked-in plan, executes or exactly reuses two immutable V3 live runs, verifies non-chat invariants, publishes a private comparison, and exports an eight-file content-free package with a standard-library verifier.

**Tech Stack:** Python 3.11, Pydantic v2 strict frozen models, Ollama local API, BGE-M3, Qwen2.5:3b, Qwen3:8b, canonical JSON/JSONL, SHA-256, pytest, PowerShell, GitHub Actions.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-22-r2-s4-cross-model-replication-design.md`.
- Split is exactly `dev`; alternative chat models must never run the frozen official `test` split.
- Embedding identity is exactly `bge-m3:latest` digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`.
- Baseline chat identity is exactly `qwen2.5:3b` digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`.
- Replication chat identity is exactly `qwen3:8b` digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Component run IDs are `r2-s4-qwen25-dev-20260722-01` and `r2-s4-qwen3-dev-20260722-01`; matrix run ID is `r2-s4-cross-model-dev-20260722-01`.
- Each model must execute 36 cases, 72 arm events, and exact 18/18 counterbalancing.
- The existing `scripts.eval_indirect_injection_live` parser must not expose `--chat-model`, `--embedding-model`, `--force`, or a Guard override.
- Do not change production Guard, retrieval, Agent, prompts, frozen test data, holdout data, or historical immutable run artifacts.
- Do not tune timeouts, attempts, rules, labels, or prompts after seeing either real-model result.
- Private `security_runs/`, including `security_runs/cross_model_matrices/`, remains ignored; only the allowlisted public package is tracked.
- Public evidence excludes questions, retrieved text, prompts, answers, canaries, raw source IDs, absolute paths, credentials, environment variables, and private run locations.
- Any post-run change to bound evaluator/writer/verifier/plan/Guard/retrieval/Agent bytes requires new run IDs; never rerun the three IDs above.
- Use RED/GREEN TDD, explicit-path staging, per-task spec/quality review, final whole-branch review, exact-HEAD local gates, and exact-SHA GitHub CI.
- The evaluator acquires a standard-library no-wait OS-backed exclusive lock keyed by normalized local Ollama origin before preflight, Git/identity reads, index build, model work, and matrix/publication. Keep the manual no-other-Ollama-client check for non-cooperating external clients.

## File Structure

### Experiment contracts and execution

- Create `app/evaluation/indirect_injection_cross_model.py`: plan schemas, plan loader, component invariant comparison, redacted rows, metric recomputation, and decision.
- Create `data/v2/evaluation/r2_s4_cross_model_matrix_v1.json`: checked-in exact model matrix.
- Modify `app/evaluation/indirect_injection_live_writer.py`: V3 manifest and verified snapshot support without changing V1/V2 behavior.
- Modify `scripts/eval_indirect_injection_live.py`: typed internal execution boundary; historical CLI remains locked.
- Create `scripts/eval_indirect_injection_cross_model.py`: plan-driven preflight, safe restart, and two-model orchestration.

### Private and public evidence

- Create `app/evaluation/indirect_injection_cross_model_writer.py`: immutable private matrix writer/verifier.
- Create `app/evaluation/indirect_injection_cross_model_public.py`: strict private-to-public projection.
- Create `app/evaluation/indirect_injection_cross_model_public_verifier.py`: dependency-free public package verifier source.
- Create `scripts/verify_indirect_injection_cross_model.py`.
- Create `scripts/export_indirect_injection_cross_model_public.py`.
- Create `scripts/verify_indirect_injection_cross_model_public.py`.
- Generate ignored `security_runs/cross_model_matrices/r2-s4-cross-model-dev-20260722-01/`.
- Generate tracked `data/v2/public/r2_s4_cross_model/`.

### Tests and documentation

- Create `tests/evaluation/test_indirect_injection_cross_model.py`.
- Create `tests/evaluation/test_indirect_injection_cross_model_cli.py`.
- Create `tests/evaluation/test_indirect_injection_cross_model_writer.py`.
- Create `tests/evaluation/test_indirect_injection_cross_model_public.py`.
- Modify `tests/evaluation/test_indirect_injection_live_cli.py`.
- Modify `tests/evaluation/test_indirect_injection_live_writer.py`.
- Create `docs/security/r2_s4/00_cross_model_protocol.md`.
- Create `docs/security/r2_s4/01_results.md`.
- Create `docs/security/r2_s4/02_engineering_journal.md`.
- Create `docs/roadmap/r2_industrialization_execution_plan.md`.
- Modify `PROJECT_STATUS.md`, `README.md`, `docs/known_limitations.md`, `docs/industrialization_backlog.md`, and `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`.

---

### Task 1: Freeze The Declarative Matrix Plan

**Files:**
- Create: `app/evaluation/indirect_injection_cross_model.py`
- Create: `data/v2/evaluation/r2_s4_cross_model_matrix_v1.json`
- Create: `tests/evaluation/test_indirect_injection_cross_model.py`

**Interfaces:**
- Produces `CrossModelPlanV1`, `CrossModelModelPlan`, `CrossModelPlanError`, `load_cross_model_plan(path: Path) -> tuple[CrossModelPlanV1, str]`, and `model_for_role(role: Literal["baseline", "replication"]) -> CrossModelModelPlan`.
- The returned string is the SHA-256 of the exact canonical plan bytes.

- [ ] **Step 1: Write RED contract tests**

Add tests that load the real checked-in plan and assert:

```python
plan, digest = load_cross_model_plan(PLAN_PATH)
assert plan.schema_version == "indirect_injection_cross_model_plan_v1"
assert plan.experiment_id == "r2-s4-cross-model-dev-v1"
assert plan.split == "dev"
assert plan.expected_case_count == 36
assert plan.expected_arm_event_count_per_model == 72
assert plan.model_for_role("baseline").requested_name == "qwen2.5:3b"
assert plan.model_for_role("replication").requested_name == "qwen3:8b"
assert len(digest) == 64
```

Parameterized mutations must reject: unknown field, `test` split, duplicate
role/name/digest/run ID, missing metric, unsafe run ID, wrong embedding digest,
noncanonical JSON, and more or fewer than two chat models.

- [ ] **Step 2: Confirm RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_cross_model.py -k "plan"
```

Expected: import/collection failure because the module and plan do not exist.

- [ ] **Step 3: Add the strict models and canonical loader**

Use strict frozen Pydantic models. The checked-in JSON must encode exactly:

```json
{
  "chat_models": [
    {
      "digest": "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b",
      "family": "qwen2",
      "parameter_size": "3.1B",
      "requested_name": "qwen2.5:3b",
      "resolved_name": "qwen2.5:3b",
      "role": "baseline",
      "run_id": "r2-s4-qwen25-dev-20260722-01"
    },
    {
      "digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
      "family": "qwen3",
      "parameter_size": "8.2B",
      "requested_name": "qwen3:8b",
      "resolved_name": "qwen3:8b",
      "role": "replication",
      "run_id": "r2-s4-qwen3-dev-20260722-01"
    }
  ],
  "comparison_metric_ids": [
    "off_user_boundary_attack_success",
    "on_user_boundary_attack_success",
    "off_raw_follow_signal",
    "on_raw_follow_signal",
    "off_model_context_exposure",
    "on_model_context_exposure",
    "on_conditional_quarantine",
    "on_all_labeled_quarantine",
    "on_benign_quarantine",
    "clean_utility",
    "mixed_utility",
    "poison_only_utility",
    "model_error_count",
    "blocked_egress",
    "model_call_count",
    "model_latency_p50_ms",
    "model_latency_p95_ms"
  ],
  "embedding": {
    "digest": "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab",
    "requested_name": "bge-m3",
    "resolved_name": "bge-m3:latest"
  },
  "expected_arm_event_count_per_model": 72,
  "expected_arm_order_protocol": "stable_case_hash_rank_counterbalanced_v1",
  "expected_case_count": 36,
  "experiment_id": "r2-s4-cross-model-dev-v1",
  "matrix_run_id": "r2-s4-cross-model-dev-20260722-01",
  "only_changed_variable": "chat_model_identity",
  "schema_version": "indirect_injection_cross_model_plan_v1",
  "split": "dev"
}
```

Canonical form is UTF-8, sorted keys, indent 2, trailing newline. Reject bytes
that differ from reserialization.

- [ ] **Step 4: Run GREEN tests**

Run the same focused command. Expected: all selected tests pass.

- [ ] **Step 5: Commit explicit files**

```powershell
git add app/evaluation/indirect_injection_cross_model.py data/v2/evaluation/r2_s4_cross_model_matrix_v1.json tests/evaluation/test_indirect_injection_cross_model.py
git commit -m "feat: freeze R2-S4 cross-model plan"
```

---

### Task 2: Add Manifest V3 And A Shared Live Execution Boundary

**Files:**
- Modify: `app/evaluation/indirect_injection_live_writer.py`
- Modify: `scripts/eval_indirect_injection_live.py`
- Modify: `tests/evaluation/test_indirect_injection_live_writer.py`
- Modify: `tests/evaluation/test_indirect_injection_live_cli.py`

**Interfaces:**
- Produces `CrossModelExperimentBinding` and `LiveSecurityRunManifestV3`.
- Produces `LiveExecutionRequest`, `LiveExecutionOutcome`, and `execute_live_security_run(request: LiveExecutionRequest) -> LiveExecutionOutcome`.
- V1/V2 `verify_live_security_run()` behavior remains byte-for-byte compatible at its public interface.

- [ ] **Step 1: Write RED V3 and historical-CLI tests**

Assert V3 requires the exact fields:

```python
binding = CrossModelExperimentBinding(
    plan_id="r2-s4-cross-model-dev-v1",
    plan_sha256="a" * 64,
    model_role="replication",
    only_changed_variable="chat_model_identity",
)
assert binding.model_role == "replication"
```

Writer tests must publish and verify a temporary V3 run, then reject altered
plan hash, role, model digest, artifact bytes, summary, and arm order. Existing
V1/V2 fixtures must still verify.

CLI tests must continue asserting `--chat-model` is absent. Add a test showing
that the internal cross-model request rejects `test` before settings, Ollama,
index, or model calls.

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_live_writer.py tests\evaluation\test_indirect_injection_live_cli.py -k "v3 or cross_model or parser_has_no"
```

Expected: failures for missing V3/request contracts.

- [ ] **Step 3: Implement V3 without widening V1/V2**

Add:

```python
class CrossModelExperimentBinding(_StrictFrozenModel):
    plan_id: Literal["r2-s4-cross-model-dev-v1"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_role: Literal["baseline", "replication"]
    only_changed_variable: Literal["chat_model_identity"]


class LiveSecurityRunManifestV3(LiveSecurityRunManifestV2):
    schema_version: Literal["indirect_injection_live_security_run_manifest_v3"]
    mode: Literal["local_live_paired_counterbalanced_cross_model_dev"]
    split: Literal["dev"]
    experiment: CrossModelExperimentBinding
```

Update schema dispatch and consistency checks with explicit V3 branches. Do not
make `isinstance(V3, V2)` accidentally serialize the V2 schema; dispatch from
`schema_version` or most-specific type first.

- [ ] **Step 4: Extract the internal execution request**

Define:

```python
@dataclass(frozen=True)
class LiveExecutionRequest:
    args: argparse.Namespace
    chat_model: str
    expected_chat_digest: str
    experiment: CrossModelExperimentBinding | None = None
    evaluator_path: str = "scripts/eval_indirect_injection_live.py"
    canonical_argv: tuple[str, ...] | None = None


@dataclass(frozen=True)
class LiveExecutionOutcome:
    output_dir: Path
    manifest: LiveSecurityRunManifestV2 | LiveSecurityRunManifestV3
```

Move the current main body into `execute_live_security_run()`. Historical
`main()` creates a request with `settings.chat_model`, the frozen Qwen2.5
digest policy, no experiment binding, and the existing canonical argv. V3
requires `dev`, exact expected digest, and an experiment binding. Verify the
resolved Ollama chat digest before index build.

- [ ] **Step 5: Run GREEN and broad live regression**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_live_writer.py tests\evaluation\test_indirect_injection_live_cli.py tests\evaluation\test_indirect_injection_live_runner.py
```

Expected: pass with only known SWIG warnings.

- [ ] **Step 6: Commit explicit files**

```powershell
git add app/evaluation/indirect_injection_live_writer.py scripts/eval_indirect_injection_live.py tests/evaluation/test_indirect_injection_live_writer.py tests/evaluation/test_indirect_injection_live_cli.py
git commit -m "feat: add cross-model live manifest v3"
```

---

### Task 3: Build The Plan-Driven Restart-Safe Orchestrator

**Files:**
- Create: `scripts/eval_indirect_injection_cross_model.py`
- Create: `tests/evaluation/test_indirect_injection_cross_model_cli.py`

**Interfaces:**
- Produces `build_parser()`, `admit_existing_component(...)`, `run_component(...)`, and `main(argv: list[str] | None = None) -> int`.
- Consumes Task 1 plan contracts and Task 2 internal execution API.

- [ ] **Step 1: Write RED preflight and restart tests**

Tests must prove:

- help has no side effects;
- default plan path is the checked-in R2-S4 plan;
- dirty tracked worktree, wrong branch/HEAD transition, missing model, wrong
  digest, wrong embedding identity, occupied matrix target, and frozen D7 run ID
  fail before model execution;
- an absent component runs once;
- an exact complete V3 component is verified and reused;
- V1/V2, wrong plan hash, wrong role, wrong run ID, wrong Git HEAD, wrong data or
  Guard hash, incomplete protocol, or artifact tampering is never reused;
- no `--force`, arbitrary model override, test split, timeout override, or
  prompt override exists.

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_cross_model_cli.py
```

Expected: import failure because the script does not exist.

- [ ] **Step 3: Implement bounded orchestration**

The only public options are:

```text
--plan
--out-dir
--index-root
--matrix-out-dir
```

The command loads the plan, captures one clean Git provenance snapshot, fetches
Ollama identities once, validates all three exact digests, and sequentially
calls `execute_live_security_run()` for baseline then replication. For an
existing target, call `verify_live_security_run()` and compare every plan/Git/
data/Guard/model invariant before returning a reused outcome. After both
components, recapture Git provenance and require exact equality.

Do not catch and convert evidence exceptions into success. Print only run IDs,
roles, reuse booleans, status, protocol completeness, and output paths.

- [ ] **Step 4: Run GREEN tests**

Run the same focused file. Expected: all pass.

- [ ] **Step 5: Commit explicit files**

```powershell
git add scripts/eval_indirect_injection_cross_model.py tests/evaluation/test_indirect_injection_cross_model_cli.py
git commit -m "feat: orchestrate restart-safe cross-model runs"
```

---

### Task 4: Recompute And Publish The Private Matrix

**Files:**
- Modify: `app/evaluation/indirect_injection_cross_model.py`
- Create: `app/evaluation/indirect_injection_cross_model_writer.py`
- Create: `scripts/verify_indirect_injection_cross_model.py`
- Create: `tests/evaluation/test_indirect_injection_cross_model_writer.py`
- Modify: `scripts/eval_indirect_injection_cross_model.py`

**Interfaces:**
- Produces `CrossModelCaseRow`, `CrossModelMetric`, `CrossModelModelSummary`, `CrossModelComparisonResult`, and `CrossModelDecision`.
- Produces `compare_verified_runs(...) -> CrossModelComparisonResult`, `publish_cross_model_run(...) -> Path`, and `verify_cross_model_run(path: Path) -> CrossModelRunManifest`.

- [ ] **Step 1: Write RED comparison tests**

Writer-generated temporary V3 component runs must demonstrate:

- exactly 72 redacted comparison rows: 36 baseline plus 36 replication;
- each row joins OFF/ON observations for one case and contains no source text;
- all non-chat invariants are compared, including Git HEAD/clean state,
  dependencies, embedding digest, data/fixture/Guard hashes, retrieval settings,
  arm order, pair fingerprints, candidate order, attempts, temperature, prompt
  variant, and egress policy;
- summaries and deltas are recomputed from rows rather than copied;
- complete equal security observations produce `CONSISTENT_OBSERVATION`;
- complete valid security/utility differences produce `DIVERGENT_OBSERVATION`;
- incomplete/error/identity/invariant mismatch produces `INCONCLUSIVE`;
- target exists, checksum mutation, row mutation, summary mutation, manifest
  mutation, symlink/junction redirect where supported, or extra file is rejected.

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_cross_model_writer.py
```

Expected: missing writer/contracts.

- [ ] **Step 3: Implement strict recomputation**

Use these exact decision values:

```python
CrossModelDecision = Literal[
    "CONSISTENT_OBSERVATION",
    "DIVERGENT_OBSERVATION",
    "INCONCLUSIVE",
]
```

Load component `per_case.jsonl` through trusted regular-file snapshots. Parse
typed `SecurityCaseResult` and `LiveCaseObservation`; join by model role and
case ID; derive public-safe case class from the frozen dataset, not from model
output. Recompute rates using integer numerator/denominator pairs and nearest-
rank p50/p95 already used by the live runner.

- [ ] **Step 4: Implement immutable private publication**

Private package files are exactly:

```text
manifest.json
summary.json
per_case_redacted.jsonl
checksums.sha256
commands.txt
verification_witness.json
```

Write into a trusted staging directory, validate canonical bytes and forbidden
content, then atomically publish without replacement. The manifest binds plan
bytes/hash, both component manifest/artifact hashes, comparison code hash, live
runner/writer hashes, Guard/retrieval/Agent dependency hashes, and all six
artifact byte/hash entries.

- [ ] **Step 5: Integrate the orchestrator**

After both component outcomes verify, compare them and publish the private
matrix. If the matrix target already exists, verify it and require exact plan,
component, and code bindings; never overwrite it.

- [ ] **Step 6: Run GREEN and tamper tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_cross_model.py tests\evaluation\test_indirect_injection_cross_model_cli.py tests\evaluation\test_indirect_injection_cross_model_writer.py
```

- [ ] **Step 7: Commit explicit files**

```powershell
git add app/evaluation/indirect_injection_cross_model.py app/evaluation/indirect_injection_cross_model_writer.py scripts/eval_indirect_injection_cross_model.py scripts/verify_indirect_injection_cross_model.py tests/evaluation/test_indirect_injection_cross_model.py tests/evaluation/test_indirect_injection_cross_model_cli.py tests/evaluation/test_indirect_injection_cross_model_writer.py
git commit -m "feat: publish verified cross-model matrix"
```

---

### Task 5: Export Independently Verifiable Public Evidence

**Files:**
- Create: `app/evaluation/indirect_injection_cross_model_public.py`
- Create: `app/evaluation/indirect_injection_cross_model_public_verifier.py`
- Create: `scripts/export_indirect_injection_cross_model_public.py`
- Create: `scripts/verify_indirect_injection_cross_model_public.py`
- Create: `tests/evaluation/test_indirect_injection_cross_model_public.py`

**Interfaces:**
- Produces `export_cross_model_public(private_run: Path, output_dir: Path) -> Path`.
- Produces dependency-free `verify_public_package(package_dir: Path) -> dict[str, object]` and packaged `verify.py` CLI.

- [ ] **Step 1: Write RED public-boundary tests**

Tests must require exactly the eight files in the design, 72 canonical rows,
two exact model digests, component/private manifest witness hashes, no private
path, and independent recomputation of summaries, deltas, and decision.

Search every candidate byte for all questions, fixture text, canaries, prompt
fragments, answers, raw unit/source IDs, current username/home path, `security_runs`,
`cross_model_runs`, environment values, and credential patterns. Deliberately
insert each forbidden class and prove export fails.

Copy the eight files into an isolated temporary directory with no repository on
`PYTHONPATH`; `python verify.py .` must exit 0. Mutation, missing/extra file,
checksum mismatch, schema drift, duplicate ordinal, row reorder, summary
contradiction, manifest contradiction, and redirecting path must fail.

- [ ] **Step 2: Confirm RED**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_cross_model_public.py
```

- [ ] **Step 3: Implement allowlisted projection and verifier**

The public projection must construct new dictionaries from an explicit key
allowlist; it must never recursively dump a private model. `verify.py` may use
only Python standard-library imports and must pin its own SHA-256 in both the
manifest and verification witness without creating a circular manifest hash.

- [ ] **Step 4: Run GREEN, repository audit, and isolated verification tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_cross_model_public.py tests\test_public_repository.py
```

- [ ] **Step 5: Commit explicit files**

```powershell
git add app/evaluation/indirect_injection_cross_model_public.py app/evaluation/indirect_injection_cross_model_public_verifier.py scripts/export_indirect_injection_cross_model_public.py scripts/verify_indirect_injection_cross_model_public.py tests/evaluation/test_indirect_injection_cross_model_public.py
git commit -m "feat: add public cross-model evidence verifier"
```

---

### Task 6: Freeze Operator Protocol And Pass Pre-Run Gates

**Files:**
- Create: `docs/security/r2_s4/00_cross_model_protocol.md`
- Create: `docs/security/r2_s4/02_engineering_journal.md`
- Modify: `docs/known_limitations.md`
- Modify: `docs/industrialization_backlog.md`

**Interfaces:**
- Produces the exact operator commands, failure semantics, immutable-ID list,
  metric definitions, claim boundary, and pre-run evidence record.

- [ ] **Step 1: Document protocol without results**

Record plan/model hashes, data flow, safe restart, private/public boundaries,
decision semantics, known limits, and these exact NOT RUN statements:

```text
independent holdout         NOT RUN
semantic judge calibration NOT RUN
human double review        NOT RUN
production traffic         NOT RUN
```

- [ ] **Step 2: Run focused and full pre-run gates**

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\evaluation\test_indirect_injection_live_runner.py tests\evaluation\test_indirect_injection_live_writer.py tests\evaluation\test_indirect_injection_live_snapshot_hardening.py tests\evaluation\test_indirect_injection_live_cli.py tests\evaluation\test_indirect_injection_cross_model.py tests\evaluation\test_indirect_injection_cross_model_cli.py tests\evaluation\test_indirect_injection_cross_model_writer.py tests\evaluation\test_indirect_injection_cross_model_public.py tests\test_public_repository.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app scripts streamlit_app tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m scripts.audit_public_repo
```

Also run the R1 frozen hash verifier plus R2-S1 and R2-S3 public/private/source
verifiers without modifying their artifacts.

- [ ] **Step 3: Run task and whole-branch pre-run reviews**

No real model run may start with an open Critical or Important finding. Fix
valid findings with TDD, repeat reviews, then rerun all pre-run gates.

- [ ] **Step 4: Commit protocol and any reviewed fixes**

Stage only named files and commit. After the commit, confirm `git status --short`
is empty and write the exact clean run HEAD, gate outputs, and timestamp to the
ignored `.superpowers/sdd/r2-s4-pre-run-gates.md`. Do not edit a tracked journal
to record the commit that contains that edit. Immutable component manifests and
the final public `common_git` are the authoritative run-HEAD evidence.

---

### Task 7: Execute The One-Time Local Cross-Model Matrix

**Files:**
- Generate ignored: `security_runs/r2-s4-qwen25-dev-20260722-01/`
- Generate ignored: `security_runs/r2-s4-qwen3-dev-20260722-01/`
- Generate ignored: `security_runs/cross_model_matrices/r2-s4-cross-model-dev-20260722-01/`

**Interfaces:**
- Consumes the clean exact HEAD and checked-in plan.
- Produces two immutable V3 component runs and one immutable private matrix.

- [ ] **Step 1: Preflight exact identities and absent IDs**

Run `ollama list` and `/api/tags`; require the three full digests from Global
Constraints. Confirm no target run directory exists, no concurrent evaluator
owns Ollama, and the worktree is clean. Before any Ollama identity, embedding,
smoke, or chat call, classify each component output together with its auxiliary
index target. If the output is absent but its index target exists, classify it
as `ORPHAN_AUXILIARY_INDEX`, fail closed, and make no model-side call. Do not
delete or reuse the index. Preserve it for diagnosis and admit only a reviewed
canonical plan with new `-02` component and matrix IDs after TDD and re-review.

The controller lock is the cooperating-evaluator exclusion mechanism. The
manual operator check still matters for non-cooperating external Ollama clients;
the run is supported only when the same local endpoint is not being used outside
the locked evaluator.

- [ ] **Step 2: Run the matrix once**

```powershell
.\.venv\Scripts\python.exe -u -m scripts.eval_indirect_injection_cross_model --plan data\v2\evaluation\r2_s4_cross_model_matrix_v1.json
```

Do not change parameters or rerun an existing ID after seeing output. A process
failure is diagnosed from logs and immutable/staging state. An orphan auxiliary
index is not a resumable `-01` state: retain it, record the recovery
classification, and move to reviewed `-02` IDs. Only code/protocol fixes approved
by review may create that new canonical plan.

A structurally valid immutable V3 component with status `FAILED` remains typed
private evidence. It may be compared to produce a private `INCONCLUSIVE` matrix,
but it is not successful-component reuse, cannot support a release/public-
evidence success, and makes the evaluator return nonzero.

- [ ] **Step 3: Verify all private artifacts independently**

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_indirect_injection_live_run security_runs\r2-s4-qwen25-dev-20260722-01
.\.venv\Scripts\python.exe -m scripts.verify_indirect_injection_live_run security_runs\r2-s4-qwen3-dev-20260722-01
.\.venv\Scripts\python.exe -m scripts.verify_indirect_injection_cross_model security_runs\cross_model_matrices\r2-s4-cross-model-dev-20260722-01
```

Record exact manifest hashes, statuses, metrics, latency, model calls, errors,
egress, decision, duration, and any failure diagnosis in the journal.

---

### Task 8: Publish Results And Industrialization Roadmap

**Files:**
- Generate: `data/v2/public/r2_s4_cross_model/`
- Create: `docs/security/r2_s4/01_results.md`
- Create: `docs/roadmap/r2_industrialization_execution_plan.md`
- Modify: `docs/security/r2_s4/02_engineering_journal.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `README.md`
- Modify: `docs/known_limitations.md`
- Modify: `docs/industrialization_backlog.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- Modify: `tests/test_public_repository.py`

**Interfaces:**
- Publishes exact accepted evidence and one evidence-driven next industrial
  stage; does not claim the external holdout or owner review happened.

- [ ] **Step 1: Export and verify the public package**

```powershell
.\.venv\Scripts\python.exe -m scripts.export_indirect_injection_cross_model_public security_runs\cross_model_matrices\r2-s4-cross-model-dev-20260722-01 data\v2\public\r2_s4_cross_model
.\.venv\Scripts\python.exe -m scripts.verify_indirect_injection_cross_model_public data\v2\public\r2_s4_cross_model
```

This export is allowed only for complete, release-eligible source evidence; a
private `INCONCLUSIVE` matrix sourced from a valid `FAILED` V3 component cannot
be presented as successful public evidence.

Then copy exactly the eight files outside the repository and run the packaged
standard-library verifier with an empty `PYTHONPATH`, isolated mode, and a
working directory outside the repository:

```powershell
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
$isolated = Join-Path $env:TEMP 'r2-s4-cross-model-public-verify-01'
if (Test-Path -LiteralPath $isolated) { throw "isolated verification target already exists: $isolated" }
Copy-Item -LiteralPath data\v2\public\r2_s4_cross_model -Destination $isolated -Recurse
$savedPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = ''
    Push-Location $env:TEMP
    & $python -I (Join-Path $isolated 'verify.py') $isolated
    if ($LASTEXITCODE -ne 0) { throw "isolated packaged verifier failed with exit $LASTEXITCODE" }
} finally {
    Pop-Location
    $env:PYTHONPATH = $savedPythonPath
}
```

Acceptance requires both the repository-trusted verifier and this copied,
repository-independent verifier to exit `0` and recompute the same result.

- [ ] **Step 2: Document exact observed results**

State per-model numerators/denominators and latency without rounding away
failures. Explain whether the result is consistent, divergent, or inconclusive,
why that decision follows from rows, and what cannot be inferred.

- [ ] **Step 3: Admit one next industrial stage from evidence**

Use `.superpowers/sdd/r2_s4_industrialization_assessment.md` plus observed R2-S4
failures. Rank the top three candidates and admit exactly one. The roadmap must
give trigger, user value, architecture, contract tests, operational/security
gates, rollback, and deferred alternatives. Do not implement that separate
stage inside R2-S4.

- [ ] **Step 4: Add public-repository contracts and synchronize status**

Tests must lock the eight-file package, public verifier command, exact current
claims, and explicit NOT RUN limitations. Update all current-state documents in
one change so no stale “single model only” or false holdout claim remains.

- [ ] **Step 5: Commit explicit evidence and documentation files**

Never stage ignored private runs. Stage only the eight public package files,
R2-S4 docs, status docs, roadmap, and named tests.

---

### Task 9: Final Review, Exact-HEAD Gates, Push, And CI

**Files:**
- Modify only files required by validated final-review findings.

- [ ] **Step 1: Run a whole-branch spec/code/security review**

Review from the R2-S4 start commit to exact HEAD. Any Critical/Important finding
gets one consolidated TDD fix wave and re-review. Minor findings are either
fixed or explicitly recorded with risk and follow-up.

- [ ] **Step 2: Run fresh exact-HEAD local gates**

Repeat Task 6 focused/full/compile/pip/audit/historical verifiers, then verify
both V3 runs, private matrix, repository public package, and isolated package.
Recompute all plan, code, artifact, and witness hashes. Confirm ignored private
runs are unchanged and tracked/staged public bytes are identical.

- [ ] **Step 3: Commit final reviewed state with explicit paths**

Run `git diff --check`, `git diff --cached --check`, and confirm the worktree is
clean. Do not write a commit's own exact SHA into a tracked file. Record the
post-commit exact SHA and gate outputs in ignored
`.superpowers/sdd/r2-s4-pre-run-gates.md`; use immutable component manifests and
public `common_git` as run identity, and use the remote branch/Actions SHA as
delivery identity. Any later tracked edit invalidates the earlier gate record.

- [ ] **Step 4: Push only the approved exact SHA and verify remote CI**

```powershell
git push origin codex/rag-eval-system
```

Verify remote branch SHA equals local HEAD and GitHub Actions succeeds for that
exact SHA. If Ubuntu CI fails, diagnose the exact failure, fix with TDD, rerun
all affected local gates, push the new exact SHA, and verify its CI. Do not
merge, tag, change default branch, rename the repository, or change visibility.
