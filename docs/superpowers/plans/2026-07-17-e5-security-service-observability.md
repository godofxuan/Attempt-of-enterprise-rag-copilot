# E5 Security, Service Runtime, and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the local Enterprise Agentic RAG service tested lifecycle/readiness, request correlation, bounded model transport, safe telemetry, private feedback persistence, deterministic CI, and reproducible load evidence.

**Architecture:** Keep one FastAPI process and add small typed boundaries around request context, resource readiness, transport, telemetry, errors, and load artifacts. ContextVar correlates API, model calls, trace, metrics, and errors; default stores are bounded in memory and never retain content. Live dependencies may be unavailable while liveness remains healthy and readiness fails closed.

**Tech Stack:** Python 3.11, FastAPI 0.136, Pydantic 2, requests, SQLite, FAISS, Ollama, pytest, GitHub Actions.

## Global Constraints

- Exact approval: `批准E4，执行E5安全、服务与可观测性`.
- Workspace stays `<repo-root>`; E0-E4 uncommitted prerequisites make a HEAD-only worktree unusable.
- HEAD remains `7aec4b950e012d3f24b8e1877d6391201e9b8f90`; commit/push/merge/tag/default-branch changes are not authorized.
- Every production behavior follows RED -> observed expected failure -> minimal GREEN -> related regression.
- Never run two pytest processes concurrently because the pre-E5 config shares one basetemp; change that config only in Task 7.
- CI and unit tests never call Ollama. Live checks run only after deterministic gates.
- Telemetry must not persist question, answer, prompt, messages, tenant, groups, user ID, doc/chunk/path/title/ACL, or model response body.
- ACL remains pre-fusion. No test or ablation may disable it.
- No OpenTelemetry collector, Prometheus, Redis, Docker, Kubernetes, real IAM, distributed cancellation, or production SLA claim.
- Existing E4 frozen test hash and evaluator parameters remain unchanged.

---

### Task 1: Request Context and Runtime Settings

**Files:**
- Create: `app/runtime/__init__.py`
- Create: `app/runtime/request_context.py`
- Modify: `app/config.py`
- Test: `tests/runtime/test_request_context.py`
- Test: `tests/runtime/test_settings.py`

**Interfaces:**
- Produces: `RequestContext`, `bind_request_context()`, `reset_request_context()`, `current_request_context()`, `current_request_id()`, `remaining_seconds()`, `effective_timeout_seconds()`.
- Produces settings: `api_request_deadline_ms`, `model_request_timeout_seconds`, `model_max_attempts`, `model_retry_backoff_ms`, `structured_generation_max_attempts`, `readiness_probe_timeout_seconds`, `readiness_ttl_seconds`, `trace_buffer_size`, `metrics_latency_buffer_size`, `sqlite_timeout_seconds`.

- [x] **Step 1: Write request context RED tests**

```python
def test_bind_exposes_request_id_and_deadline_then_reset_isolates_next_request():
    token = bind_request_context("req-one", deadline_ms=1_000, clock_ms=lambda: 100.0)
    assert current_request_id() == "req-one"
    assert remaining_seconds(clock_ms=lambda: 350.0) == 0.75
    reset_request_context(token)
    assert current_request_context() is None

def test_effective_timeout_uses_smaller_request_remainder():
    token = bind_request_context("req", deadline_ms=500, clock_ms=lambda: 0.0)
    assert effective_timeout_seconds(12.0, clock_ms=lambda: 300.0) == 0.2
    reset_request_context(token)
```

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/runtime/test_request_context.py tests/runtime/test_settings.py -q`

Expected: collection fails because `app.runtime.request_context` and new settings do not exist.

- [x] **Step 3: Implement typed context and validated settings**

Use one ContextVar whose default is `None`. Context records safe counters/spans but no body data. Settings use Pydantic bounds so attempts are 1-3, deadlines 100-300000ms, buffers 10-10000, and probe/SQLite timeouts are positive.

- [x] **Step 4: Run GREEN and config regression**

Run: `python -m pytest tests/runtime/test_request_context.py tests/runtime/test_settings.py tests/evaluation/test_runtime.py -q`

Expected: all pass.

- [x] **Step 5: Record checkpoint**

Update `docs/roadmap/e5_security_service_observability_implementation.md`; do not commit.

### Task 2: Bounded Traces and Metrics

**Files:**
- Create: `app/observability/__init__.py`
- Create: `app/observability/tracing.py`
- Create: `app/observability/metrics.py`
- Test: `tests/observability/test_tracing.py`
- Test: `tests/observability/test_metrics.py`

**Interfaces:**
- Produces: strict `SpanRecord`, `RequestTrace`, `TraceSink`, `InMemoryTraceStore`, `trace_span()`.
- Produces: `MetricsRegistry.request_started()`, `request_finished()`, `snapshot()` and `process_rss_bytes()`.
- Consumes: current `RequestContext` from Task 1.

- [x] **Step 1: Write trace RED tests**

Test maxlen eviction, get-by-request-ID, span allowlist, ContextVar isolation, and serialized absence of seeded secrets/question/tenant/doc fields.

- [x] **Step 2: Write metrics RED tests**

Test request/in-flight/error/model counters, nearest-rank p50/p95, bounded latency samples, route normalization, and injected memory provider.

- [x] **Step 3: Run RED**

Run: `python -m pytest tests/observability/test_tracing.py tests/observability/test_metrics.py -q`

Expected: module-not-found failures.

- [x] **Step 4: Implement minimal thread-safe stores**

Use `deque(maxlen=...)` and `threading.Lock`. Accepted route labels are registered templates or `__unmatched__`; span names are a fixed Literal/allowlist. Metrics snapshot reports count/sum/p50/p95 and safe process RSS only.

- [x] **Step 5: Run GREEN and security trace regression**

Run: `python -m pytest tests/observability tests/security/test_trace_redaction.py tests/security/test_agent_trace_zero_leak.py -q`

Expected: all pass.

- [x] **Step 6: Record checkpoint; do not commit**

### Task 3: Deadline-Aware Model Transport and Structured Retry

**Files:**
- Create: `app/runtime/model_transport.py`
- Modify: `app/ollama_chat.py`
- Modify: `app/retriever.py`
- Modify: `app/agent/generation_v2.py`
- Test: `tests/runtime/test_model_transport.py`
- Modify test: `tests/test_ollama_chat.py`
- Modify test: `tests/agent_v2/test_generation_v2.py`

**Interfaces:**
- Produces: `ModelRequestError(code, status_code, retryable, attempts)` and `perform_model_request(send, operation, timeout_seconds, max_attempts, backoff_seconds, sleeper, clock)`.
- Consumes: request deadline and telemetry counters from Task 1.
- `chat_with_ollama()` and `_embed_text()` keep their public signatures.

- [x] **Step 1: Write transport RED tests**

Cover successful first attempt, retry of 503/timeout, no retry for 400, deadline exhausted before send, backoff exceeding remainder, safe exception serialization, and exact timeout passed to `send`.

- [x] **Step 2: Run transport RED**

Run: `python -m pytest tests/runtime/test_model_transport.py -q`

Expected: module-not-found.

- [x] **Step 3: Implement shared bounded transport**

Retry only timeout/connection and 429/502/503/504. Never include response body, URL or input in `ModelRequestError`. Record operation attempt spans in current request context.

- [x] **Step 4: Write adapter RED tests**

Update old hardcoded timeout assertion to settings-driven timeout. Add chat/embed tests proving request remainder wins and 400 is attempted once.

- [x] **Step 5: Adapt chat and embed, then run GREEN**

Run: `python -m pytest tests/runtime/test_model_transport.py tests/test_ollama_chat.py tests/indexing/test_legacy_adapter.py -q`

- [x] **Step 6: Write structured generation retry RED**

```python
def test_invalid_first_json_gets_one_bounded_shape_retry():
    chat = SequencedChat(["not-json", valid_payload()])
    response = GenerationV2ResponseBuilder(chat_fn=chat, model="m", max_attempts=2).build(...)
    assert response.mode == "answered"
    assert len(chat.calls) == 2
    assert response.trace["generation_attempts"] == 2
```

Also assert two invalid shapes return source-free `system`, transport errors are not retried by the builder, and max attempts is never exceeded.

- [x] **Step 7: Implement shape-only retry and run GREEN**

Run: `python -m pytest tests/agent_v2/test_generation_v2.py tests/evaluation -q`

- [x] **Step 8: Record checkpoint; do not commit**

### Task 4: Runtime Resources, SQLite Privacy, and Lifespan

**Files:**
- Create: `app/runtime/resources.py`
- Modify: `app/db.py`
- Test: `tests/runtime/test_resources.py`
- Test: `tests/api_v2/test_feedback_privacy.py`

**Interfaces:**
- Produces: `ReadinessSnapshot`, `RuntimeResources.start()`, `refresh_if_stale()`, `snapshot()`, `close()`.
- Produces DB functions: `init_db()`, `check_db()`, `save_feedback_metadata(question, answer, helpful, request_id)`.
- Resource probes are constructor-injected for deterministic tests.

- [x] **Step 1: Write resource RED tests**

Test all-ready metadata, one failed dependency -> safe not-ready code, no exception text/path, TTL caching, force refresh, and close idempotence.

- [x] **Step 2: Write feedback privacy RED tests**

Use temp SQLite. Submit seeded question/answer secrets; query all tables and assert plaintext is absent while 64-char SHA256, request ID and helpful are present.

- [x] **Step 3: Run RED**

Run: `python -m pytest tests/runtime/test_resources.py tests/api_v2/test_feedback_privacy.py -q`

- [x] **Step 4: Implement resources and DB migration**

Index probe uses `V2IndexSnapshot.load`; model probe calls `/api/tags` with short timeout and matches optional `:latest`; DB uses `feedback_events`. Keep old table untouched and stop new writes to it.

- [x] **Step 5: Run GREEN plus indexing regression**

Run: `python -m pytest tests/runtime/test_resources.py tests/api_v2/test_feedback_privacy.py tests/indexing tests/security -q`

- [x] **Step 6: Record checkpoint; do not commit**

### Task 5: Unified Errors, Middleware, Health, and Observability API

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/errors.py`
- Create: `app/api/middleware.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Create tests: `tests/api_v2/test_health.py`
- Create tests: `tests/api_v2/test_request_context_api.py`
- Create tests: `tests/api_v2/test_errors.py`
- Create tests: `tests/api_v2/test_observability_api.py`
- Modify tests: `tests/agent_v2/test_api_v2.py`
- Modify tests: `tests/security/test_api_v2_zero_leak.py`

**Interfaces:**
- Produces: `ApiError`, `ApiErrorResponse`, handler installer, `RequestContextMiddleware`, `create_app()` and global `app`.
- Consumes: resources/metrics/traces from Tasks 1-4.

- [x] **Step 1: Write health/lifespan RED tests**

Use a fake `RuntimeResources`. Assert `/health/live` never refreshes probes, `/health/ready` maps ready to 200 and not-ready to 503, `/health` remains 200 alias, and lifespan calls start/close exactly once.

- [x] **Step 2: Write request/error RED tests**

Assert valid incoming request ID is preserved; invalid/oversized ID is replaced; header equals `AnswerResponse.trace.request_id`; 422 and generic 500 bodies use the unified model and never echo seeded secret/path.

- [x] **Step 3: Write observability RED tests**

Assert metrics/traces endpoints expose aggregates only, unknown trace is generic 404, bounded trace eviction works through API, and seeded question/identity/title never appears.

- [x] **Step 4: Run RED**

Run: `python -m pytest tests/api_v2 -q`

Expected: missing modules/routes/contracts.

- [x] **Step 5: Implement app factory, lifespan, handlers, middleware, routes**

Construct stores/resources without IO at import. Lifespan performs start/close. Remove `@app.on_event`. Endpoint functions no longer return `str(exc)`. Wrap `agent.run` and `feedback.persist` in allowed spans. V2 response adds request ID after runner output without adding question/identity.

- [x] **Step 6: Run GREEN and legacy API regression**

Run: `python -m pytest tests/api_v2 tests/agent_v2/test_api_v2.py tests/security/test_api_v2_zero_leak.py tests/test_agent_api.py -q`

- [x] **Step 7: Run complete security regression**

Run: `python -m pytest tests/security tests/evaluation/test_security.py -q`

- [x] **Step 8: Record checkpoint; do not commit**

### Task 6: Reproducible Load Profile Artifacts

**Files:**
- Create: `scripts/load_profile.py`
- Create: `tests/observability/test_load_profile.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: parser with `--base-url`, `--profile`, `--concurrency`, `--requests-per-level`, `--run-id`, `--out-dir`, `--timeout-seconds`.
- Produces: immutable `manifest.json`, `summary.json`, `details.csv` under `load_runs/<run-id>`.

- [x] **Step 1: Write load profiler RED tests**

Test concurrency parsing/validation, nearest-rank percentile, cold/warm separation, failure accounting, safe details schema, existing target refusal, staging cleanup, and manifest hashes. Use injected fake HTTP callable; no server/Ollama.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/observability/test_load_profile.py -q`

- [x] **Step 3: Implement minimal profiler and writer**

Use `ThreadPoolExecutor`, `time.perf_counter`, requests with `trust_env=False`, UTF-8 JSON and UTF-8-BOM CSV. Read readiness/metrics before and after. Do not persist payload or response body.

- [x] **Step 4: Run GREEN and CLI help**

Run: `python -m pytest tests/observability/test_load_profile.py -q`

Run: `python -m scripts.load_profile --help`

Expected: help exits 0 and does not create `load_runs`.

- [x] **Step 5: Add `load_runs/` to ignore and record checkpoint**

Do not run live load until Task 8 deterministic gates pass.

### Task 7: Deterministic CI and Dependency/Test Configuration

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `requirements.txt`
- Modify: `pytest.ini`
- Create: `tests/test_repository_config.py`

**Interfaces:**
- CI uses Python 3.11, official checkout/setup-python, pip cache, pip check, compileall, frozen hash check, and full pytest.

- [x] **Step 1: Capture installed direct dependency versions**

Run `python -m pip show` for every direct requirement. Use exact versions already proven by the local 462-test baseline; do not add psutil.

- [x] **Step 2: Write repository config RED tests**

Assert `pytest.ini` does not point basetemp into repository data, workflow exists, uses Python 3.11, contains no Ollama/live command, and runs full pytest/frozen hash check.

- [x] **Step 3: Run RED**

Run: `python -m pytest tests/test_repository_config.py -q`

- [x] **Step 4: Pin direct requirements, remove shared basetemp, add CI**

Use system pytest temp. Workflow permissions are `contents: read`; no secrets, services, network model pull, live eval or load profile.

- [x] **Step 5: Run GREEN, pip check, compileall, and full tests**

Run sequentially:

```powershell
python -m pytest tests/test_repository_config.py -q
python -m pip check
python -m compileall -q app scripts tests
python -m pytest -q
```

- [x] **Step 6: Record checkpoint; do not commit**

### Task 8: Documentation, Live Profile, and Final Gates

**Files:**
- Create: `docs/security_threat_model.md`
- Create: `docs/reproducibility.md`
- Create: `docs/observability.md`
- Create: `docs/roadmap/e5_security_service_observability_implementation.md`
- Create: `docs/roadmap/e5_beginner_learning_and_interview.md`
- Modify: `docs/api.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`

**Interfaces:**
- Documents exact contracts, commands, results, incidents, residual risks, interview Q&A, and links to immutable artifacts.

- [x] **Step 1: Start hidden local uvicorn for live evidence**

Use a free port, redirect stdout/stderr to ignored log files, record PID, and wait for `/health/live`. Never use `--reload` for load evidence.

- [x] **Step 2: Verify live/ready and run one real v2 smoke**

Require ready 200 with the active bge-m3 index. Send one authorized fact query; assert request ID header equals response trace and no secret fields appear.

- [x] **Step 3: Run live load profile**

```powershell
python -m scripts.load_profile --profile demo --concurrency 1,5,10 \
  --requests-per-level 10 --run-id 20260716T165304Z_7aec4b9_demo_load
```

If hardware/model limits cause failures, preserve the artifact and report them; do not tune until they disappear.

- [x] **Step 4: Stop only the uvicorn PID started in Step 1**

Verify no project Python/pytest/pip process remains. Do not stop the user's pre-existing Ollama service.

- [x] **Step 5: Write threat model, reproducibility, observability, implementation journal, and beginner/interview guide**

Reference official FastAPI lifespan, OWASP prompt-injection/system-prompt guidance, OpenTelemetry signal/context concepts, and GitHub Actions Python guidance. Clearly separate borrowed principles from local implementation.

- [x] **Step 6: Run final deterministic gates fresh**

```powershell
python -m pytest tests/api_v2 tests/observability tests/security -q
python -m pytest tests/evaluation -q
python -m pytest -q
python -m pip check
python -m compileall -q app scripts tests
git diff --check
```

Also verify frozen test hash, load artifact hashes, active index load, project background 0, and Git lock false.

- [x] **Step 7: Update handoff and stop at E5 acceptance**

Mark implementation complete but human acceptance pending. Do not enter E6. The only next stage command is `批准E5，执行E6演示与公开仓库收口`.

## Plan Self-Review

- Every E5 design requirement maps to a task.
- New production functions have a named RED test before implementation.
- Type names are consistent across tasks.
- CI and load modes are explicitly separated.
- No task asks for Ollama in CI.
- No task persists content in telemetry or feedback.
- Every implementation step contains concrete behavior and a verification command.
- Commit steps are replaced by explicit no-commit checkpoints because Git writes are not authorized.
