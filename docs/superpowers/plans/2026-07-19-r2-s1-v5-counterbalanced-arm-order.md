# R2-S1 V5 Counterbalanced Arm-Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make future local live paired runs execute a deterministic, cohort-balanced mix of OFF-then-ON and ON-then-OFF cases and persist auditable arm-order evidence without changing the frozen D7 v1 run.

**Architecture:** A focused arm-order module builds and validates a canonical SHA-256 hash-rank plan. The live runner accepts that plan and returns an additive v2 result, while retaining its no-plan v1 compatibility path. A v2 manifest and per-case row shape record the complete plan and actual arm positions; the historical v1 parser/writer path remains unchanged.

**Tech Stack:** Python 3.11, Pydantic v2 strict frozen models, pytest, existing immutable security-run writer and SHA-256 artifact checks.

**Execution Status:** Completed locally on 2026-07-19. V5 focused `53 passed`, expanded `404 passed`, full repository `913 passed`; no commit or push performed.

## Global Constraints

- Keep HEAD at `1bf9b95917d7ae813ca6214c7ab83492b4c47aa3` during implementation.
- Do not modify the frozen dataset, fixture manifest, frozen hash files, Guard rules, Guard thresholds, detector version, or existing `security_runs/r2-s1-d7-test-20260718-01` bytes.
- Do not rerun or overwrite the frozen formal D7 run.
- Do not modify the checked-in V1 public package because its checksums intentionally freeze the historical projection.
- Do not use `git add .`, commit, push, merge, rebase, tag, or modify the default branch without explicit user approval.
- Use RED -> GREEN -> refactor for every behavior change.
- Preserve all existing V1-V4 dirty work and the user-owned `.superpowers/` directory.

---

### Task 1: Canonical Counterbalanced Plan Contract

**Files:**
- Create: `app/evaluation/indirect_injection_arm_order.py`
- Create: `tests/evaluation/test_indirect_injection_arm_order.py`

**Interfaces:**
- Produces: `ArmOrderAssignment`, `CounterbalancedArmOrderPlan`, `build_counterbalanced_arm_order_plan(case_ids)`.
- Produces: fixed protocol ID `stable_case_hash_rank_counterbalanced_v1` and assignment method `modes()`.
- Consumes: only standard-library SHA-256 and Pydantic v2.

- [ ] **Step 1: Write failing contract tests**

Cover exact 18/18 balance for 36 IDs, input-order independence, at-most-one imbalance for odd cohorts, canonical assignment ordering, duplicate/empty IDs, and validation failures after mutating a hash, rank, order, or count.

```python
def test_even_cohort_is_exactly_counterbalanced_and_order_independent():
    ids = tuple(f"case-{index:02d}" for index in range(36))
    first = build_counterbalanced_arm_order_plan(ids)
    second = build_counterbalanced_arm_order_plan(tuple(reversed(ids)))
    assert first == second
    assert first.off_then_on_count == 18
    assert first.on_then_off_count == 18
```

- [ ] **Step 2: Run RED tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_arm_order.py`

Expected: collection fails because `app.evaluation.indirect_injection_arm_order` does not exist.

- [ ] **Step 3: Implement the strict plan models and builder**

Use `sha256(case_id.encode("utf-8"))`, sort `(case_hash, case_id)` to assign zero-based ranks, map even ranks to `off_then_on`, odd ranks to `on_then_off`, and serialize assignments sorted by `case_id`.

```python
def build_counterbalanced_arm_order_plan(
    case_ids: Iterable[str],
) -> CounterbalancedArmOrderPlan:
    canonical_ids = _validated_case_ids(case_ids)
    ranked = sorted((_case_hash(case_id), case_id) for case_id in canonical_ids)
    rank_by_id = {case_id: rank for rank, (_, case_id) in enumerate(ranked)}
    assignments = tuple(
        ArmOrderAssignment(
            case_id=case_id,
            case_hash=_case_hash(case_id),
            hash_rank=rank_by_id[case_id],
            arm_order="off_then_on" if rank_by_id[case_id] % 2 == 0 else "on_then_off",
        )
        for case_id in sorted(canonical_ids)
    )
    return CounterbalancedArmOrderPlan.from_assignments(assignments)
```

The model validator must recompute the entire expected ranked allocation rather than trusting caller-supplied summary values.

- [ ] **Step 4: Run GREEN tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_arm_order.py`

Expected: all new plan tests pass.

---

### Task 2: Execute the Plan in the Live Runner

**Files:**
- Modify: `app/evaluation/indirect_injection_live_runner.py`
- Modify: `tests/evaluation/test_indirect_injection_live_runner.py`

**Interfaces:**
- Consumes: `CounterbalancedArmOrderPlan.assignment_for(case_id).modes()`.
- Produces: `LivePairedResultV2`, an additive subclass carrying `arm_order`.
- Changes: `evaluate_live_paired(..., arm_order: CounterbalancedArmOrderPlan | None = None)` returns v1 when omitted and v2 when supplied.

- [ ] **Step 1: Write failing runner tests**

Wrap `_evaluate_live_case` to record `(case_id, guard_mode)` calls. Assert the call sequence equals the manifest plan, while `guard_off` and `guard_on` tuples both remain in dataset order. Assert v2 plan/schema serialization, exact 18/18 counts, and plan/dataset mismatch rejection. Add an explicit compatibility assertion that the no-plan result remains `indirect_injection_live_paired_result_v1` and has no `arm_order` key.

- [ ] **Step 2: Run RED runner tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_live_runner.py -k "arm_order or v1_result"`

Expected: failures because the v2 result and `arm_order` parameter do not exist.

- [ ] **Step 3: Add v2 result and mode-dispatched execution**

```python
class LivePairedResultV2(LivePairedResult):
    schema_version: Literal["indirect_injection_live_paired_result_v2"]
    arm_order: CounterbalancedArmOrderPlan


for case in dataset.cases:
    modes = (
        arm_order.assignment_for(case.case_id).modes()
        if arm_order is not None
        else ("off", "on")
    )
    evaluated = {
        mode: _evaluate_live_case(..., guard_mode=mode, ...)
        for mode in modes
    }
    off_case, off_observation = evaluated["off"]
    on_case, on_observation = evaluated["on"]
```

Validate the plan case set before constructing the pipeline or invoking the model. Build the existing security summaries from the mode-specific arrays exactly as before.

- [ ] **Step 4: Run runner GREEN tests and the existing runner file**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_live_runner.py`

Expected: new v2 tests and all prior v1/boundary tests pass.

---

### Task 3: Versioned Manifest and Per-Case Arm Evidence

**Files:**
- Modify: `app/evaluation/indirect_injection_live_writer.py`
- Modify: `tests/evaluation/test_indirect_injection_live_writer.py`

**Interfaces:**
- Consumes: `LivePairedResultV2.arm_order`.
- Produces: `LiveSecurityRunManifestV2` with schema `indirect_injection_live_security_run_manifest_v2`, mode `local_live_paired_counterbalanced`, and full `arm_order` plan.
- Produces: v2 `per_case.jsonl` rows with `arm_execution`, `security`, and `live`.
- Preserves: strict `LiveSecurityRunManifest` v1 parsing and old two-key per-case rows.

- [ ] **Step 1: Write failing writer tests**

Publish a v2 synthetic run and assert:

```python
assert manifest["arm_order"]["off_then_on_count"] == 18
assert manifest["arm_order"]["on_then_off_count"] == 18
assert set(rows[0]) == {"arm_execution", "security", "live"}
assert rows[0]["arm_execution"]["arm_position"] == 1
assert rows[1]["arm_execution"]["arm_position"] == 2
```

For every adjacent pair, verify case ID, hash, rank, declared order, positions,
and implied guard modes. Add a direct stage-row validation test that mutates an
arm position or swaps modes and expects rejection. Keep the existing v1
publication test unchanged as the compatibility test.

- [ ] **Step 2: Run RED writer tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_live_writer.py`

Expected: new tests fail because the v2 manifest and row evidence do not exist.

- [ ] **Step 3: Implement schema-dispatched publication and validation**

Subclass the v1 manifest for additive v2 fields. Reject v1/v2 manifest-result
mixes in `_validate_consistency`. For v2 rows, map mode-specific result arrays
by case ID, then emit each pair in `assignment.modes()` order:

```python
for position, mode in enumerate(assignment.modes(), start=1):
    rows.append({
        "arm_execution": {
            "protocol_id": plan.protocol_id,
            "case_hash": assignment.case_hash,
            "hash_rank": assignment.hash_rank,
            "arm_order": assignment.arm_order,
            "arm_position": position,
        },
        "security": security_by_mode[mode][case_id].model_dump(mode="json"),
        "live": live_by_mode[mode][case_id].model_dump(mode="json"),
    })
```

Select `type(manifest).model_validate(...)` when adding artifact evidence and
when round-tripping the final manifest. Keep `_ARTIFACT_NAMES` unchanged.

- [ ] **Step 4: Run writer GREEN tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_live_writer.py`

Expected: both v1 and v2 publication paths pass.

---

### Task 4: Make the Future CLI Protocol Explicit and Non-Overwritable

**Files:**
- Modify: `scripts/eval_indirect_injection_live.py`
- Modify: `tests/evaluation/test_indirect_injection_live_cli.py`

**Interfaces:**
- Consumes: `build_counterbalanced_arm_order_plan` and v2 runner/writer models.
- Produces: every new CLI run as a v2 counterbalanced artifact.
- Enforces: `r2-s1-d7-test-20260718-01` cannot be requested as a new run ID.

- [ ] **Step 1: Write failing CLI tests**

Extend the completed synthetic run test to assert v2 schema/mode, 18/18 plan
counts, 36 assignments, and 72 per-case rows with exact arm evidence. Add a
test that invokes `main()` with the formal D7 run ID and expects rejection
before frozen-data, model, or index work.

- [ ] **Step 2: Run RED CLI tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_live_cli.py`

Expected: v2 assertions fail and the formal run ID is not yet explicitly rejected.

- [ ] **Step 3: Wire the plan through CLI, runner, and manifest**

Build the plan from `bundle.dataset.cases`, pass it to `evaluate_live_paired`,
and make `_build_manifest` return `LiveSecurityRunManifestV2` with the same plan.
Update the description and paired evidence to say this is a future
counterbalanced run. Do not add a fixed-order fallback switch.

- [ ] **Step 4: Run CLI GREEN tests**

Run: `python -m pytest -q tests/evaluation/test_indirect_injection_live_cli.py`

Expected: all CLI tests pass without real network/model calls.

---

### Task 5: Documentation, Compatibility Proof, and Final Verification

**Files:**
- Modify: `docs/security/r2_s1/04_evaluation_protocol.md`
- Modify: `docs/security/r2_s1/05_results.md`
- Modify: `docs/security/r2_s1/09_d7_engineering_journal.md`
- Create: `docs/security/r2_s1/15_v5_counterbalanced_arm_order_engineering_journal.md`
- Modify: `README.md`
- Modify: `PROJECT_STATUS.md`

**Interfaces:**
- Documents: historical fixed OFF-first v1 versus future counterbalanced v2.
- Records: RED failures, GREEN results, obstacles, exact commands, frozen hashes, and interview explanations.

- [ ] **Step 1: Update protocol and historical-result labels**

State that formal D7 is a fixed OFF-first observational run. Describe v2
SHA-256 rank alternation, exact even-cohort balance, cohort-stability trade-off,
manifest plan, per-row arm evidence, and non-causal limitations. Do not change
the public package bytes.

- [ ] **Step 2: Run focused and expanded regressions**

Run:

```text
python -m pytest -q tests/evaluation/test_indirect_injection_arm_order.py
python -m pytest -q tests/evaluation/test_indirect_injection_live_runner.py tests/evaluation/test_indirect_injection_live_writer.py tests/evaluation/test_indirect_injection_live_cli.py
python -m pytest -q tests/security tests/evaluation tests/retrieval/test_indirect_injection_red_baseline.py
```

Expected: all pass; only the three known FAISS SWIG warnings may remain.

- [ ] **Step 3: Run full repository and static health checks**

Run:

```text
python -m pytest -q
python -m compileall -q app scripts tests
python -m pip check
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 4: Prove frozen and public evidence remain unchanged**

Verify the expected frozen hashes, including formal manifest
`5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e`.
Run the repository verifier and a copy of the eight-file public package in a
clean temporary directory. Run `scripts.audit_public_repo` and require zero
findings.

- [ ] **Step 5: Complete the V5 engineering journal**

Record exact code locations, the distinction between execution order and
result ordering, why v2 was additive, RED error messages, implementation
obstacles, final test counts, hashes, limitations, and interview questions
with defensible answers.

- [ ] **Step 6: Stop without Git writes**

Show `git status --short`, confirm `.superpowers/` and unrelated dirty files
were not touched, and wait for explicit approval before staging or committing.
