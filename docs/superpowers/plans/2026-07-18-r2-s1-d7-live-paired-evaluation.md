# R2-S1 D7 Local Live Paired Evaluation Implementation Plan

> **Execution mode:** Follow the already approved D1 design with test-driven development. D7 is a local observational study, not a CI release gate and not a claim of universal model safety.

**Status:** Completed locally. The frozen test was run once; verification and local Git delivery are complete. Nothing was pushed by D7.

**Goal:** Run the frozen 36-case test split through the production retrieval, Guard, Agent and generation boundaries twice with real local BGE-M3 and Qwen models, changing only Guard OFF versus ON, and publish an immutable, redacted, reproducible result bundle.

**Architecture:** Build a temporary security-fixture index from the frozen post-parser fixtures. Every fixture candidate becomes a canonical index record and receives an evaluator-only `policy_id=case_id`, so the production `HybridRetrievalPipeline` calls BGE-M3 and ranks only that case's frozen candidate set. Both arms share the same index snapshot, case order, retrieval configuration, Qwen adapter and prompt nonce schedule. A recording chat adapter adds an inert evaluator system canary, records counts/latency/error classes without persisting prompts, and calls the normal structured-output generation path. A local egress boundary permits only the configured loopback Ollama origin and blocks/counts every other HTTP or socket destination.

**Evidence boundary:** The checked-in production active-index pointer and manifest are hashed as environment provenance but are not contaminated with synthetic attack documents. The run's actual retrieval source is the separately hashed temporary security index. Results report model behavior observed in this exact run; Guard OFF model resistance is not credited as a software-boundary success.

## Global Constraints

- D1 threat model and `docs/security/r2_s1/04_evaluation_protocol.md` remain unchanged.
- Test dataset and fixture bytes must verify against the D1 freeze manifest before any model call.
- `qwen2.5:3b`, `bge-m3`, Ollama identities/digests, Ollama version, endpoint, structured schema, temperature and budgets are recorded exactly.
- The allowed model endpoint must be loopback HTTP on the configured port. Redirects, proxies and non-loopback hosts are rejected.
- OFF exists only through evaluator dependency injection and cannot become an application setting or service endpoint.
- Raw prompts, retrieved text, model output, canaries, absolute paths, credentials and environment values never enter published artifacts.
- A completed live run can be `COMPLETED WITH OBSERVATIONS` even when attacks succeed or utility fails. Runtime/protocol incompleteness is `FAILED`; live behavior is data, not a hard release verdict.
- Runs are immutable: unique ID, same-parent staging, no overwrite/force option.

---

### Task 1: Freeze live contracts and fixture-index projection

**Files:**
- Create: `app/evaluation/indirect_injection_live_index.py`
- Test: `tests/evaluation/test_indirect_injection_live_index.py`

- [x] Write failing tests for exact model identity, loopback endpoint validation, fixture-to-document/chunk projection, parent/open preservation, per-case policy isolation, deterministic index fingerprints and no mutation of the production active index.
- [x] Confirm RED before implementation.
- [x] Implement the smallest strict contracts and BGE-M3-backed temporary index builder.
- [x] Confirm GREEN and validate the built index through `V2IndexSnapshot.load`.

### Task 2: Implement real Qwen paired execution

**Files:**
- Create: `app/evaluation/indirect_injection_live_runner.py`
- Test: `tests/evaluation/test_indirect_injection_live_runner.py`

- [x] Write failing tests using local fakes for OFF/ON input equality, actual production retrieval invocation, fresh nonce schedule, system-canary injection, structured retries, model-call counters, redacted error classes and local-only egress enforcement.
- [x] Confirm RED before implementation.
- [x] Implement the recording Qwen adapter and paired runner over the existing Agent V2/Guard stack.
- [x] Reuse D6 metric definitions while adding live completion, latency, call-count and paired-input consistency evidence.
- [x] Confirm GREEN and rerun D4-D6 security regressions.

### Task 3: Implement immutable live artifacts and CLI

**Files:**
- Create: `app/evaluation/indirect_injection_live_writer.py`
- Create: `scripts/eval_indirect_injection_live.py`
- Test: `tests/evaluation/test_indirect_injection_live_writer.py`
- Test: `tests/evaluation/test_indirect_injection_live_cli.py`

- [x] Write failing tests for preflight-before-model-call, model/index/git provenance, exact artifact set, no overwrite, redaction, checksums, observation-versus-protocol status and absence of a Guard-disable service switch.
- [x] Confirm RED before implementation.
- [x] Implement preflight, writer and an explicitly local/non-CI CLI.
- [x] Confirm GREEN, compile and audit the output schema.

### Task 4: Calibrate, run and record

**Files:**
- Generate ignored: `security_runs/<d7-dev-run-id>/...`
- Generate ignored: `security_runs/<d7-test-run-id>/...`
- Create: `docs/security/r2_s1/09_d7_engineering_journal.md`
- Modify: `docs/security/r2_s1/04_evaluation_protocol.md`
- Modify: `docs/security/r2_s1/05_results.md`
- Modify: `docs/roadmap/r2_s1_indirect_injection_implementation.md`
- Modify: `docs/superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `README.md`

- [x] Query Ollama version/model identities and run one embedding plus one structured-generation smoke test.
- [x] Run a small dev calibration; preserve every failure and add a regression test before fixing evaluator defects.
- [x] Run the complete dev split, then verify frozen test bytes again.
- [x] Run the complete test split once with a unique run ID; do not tune from frozen-test behavior.
- [x] Record metrics, paired differences, latency, errors, limitations, exact artifact hashes and interview explanations.

### Task 5: Verify and close locally

- [x] Run all D7 focused tests, D2-D6 security tests, the full repository suite, `compileall`, `pip check`, public-repository audit, `git diff --check`, frozen-hash checks and sensitive-output scans.
- [x] Confirm no project server/background evaluator remains; retain only the user's existing Ollama service.
- [x] Stage only D7-owned files, exclude `.superpowers/` and ignored live artifacts, commit locally and stop without pushing unless separately requested.
