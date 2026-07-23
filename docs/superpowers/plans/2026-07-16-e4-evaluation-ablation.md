# E4 Layered Evaluation and Ablation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one non-overwriting, provenance-rich evaluation protocol for retrieval, answer, Agent, security, ablation, failure attribution, and blank human review over the E1 v2 dataset.

**Architecture:** A new `app.evaluation` package owns typed contracts, metrics, runtime, layer evaluators, attribution, orchestration, and publication. CLI modules only parse arguments. Deterministic and live modes are explicit; legacy evaluators remain unchanged as regression evidence.

**Tech Stack:** Python 3.11, Pydantic v2, FAISS, rank-bm25, NumPy, pytest, standard-library CSV/JSON/hashlib/subprocess/tempfile, existing E1/E2/E3 contracts.

## Global Constraints

- E4 is approved by exact command `批准E3，执行E4评估与消融`.
- Production behavior changes follow RED -> minimal GREEN -> focused regression.
- Use `data/v2/eval/dev.json` during implementation; do not read `test.json` until C07 formal run.
- Validate frozen test SHA256 before the formal test run; never overwrite or relabel test.
- Deterministic mode uses fixed 500/80 chunks, stable hash 128D embedding, extractive response, and zero model calls.
- Live mode is explicit and never silently falls back to deterministic.
- ACL and authority invariants stay enabled in every ablation.
- Details and failures must not contain forbidden IDs, ACL groups, chunk text, prompts, or raw trace.
- Every run directory is new; no `--force` exists.
- Codex may prefill review context but must leave all human judgement columns blank.
- Legacy evaluator code/results remain unchanged.
- No reranker is added without an admission result; absent reranker is `not_run`.
- No commit, push, merge, tag, default-branch change, or repository rename without separate user authorization.
- Update `docs/roadmap/e4_evaluation_ablation_implementation.md` and `CURRENT_EXECUTION_HANDOFF.md` after every Change.

---

## File Structure

### Evaluation package

- Create `app/evaluation/__init__.py`: stable public exports only.
- Create `app/evaluation/contracts.py`: failure stages, rate/CI, layer/case/run/ablation models.
- Create `app/evaluation/metrics.py`: unique-document ranking metrics, rates, latency, bootstrap.
- Create `app/evaluation/attribution.py`: deterministic primary/secondary stage selection.
- Create `app/evaluation/run_manifest.py`: safe Git/data/index/runtime provenance.
- Create `app/evaluation/writer.py`: atomic non-overwriting artifact publication.
- Create `app/evaluation/runtime.py`: deterministic and live runtime construction.
- Create `app/evaluation/retrieval.py`: retrieval observations and layer scoring.
- Create `app/evaluation/answer.py`: fact/citation/mode scoring.
- Create `app/evaluation/agent.py`: intent/tool/retry/budget/stop/trace scoring.
- Create `app/evaluation/security.py`: ACL/injection/trace/budget security scoring.
- Create `app/evaluation/suite.py`: one-pass orchestration and grouping.
- Create `app/evaluation/ablation.py`: controlled retrieval/workflow variants.
- Create `app/evaluation/human_review.py`: 30-50-row blank review export.

### CLI and docs

- Create `scripts/eval_enterprise_v2.py`.
- Create `scripts/eval_ablation_v2_enterprise.py`.
- Create `docs/evaluation.md`.
- Create `docs/ablation_report.md` after measured runs.
- Modify `.gitignore` only if `eval_runs/` is not already ignored; current audit says it is already present.

### Tests

- Create `tests/evaluation/conftest.py`.
- Create focused test files matching each production module.
- Reuse `tests/v2_test_support.py`; do not put production evaluator logic in test helpers.

---

### Task 1: E4-C01 Typed contracts and deterministic metrics

**Files:**
- Create: `app/evaluation/__init__.py`
- Create: `app/evaluation/contracts.py`
- Create: `app/evaluation/metrics.py`
- Test: `tests/evaluation/test_contracts.py`
- Test: `tests/evaluation/test_metrics.py`

**Interfaces:**
- Produces: `FailureStage`, `FailureSignal`, `ConfidenceInterval`, `RateMetric`, `LayerResult`, `EvaluationCaseResult`, `EvaluationRunResult`, `AblationRow`.
- Produces: `unique_ranked_doc_ids`, `document_metrics`, `rate_metric`, `percentiles`, `bootstrap_rate_ci`.

- [ ] **Step 1: Write contract import/validation RED**

Tests must assert strict extra-field rejection, unique failure signals, `passed=False` when applicable failures exist, `rate=None` for total 0, and CI bounds/order. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_contracts.py -q
```

Expected RED: `ModuleNotFoundError: app.evaluation`.

- [ ] **Step 2: Implement minimal strict Pydantic contracts**

Use one `StrictModel` with `extra="forbid"`. `EvaluationCaseResult` must reject forbidden-output fields by schema rather than relying on callers.

- [ ] **Step 3: Write document-metric RED**

Cases: duplicate chunks from one doc, two-doc gold partial/full recall, invalid extras, delayed first hit, empty gold, deterministic bootstrap.

- [ ] **Step 4: Implement metrics**

`unique_ranked_doc_ids` preserves first rank. Precision denominator remains k; relevant docs cannot be counted twice. Bootstrap uses `random.Random(seed)` and percentile indices, with n/iterations/seed/method in output.

- [ ] **Step 5: Run focused and existing metric regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_contracts.py tests\evaluation\test_metrics.py tests\test_eval_metrics.py -q
```

Expected: all pass; legacy `app.eval_metrics` unchanged.

---

### Task 2: E4-C01 Failure attribution, provenance, and writer

**Files:**
- Create: `app/evaluation/attribution.py`
- Create: `app/evaluation/run_manifest.py`
- Create: `app/evaluation/writer.py`
- Test: `tests/evaluation/test_attribution.py`
- Test: `tests/evaluation/test_run_manifest.py`
- Test: `tests/evaluation/test_writer.py`

**Interfaces:**
- Produces: `attribute_failures(signals) -> tuple[FailureStage | None, list[FailureStage]]`.
- Produces: `build_run_manifest(config, dataset, runtime, artifacts) -> RunManifest`.
- Produces: `publish_run(root, run_id, result, ablation_rows=(), human_review_rows=()) -> Path`.

- [ ] **Step 1: Write deterministic attribution RED**

Assert earliest-stage priority, duplicate collapse, original signal retention, and `None/[]` for no failure.

- [ ] **Step 2: Implement priority mapping from approved design**

No LLM calls and no message-text parsing for stage selection.

- [ ] **Step 3: Write provenance RED**

Use temporary Git/data/index fixtures. Assert actual non-sensitive values exist, API key/env values do not, dirty state is explicit, and missing optional index is represented as `status="not_available"`.

- [ ] **Step 4: Implement provenance**

Use `subprocess.run(..., check=False, capture_output=True, text=True, encoding="utf-8")`. Hash bytes, not decoded text. Package versions come from `importlib.metadata` allowlist.

- [ ] **Step 5: Write writer RED**

Assert required six files, existing target refusal, unsafe run IDs, target containment, canonical JSONL, UTF-8 BOM CSV, staging cleanup, artifact hashes, and one transient `PermissionError` retry.

- [ ] **Step 6: Implement atomic writer**

Resolve root/target, create sibling staging, write/validate artifacts, write manifest last, then rename with five bounded retries. Never expose a force flag.

- [ ] **Step 7: Run C01 suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_contracts.py tests\evaluation\test_metrics.py tests\evaluation\test_attribution.py tests\evaluation\test_run_manifest.py tests\evaluation\test_writer.py -q
```

---

### Task 3: Shared evaluation runtime

**Files:**
- Create: `app/evaluation/runtime.py`
- Test: `tests/evaluation/test_runtime.py`
- Modify: `scripts/eval_agent_v2_dev.py` only if replacing duplicated deterministic helpers is behavior-neutral and covered; otherwise leave legacy E3 script unchanged.

**Interfaces:**
- Produces: `EvaluationRuntime(snapshot, pipeline, navigator, runner, budget, mode, variant, model_calls)`.
- Produces: `deterministic_runtime(corpus_dir, temp_root, budget) -> EvaluationRuntime`.
- Produces: `live_runtime(settings) -> EvaluationRuntime`.

- [ ] **Step 1: Write deterministic runtime RED**

Build a temporary E2 index from a tiny corpus, assert manifest/chunk config, stable embedding equality, runnable search/Agent, and model_calls 0.

- [ ] **Step 2: Implement deterministic runtime**

Move or reproduce only the E3 builder boundary: fixed 500/80, hash-128, `HybridRetrievalPipeline`, `DocumentNavigator`, `V2ToolRegistry`, `V2AgentRunner` with extractive builder.

- [ ] **Step 3: Write live precondition RED**

Absent active v2 index must raise a typed runtime error; it must not build deterministic fallback.

- [ ] **Step 4: Implement live runtime**

Load `settings.v2_indexes_dir`, use configured embedding/chat model and `GenerationV2ResponseBuilder`; redact API key from runtime metadata.

- [ ] **Step 5: Run runtime and E3 compatibility tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_runtime.py tests\agent_v2\test_eval_agent_v2_dev.py -q
```

---

### Task 4: E4-C02 Retrieval evaluator

**Files:**
- Create: `app/evaluation/retrieval.py`
- Test: `tests/evaluation/test_retrieval.py`

**Interfaces:**
- Consumes: `EvalCase`, `EvaluationRuntime`, retrieval variant, top-k/candidate-k.
- Produces: `RetrievalObservation` and retrieval `LayerResult` with safe visible doc IDs.

- [ ] **Step 1: Write retrieval RED**

Cover multi-chunk same doc, two-doc comparison, authority replacement, invalid extra docs, forbidden result, no-gold not-applicable, metadata filter, and latency/context counters.

- [ ] **Step 2: Implement one-shot observation**

Use `RuleFirstQueryAnalyzer` only for filters in metadata variants. Base retrieval variants query the original question once so decomposition remains an Agent-layer feature.

- [ ] **Step 3: Implement document metrics and failure signals**

Map no gold to `applicable=False`. ACL leakage is always applicable and produces stage `acl`. Missing all gold is retrieval; gold present but ranked below k is ranking; authority replacement is conflict resolution/metadata as appropriate.

- [ ] **Step 4: Run focused and E3 retrieval regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_retrieval.py tests\retrieval tests\security -q
```

---

### Task 5: E4-C03 Answer evaluator

**Files:**
- Create: `app/evaluation/answer.py`
- Test: `tests/evaluation/test_answer.py`

**Interfaces:**
- Consumes: `EvalCase`, `AnswerResponse`, `snapshot.chunks_by_id`.
- Produces: answer `LayerResult` and fact/citation observations.

- [ ] **Step 1: Write answer RED**

Cases: perfect answered, correct mode but missing fact, citation not visible, unsupported claim, wrong authority in version conflict, correct permission/not-found source-free, partial with measurable coverage, lexical signal disagreement.

- [ ] **Step 2: Implement fact coverage from cited chunk IDs**

Union `fact_ids` only from chunks actually cited by claims. Retrieved but uncited chunks do not count.

- [ ] **Step 3: Implement citation/refusal/conflict metrics**

Correctness hard gate uses mode + full required fact coverage + supported critical claims. `expected_answer_signal` is separately named heuristic.

- [ ] **Step 4: Run focused and domain regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_answer.py tests\domain_v2\test_evidence_models.py tests\agent_v2\test_citation_verifier.py -q
```

---

### Task 6: E4-C03 Agent evaluator

**Files:**
- Create: `app/evaluation/agent.py`
- Test: `tests/evaluation/test_agent.py`

**Interfaces:**
- Consumes: `EvalCase`, `AnswerResponse`, `AgentBudget`.
- Produces: agent `LayerResult`, tool sequence, tool counts, context chars, latency-compatible stop checks.

- [ ] **Step 1: Write Agent RED**

Cover acceptable intent sets, comparison two-search decomposition, completeness open, unsafe zero-tool, missing trace key, non-contiguous sequence, budget overrun, wrong stop reason, wrong outcome, and live exact-sequence non-gating behavior.

- [ ] **Step 2: Implement typed trace parser**

Reject malformed aggregate trace without reading raw prompts. Sequence must increase from 1; terminal step is included but not a tool call.

- [ ] **Step 3: Implement metrics/failure signals**

Use query_analysis, decomposition_rewrite, evidence_assessment, or system_runtime stages. Exact sequence is a reported deterministic contract only.

- [ ] **Step 4: Run focused and E3 Agent regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_agent.py tests\agent_v2\test_controller_v2.py tests\agent_v2\test_runner_v2.py -q
```

---

### Task 7: E4-C04 Security evaluator

**Files:**
- Create: `app/evaluation/security.py`
- Test: `tests/evaluation/test_security.py`

**Interfaces:**
- Produces: `SECURITY_PROBES`, `evaluate_case_security`, `evaluate_injection_probes`, `trace_is_redacted`.

- [ ] **Step 1: Write security RED**

Cover forbidden source, denied ID in nested trace, raw question/text/path key, source-bearing refusal, prompt injection bypass, nonzero tool call, and unbounded counter.

- [ ] **Step 2: Implement recursive trace contract check**

Use forbidden key names and explicit forbidden values supplied only in-memory. Returned failure messages use counts/codes, never forbidden values.

- [ ] **Step 3: Add four fixed probes**

Probes cover approval bypass, secret extraction, system instruction override, and unauthorized export. Save only probe IDs and aggregate results.

- [ ] **Step 4: Run security and legacy API regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_security.py tests\security tests\agent_v2\test_api_security.py -q
```

---

### Task 8: E4-C05 Unified suite and CLI

**Files:**
- Create: `app/evaluation/suite.py`
- Create: `scripts/eval_enterprise_v2.py`
- Test: `tests/evaluation/test_suite.py`
- Test: `tests/evaluation/test_eval_cli.py`

**Interfaces:**
- Produces: `evaluate_suite(cases, runtime, suite, config) -> EvaluationRunResult`.
- CLI: `--suite retrieval|answer|agent|security|all --split dev|test --mode deterministic|live --run-id --out-dir --top-k --candidate-k --bootstrap-iterations`.

- [ ] **Step 1: Write suite RED**

Assert runner called once per case for all-suite, retrieval-only never calls generation, layer applicability, grouped metrics by task/tag, failure attribution, rate n/CI, and safe details.

- [ ] **Step 2: Implement one-pass orchestrator**

Observe retrieval once, run Agent once where needed, fan out immutable observations, then summarize. Security probes run once per run.

- [ ] **Step 3: Write CLI RED**

`--help` has no filesystem side effects; missing required run ID fails; existing run fails; test hash mismatch fails before runtime construction; live precondition fails without fallback.

- [ ] **Step 4: Implement thin CLI**

Default output root is `eval_runs`. Print concise JSON summary and absolute run path. Do not accept force.

- [ ] **Step 5: Run C05 tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_suite.py tests\evaluation\test_eval_cli.py -q
```

---

### Task 9: E4-C06 Ablation and blank human review

**Files:**
- Create: `app/evaluation/ablation.py`
- Create: `app/evaluation/human_review.py`
- Create: `scripts/eval_ablation_v2_enterprise.py`
- Test: `tests/evaluation/test_ablation.py`
- Test: `tests/evaluation/test_human_review.py`

**Interfaces:**
- Produces: six retrieval variant rows plus fixed-vs-Agent rows.
- Produces: `build_human_review_rows(cases, case_results, min_rows=30, max_rows=50)` with blank judgement fields.

- [ ] **Step 1: Write ablation RED**

Assert same case IDs/config across variants; ACL never disabled; modes/filters/diversity/parent match design; reranker is not_run; quality/latency/model/tool/context columns exist.

- [ ] **Step 2: Implement retrieval variants without ranking duplication**

Construct `SearchRequest` variants and call the same production pipeline. Never copy BM25/dense/RRF implementation into evaluation code.

- [ ] **Step 3: Implement fixed-vs-Agent comparison**

Fixed RAG does one original-query production search and derives outcome from search stop reason; Agent uses E3 runner. Gold labels are used only for scoring after predictions.

- [ ] **Step 4: Write/implement human review RED**

Require 30-50 representative rows when enough cases exist, include machine context columns, and assert all eight human judgement fields are empty strings.

- [ ] **Step 5: Implement ablation CLI and run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation\test_ablation.py tests\evaluation\test_human_review.py -q
```

---

### Task 10: E4-C07 Dev audit, frozen test, documentation, and gates

**Files:**
- Create: `docs/evaluation.md`
- Create: `docs/ablation_report.md`
- Create: `docs/roadmap/e4_beginner_learning_and_interview.md`
- Modify: `docs/roadmap/e4_evaluation_ablation_implementation.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`

**Interfaces:**
- Produces immutable run directories using root `20260716T135632Z_7aec4b9` with unique suffixes.

- [ ] **Step 1: Run evaluation tests and all dev suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation -q
.\.venv\Scripts\python.exe -m scripts.eval_enterprise_v2 --suite all --split dev --mode deterministic --run-id 20260716T135632Z_7aec4b9_dev_suite
.\.venv\Scripts\python.exe -m scripts.eval_ablation_v2_enterprise --split dev --mode deterministic --run-id 20260716T135632Z_7aec4b9_dev_ablation
```

Record every metric and failure. Fix evaluator/system bugs using new run IDs; do not delete failed runs.

- [ ] **Step 2: Freeze development decisions**

Record code diff hash/status, dev results, chosen/default config, and explicit limitations. After this point, do not tune from test quality.

- [ ] **Step 3: Verify hash and run frozen test once**

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_enterprise_v2 --suite all --split test --mode deterministic --run-id 20260716T135632Z_7aec4b9_test_suite
.\.venv\Scripts\python.exe -m scripts.eval_ablation_v2_enterprise --split test --mode deterministic --run-id 20260716T135632Z_7aec4b9_test_ablation
```

If runtime invalidates a run, preserve it and use suffix `_retry01` only after documenting why. Never tune based on test score.

- [ ] **Step 4: Attempt explicit live dev only after active index audit**

If active v2 index and Ollama are available, run a separate `_live_dev` run. If not, mark NOT RUN with exact precondition; do not fallback or block deterministic E4 evidence.

- [ ] **Step 5: Generate blank 30-50 case review sheet**

Combine dev/test machine observations into an ignored `eval_runs/.../human_review.csv`. Confirm every human judgement cell is blank. E4 remains awaiting human review until the user fills it.

- [ ] **Step 6: Run repository gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\evaluation -q
.\.venv\Scripts\python.exe -m pytest tests\test_eval_metrics.py tests\test_answer_eval_metrics.py tests\test_agent_action_eval.py tests\test_agent_loop_eval.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
git diff --check
```

Also verify frozen hash, no Git lock, no project Python/pip background process, no overwritten run IDs, and no human judgements filled by Codex.

- [ ] **Step 7: Write learning/interview record and stop**

Explain every metric, denominator, CI, failure attribution, deterministic/live boundary, dev/test protocol, good/bad ablation result, incidents, and at least 20 interview questions with answers. Set handoff to `E4 implementation complete, awaiting user acceptance and human review`.

Stop before E5. Require exact command:

```text
批准E4，执行E5安全、服务与可观测性
```

Suggested future commit after separate approval is
`eval: add layered enterprise benchmark and ablation reports`.
