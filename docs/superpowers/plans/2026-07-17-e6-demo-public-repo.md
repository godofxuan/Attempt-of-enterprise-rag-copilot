# E6 Demo and Public Repository Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested three-page Streamlit interview demo backed by the real V2 API and a hash-traceable public evaluation snapshot, then make the local repository ready for public review without publishing Git changes.

**Architecture:** `ui.py` owns navigation and shared state; page scripts own presentation; typed helper modules own API, demo-case, and view-model behavior. Ask/Trace consume live FastAPI responses, while Evaluation consumes a checked-in canonical snapshot exported from immutable E4/E5 artifacts. Public and private materials have explicit filesystem and Git-ignore boundaries.

**Tech Stack:** Python 3.11, Streamlit 1.56, FastAPI/Pydantic 2, requests, pytest, Streamlit AppTest, Mermaid, browser Playwright screenshots.

## Global Constraints

- Exact approval: `批准E5，执行E6演示与公开仓库收口`.
- Design authority: `docs/superpowers/specs/2026-07-17-e6-demo-public-repo-design.md`.
- Workspace remains `<repo-root>`; E0-E5 uncommitted prerequisites require the current normal checkout.
- HEAD remains `7aec4b950e012d3f24b8e1877d6391201e9b8f90`; commit/push/merge/tag/default-branch/repository-rename operations are not authorized.
- Every production behavior change follows RED -> observed expected failure -> minimal GREEN -> regression.
- UI must never hardcode an answer, successful trace, or evaluation score; values come from the API, canonical eval cases, or public snapshot.
- Public snapshot must contain no absolute path, question, answer, identity, source preview, model body, or secret.
- `.private/` is ignored and never appears in public candidate files.
- Direct prompt injection is measured; indirect document injection remains `NOT RUN` because the current corpus lacks such a fixture.
- Screenshots must be generated from the final running UI and verified at 1440x1000 and 390x844.
- Stage end requires project Python/Streamlit/Uvicorn background 0 and Git index lock false.

---

### Task 1: Safe Evidence Summary in Agent Trace

**Files:**
- Modify: `app/agent/runner_v2.py`
- Modify tests: `tests/agent_v2/test_runner_v2.py`
- Regression: `tests/security/test_agent_trace_zero_leak.py`

**Interfaces:**
- Produces trace key `evidence` with exact fields `required`, `supported`, `missing`, `conflicting`, `coverage`, `recommended_action`.
- Consumes `ControllerState.ledger` or `build_ledger()` and never emits aspect names or evidence IDs.

- [x] **Step 1: Write evidence summary RED tests**

Add assertions to answered, comparison, no-match, and unsafe tests:

```python
assert response.trace["evidence"] == {
    "required": 1,
    "supported": 1,
    "missing": 0,
    "conflicting": 0,
    "coverage": 1.0,
    "recommended_action": "answer",
}
assert response.trace["evidence"].keys() == {
    "required", "supported", "missing", "conflicting",
    "coverage", "recommended_action",
}
```

Unsafe must use zero counts, coverage `0.0`, action `refuse`. No-match must report required 1/missing 1/coverage 0/not_found.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/agent_v2/test_runner_v2.py -q`

Expected: failures because `trace["evidence"]` does not exist.

- [x] **Step 3: Implement safe summary**

Add:

```python
def _evidence_trace(state: ControllerState | None, *, unsafe: bool = False) -> dict:
    if unsafe or state is None:
        return {"required": 0, "supported": 0, "missing": 0,
                "conflicting": 0, "coverage": 0.0,
                "recommended_action": "refuse" if unsafe else "system"}
    ledger = state.ledger
    if ledger is None:
        required = len(state.analysis.required_aspects)
        return {"required": required, "supported": 0, "missing": required,
                "conflicting": 0, "coverage": 0.0,
                "recommended_action": "budget"}
    return {
        "required": len(ledger.required_aspects),
        "supported": len(ledger.supported_aspects),
        "missing": len(ledger.missing_aspects),
        "conflicting": len(ledger.conflicting_aspects),
        "coverage": ledger.coverage,
        "recommended_action": ledger.recommended_action,
    }
```

Pass the summary into every `_build_trace` call. Do not serialize `ledger.items` or aspect values.

- [x] **Step 4: Run GREEN and security regression**

Run: `python -m pytest tests/agent_v2/test_runner_v2.py tests/security/test_agent_trace_zero_leak.py tests/evaluation -q`

- [x] **Step 5: Record E6-C01; do not commit**

---

### Task 2: Hash-Traceable Public Evaluation Snapshot

**Files:**
- Create: `app/evaluation/public_snapshot.py`
- Create: `scripts/export_public_demo_snapshot.py`
- Create: `tests/evaluation/test_public_snapshot.py`
- Create generated artifact: `data/v2/public/demo_snapshot.json`
- Modify: `.gitignore` only if the public path is accidentally covered

**Interfaces:**
- Produces strict `PublicDemoSnapshot` and `export_public_snapshot(*, deterministic_run: Path, live_run: Path, ablation_run: Path, load_run: Path, output: Path) -> Path`.
- CLI arguments: `--deterministic-run`, `--live-run`, `--ablation-run`, `--load-run`, `--output`.
- Snapshot is the only Evaluation-page data source.

- [x] **Step 1: Write schema/exporter RED tests**

Tests use temp E4/E5-shaped manifests and artifacts. Cover:

```python
snapshot = build_public_snapshot(inputs)
assert snapshot.quality.deterministic.passed == 28
assert snapshot.quality.live.failed == 1
assert snapshot.security.indirect_document_injection.status == "not_run"
serialized = snapshot.model_dump_json()
for forbidden in [WINDOWS_USER_PATH_MARKER, DRIVE_PATH_MARKER, "question", "answer", "tenant_id"]:
    assert forbidden not in serialized
```

Also test declared source hash mismatch, existing output refusal, staging cleanup, deterministic bytes, and `--help` no output creation.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_public_snapshot.py -q`

Expected: module-not-found.

- [x] **Step 3: Implement strict snapshot models and exporter**

Models must include:

```python
class EvidenceRef(StrictModel):
    label: str
    run_id: str
    artifact: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

class OutcomeSummary(StrictModel):
    mode: Literal["deterministic", "live"]
    split: Literal["dev", "test"]
    cases: int
    passed: int
    failed: int
    rate: float = Field(ge=0, le=1)
```

Read only allowlisted metrics from source JSON/CSV. Verify manifest-declared artifact hash before extraction. Normalize all provenance to labels/run IDs/hashes, never paths.

- [x] **Step 4: Run GREEN and CLI help**

Run:

```powershell
python -m pytest tests/evaluation/test_public_snapshot.py -q
python -m scripts.export_public_demo_snapshot --help
```

- [x] **Step 5: Export the real canonical snapshot once**

Run to a new target:

```powershell
python -m scripts.export_public_demo_snapshot `
  --deterministic-run eval_runs/20260716T135632Z_7aec4b9_test_suite `
  --live-run eval_runs/20260716T135632Z_7aec4b9_live_dev_suite_r01 `
  --ablation-run eval_runs/20260716T135632Z_7aec4b9_test_ablation `
  --load-run load_runs/20260716T165304Z_7aec4b9_demo_load_r2 `
  --output data/v2/public/demo_snapshot.json
```

Validate it with `PublicDemoSnapshot.model_validate_json` and scan forbidden keys/paths.

- [x] **Step 6: Record E6-C02; do not commit**

---

### Task 3: Typed UI Client, Demo Cases, and View Models

**Files:**
- Create: `streamlit_app/__init__.py`
- Create: `streamlit_app/api_client.py`
- Create: `streamlit_app/demo_cases.py`
- Create: `streamlit_app/view_models.py`
- Create: `tests/ui/test_api_client.py`
- Create: `tests/ui/test_demo_cases.py`
- Create: `tests/ui/test_view_models.py`

**Interfaces:**
- `EnterpriseRagClient.ask(question, user, top_k) -> AskResult`.
- `EnterpriseRagClient.readiness() -> ReadinessSnapshot`.
- `EnterpriseRagClient.trace(request_id) -> RequestTrace`.
- `load_demo_cases(root: Path) -> tuple[DemoCase, DemoCase, DemoCase, DemoCase, DemoCase, DemoCase, DemoCase]` returns seven named scenarios.
- Pure row builders return lists of JSON-safe dictionaries for Streamlit.

- [x] **Step 1: Write API client RED**

Use an injected fake session. Assert request timeout, exact `/agent/v2/chat` payload, header/body request ID equality, Pydantic response validation, generic safe exception, trace 404 handling, and no raw response body in `UiApiError`.

- [x] **Step 2: Write demo case RED**

Assert exact categories:

```python
assert [case.category for case in load_demo_cases(ROOT)] == [
    "single_document", "comparison", "version_conflict",
    "multi_condition", "not_found", "permission", "direct_injection",
]
```

The first six must resolve canonical EvalCase IDs. The last must resolve `SECURITY_PROBES.instruction_override` and be labeled direct, never document injection.

- [x] **Step 3: Write view-model RED**

Cover mode labels, citation rows, action rows, evidence defaults, budget rows, span rows and millisecond formatting. Missing optional fields return empty rows rather than throwing.

- [x] **Step 4: Run RED**

Run: `python -m pytest tests/ui -q`

Expected: missing modules.

- [x] **Step 5: Implement helpers minimally**

`UiApiError` fields are `code`, `safe_message`, `request_id`, `retryable`; `str(error)` returns only safe_message. `requests.Session.trust_env=False`.

`DemoCase` carries category, label, question, `UserContext`, expected mode, provenance case/probe ID, but no expected answer.

- [x] **Step 6: Run GREEN**

Run: `python -m pytest tests/ui -q`

- [x] **Step 7: Record E6-C03; do not commit**

---

### Task 4: Streamlit Shell and Three Operational Pages

**Files:**
- Replace: `streamlit_app/ui.py`
- Create: `streamlit_app/shell.py`
- Create: `streamlit_app/pages/1_Ask.py`
- Create: `streamlit_app/pages/2_Trace.py`
- Create: `streamlit_app/pages/3_Evaluation.py`
- Create: `tests/ui/test_streamlit_pages.py`

**Interfaces:**
- `shell.ensure_session_state()` initializes `selected_demo`, `last_answer`, `last_request_id`, `last_http_trace`, `last_latency_ms`.
- Every page can render with API offline; only an explicit Ask/Fetch action calls live API.
- Evaluation loads `data/v2/public/demo_snapshot.json` through strict schema.

- [x] **Step 1: Write Streamlit AppTest RED**

```python
from streamlit.testing.v1 import AppTest

def test_ask_page_renders_offline_without_exception():
    app = AppTest.from_file("streamlit_app/pages/1_Ask.py").run()
    assert not app.exception
    assert app.title[0].value == "Ask"

def test_evaluation_page_uses_public_snapshot():
    app = AppTest.from_file("streamlit_app/pages/3_Evaluation.py").run()
    assert not app.exception
    assert any("28/28" in metric.value for metric in app.metric)
```

Also assert Trace empty state and page config/navigation source contract.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/ui/test_streamlit_pages.py -q`

- [x] **Step 3: Implement shell**

Use `st.navigation` with Material icons and `default=True` for Ask. Inject restrained CSS: no gradients, no decorative cards, radius <= 8px, stable metric/button dimensions, mobile media query, no negative letter spacing.

- [x] **Step 4: Implement Ask page**

Render demo/custom selector, identity summary, question/top-k controls, send button, mode/stop/request metrics, answer, claims/citations dataframe, authorized sources and feedback icon buttons. Save real response/trace in session state.

- [x] **Step 5: Implement Trace page**

Render session Agent trace and fetch service trace by current/custom request ID. Show evidence coverage, action table, budget usage, spans, model calls and total latency. Never display question, identity or source preview on this page.

- [x] **Step 6: Implement Evaluation page**

Render Quality/Ablation/Runtime/Security tabs from `PublicDemoSnapshot`. Show indirect document injection as `NOT RUN`, live 23/24 rather than rounded 100%, reranker as not run, and all source run IDs/hashes.

- [x] **Step 7: Run GREEN and all UI tests**

Run: `python -m pytest tests/ui -q`

- [x] **Step 8: Record E6-C04; do not commit**

---

### Task 5: Public Repository Audit and Current-State Documents

**Files:**
- Create: `scripts/audit_public_repo.py`
- Create: `tests/test_public_repository.py`
- Replace: `README.md`
- Replace: `PROJECT_STATUS.md`
- Modify: `docs/AGENTIC_RAG_EVOLUTION_LOG.md`
- Create: `docs/architecture.md`
- Create: `docs/known_limitations.md`
- Create: `docs/demo_runbook.md`
- Create: `docs/industrialization_backlog.md`
- Create: `docs/assets/README.md`

**Interfaces:**
- `audit_repository(root) -> AuditReport` enumerates tracked + untracked nonignored candidate files.
- CLI exits nonzero for forbidden paths, high-confidence secret pattern, >2MiB candidate, missing public link or missing screenshot/snapshot.

- [x] **Step 1: Write repository audit RED**

Use temp fixture paths to prove rejection of `.env`, `.private`, private key marker, `sk-`/`ghp_` token shape, non-example email, absolute user path, large file, and missing Markdown link. Prove seeded strings such as `password=never-show` in tests are not treated as credentials.

- [x] **Step 2: Write current repository contract RED**

Assert README headings/order, Mermaid, screenshot links, exactly three quick-start commands, synthetic disclaimer, current 526-test evidence, root PROJECT_STATUS current date/status, historical banner, required public docs, `.env` and `.private` ignored.

- [x] **Step 3: Run RED**

Run: `python -m pytest tests/test_public_repository.py -q`

- [x] **Step 4: Implement audit script**

Use `git ls-files --cached --others --exclude-standard -z`, structured findings and exit 1 on failure. Do not mutate files or Git.

- [x] **Step 5: Rewrite public entry docs**

README order is exact: business problem; Mermaid architecture; real screenshot; Agentic necessity; features; evidence table; three commands; synthetic data; limitations; docs. PROJECT_STATUS is the sole current status. Evolution log starts with a historical banner and link.

- [x] **Step 6: Write architecture, limitations, runbook and backlog**

Include exact local commands, Windows UTC fallback `(Get-Date).ToUniversalTime()`, process cleanup, live/ready distinction, E6 `NOT RUN` items and R2 admission criteria.

- [x] **Step 7: Run GREEN and audit**

Run:

```powershell
python -m pytest tests/test_public_repository.py -q
python -m scripts.audit_public_repo
```

Screenshot checks may remain expected RED until Task 7 publishes final PNGs; all other findings must be zero.

- [x] **Step 8: Record E6-C05; do not commit**

---

### Task 6: Ignored Interview and Learning Materials

**Files:**
- Modify: `.gitignore`
- Create ignored: `.private/e6/interview_script_30s.md`
- Create ignored: `.private/e6/interview_script_1min.md`
- Create ignored: `.private/e6/interview_script_3min.md`
- Create ignored: `.private/e6/interview_qa.md`
- Create ignored: `.private/e6/claims_evidence_matrix.md`
- Create ignored: `.private/e6/learning_cards.md`
- Modify tests: `tests/test_public_repository.py`

**Interfaces:**
- `.private/` must be ignored as a directory.
- Claims matrix produces candidate wording only; E7 approval status remains pending.

- [x] **Step 1: Add ignore contract RED**

Assert `git check-ignore .private/e6/claims_evidence_matrix.md` succeeds and `git ls-files --cached --others --exclude-standard` omits `.private/`.

- [x] **Step 2: Run RED**

Run: `python -m pytest tests/test_public_repository.py -q`

- [x] **Step 3: Add `.private/` ignore and write materials**

Scripts contain 30s/1m/3m truthful versions. Q&A has at least 25 questions across corpus/parser/retrieval/Agent/eval/API/security/load. Claims matrix columns:

```text
claim_id | candidate_wording | evidence_file | metric_path |
source_hash | boundary | status=pending_e7
```

- [x] **Step 4: Run GREEN and Git candidate audit**

Run: `python -m pytest tests/test_public_repository.py -q`

- [x] **Step 5: Record E6-C06; do not commit**

---

### Task 7: Live UI, Browser Verification, and Public Screenshots

**Files:**
- Create: `docs/assets/ask.png`
- Create: `docs/assets/trace.png`
- Create: `docs/assets/evaluation.png`
- Modify: `README.md` if actual asset names differ
- Modify: `docs/assets/README.md` with exact reproduction steps

**Interfaces:**
- FastAPI uses a free localhost port recorded for the run.
- Streamlit receives `API_BASE_URL` through environment/config without committing `.env`.
- Only processes started by this task are stopped.

- [x] **Step 1: Start hidden FastAPI and Streamlit without reload**

Use separate logs/PID records under ignored `data/eval_outputs`. Wait for `/health/live`, `/health/ready`, and Streamlit HTTP 200.

- [x] **Step 2: Browser desktop Ask verification**

At 1440x1000: select single-document demo, submit, wait for answer, assert mode/request ID/claims visible; check no page/console errors, no overlap, no horizontal page overflow. Save `ask.png`.

- [x] **Step 3: Browser Trace verification**

Navigate to Trace in same session; assert action table, evidence coverage, budget, spans and stop reason use the preceding request. Save `trace.png`.

- [x] **Step 4: Browser Evaluation verification**

Assert deterministic 28/28, live 23/24, bounded vs fixed, p95 rows, direct 0/4 and indirect NOT RUN. Save `evaluation.png`.

- [x] **Step 5: Mobile verification**

At 390x844 inspect all pages: no incoherent overlap, controls fit, navigation usable, tables scroll inside containers, long IDs do not expand page width.

- [x] **Step 6: Stop only recorded FastAPI/Streamlit process trees**

Verify project Python/Streamlit/Uvicorn process count 0. Keep Ollama running.

- [x] **Step 7: Run screenshot/public audit GREEN**

Run:

```powershell
python -m pytest tests/test_public_repository.py tests/ui -q
python -m scripts.audit_public_repo
```

- [x] **Step 8: Record exact visual observations and E6-C07; do not commit**

---

### Task 8: Final Gates and E6 Handoff

**Files:**
- Modify: `docs/roadmap/e6_demo_public_repo_implementation.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`
- Modify: `docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`
- Modify: `docs/superpowers/plans/2026-07-17-e6-demo-public-repo.md`

**Interfaces:**
- Marks E6 implementation complete but human acceptance pending.
- Stops before E7.

- [x] **Step 1: Run fresh focused gates**

```powershell
python -m pytest tests/ui tests/evaluation/test_public_snapshot.py tests/test_public_repository.py -q
python -m pytest tests/api_v2 tests/security -q
```

- [x] **Step 2: Run full deterministic gates**

```powershell
python -m pytest -q
python -m pip check
python -m compileall -q app scripts streamlit_app tests
git diff --check
python -m scripts.audit_public_repo
```

- [x] **Step 3: Verify evidence and process boundaries**

Verify frozen hash, public snapshot source hashes, active index, screenshot dimensions, candidate max file size, local links, `.private` ignored, project background 0 and `.git/index.lock` false.

- [x] **Step 4: Update journals/handoff**

Record every RED/GREEN, visual issue, artifact hash, residual NOT RUN, exact test counts and Git boundary.

- [x] **Step 5: Stop at E6 acceptance**

Do not commit/push/merge/tag or enter E7. The only next command is `执行E7最终验收`.

## Plan Self-Review

- Every E6 design requirement maps to a task.
- Agent trace evidence, snapshot exporter, API client, audit logic and UI all have named RED tests.
- Public snapshot is generated from verified source hashes and contains no ignored artifact dependency.
- All seven planned demo categories are represented; indirect document injection is explicitly NOT RUN rather than mislabeled.
- Private materials have a testable ignored boundary.
- Browser verification covers desktop/mobile and all three final pages.
- Git publishing operations remain outside E6 authorization.

### Task 9: Independent Review Remediation

- [x] **Step 1: Make public tests clean-clone safe and run audit in CI**
- [x] **Step 2: Enforce sent/header/body request correlation**
- [x] **Step 3: Prevent stale Ask results and cross-request Trace mixing**
- [x] **Step 4: Complete claim verdict columns**
- [x] **Step 5: Enforce strict snapshot semantic invariants and atomic no-replace publish**
- [x] **Step 6: Derive Evaluation status/provenance from snapshot**
- [x] **Step 7: Harden symlink/binary/runtime-path/schema/PNG/link audit coverage**
- [x] **Step 8: Repeat browser, full gates, evidence boundaries and final handoff**
