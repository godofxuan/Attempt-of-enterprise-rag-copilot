# Adaptive Evidence Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed safe-route workflow behind `/agent/chat` with a bounded evidence-aware loop that can answer on sufficient evidence, rewrite and retry once, or return a grounded no-answer.

**Architecture:** `AgentRunner` becomes a generic observe-decide-act executor. `AdaptiveController` owns deterministic transitions and limits, while an injected local-model assessor returns validated semantic evidence decisions. The historical Stage 7 evaluator explicitly uses `FixedPlanController` so its fixed-plan baseline remains reproducible.

**Tech Stack:** Python 3.11.9, Pydantic 2.13.2, FastAPI, requests, pytest, local Ollama with `qwen2.5:3b`.

## Global Constraints

- Preserve `/chat` as the baseline RAG path; only `/agent/chat` adopts the adaptive controller.
- Keep the original user `question` immutable; only `search_query` may change.
- Allow at most two retrieval calls and one rewrite.
- Treat empty retrieval, model transport errors, invalid JSON, and invalid schema as non-sufficient; never continue to generation from unverified chunks.
- Use deterministic fake assessors and fake tools in unit and orchestration tests. Ollama is required only for the separate live evaluation.
- Do not modify Stage 7 dataset expectations to match Stage 8 sequences.
- Do not commit generated files under `data/eval_outputs/`.
- Follow red-green-refactor for every production behavior.
- Before Stage 8 changes, the verified baseline is `44 passed, 5 warnings`.

---

## File Map

**Create:**

- `app/ollama_chat.py` - shared local chat transport with the current retry and error-reporting behavior.
- `app/agent/evidence.py` - evidence schema, strict parser, prompt construction, local assessor, and rewrite validation.
- `app/agent/controller.py` - fixed and adaptive controller strategies.
- `tests/test_ollama_chat.py` - transport extraction and JSON-mode payload tests.
- `tests/test_agent_evidence.py` - evidence parsing, validation, prompt, and fail-closed tests.
- `tests/test_agent_controller.py` - deterministic state-transition tests.
- `tests/test_agent_adaptive_runner.py` - complete adaptive trajectory tests.
- `data/eval/agent_loop_dev.json` - 16 development trajectories.
- `data/eval/agent_loop_test.json` - 16 held-out trajectories.
- `scripts/eval_agent_loop.py` - deterministic Stage 8 orchestration evaluator.
- `tests/test_agent_loop_dataset.py` - Stage 8 dataset contract tests.
- `tests/test_agent_loop_eval.py` - Stage 8 metrics and serialization tests.

**Modify:**

- `app/rag_service.py` - import the extracted chat transport without changing answer behavior.
- `app/agent/schemas.py` - add structured evidence trace and final-outcome fields with backward-compatible defaults.
- `app/agent/tools.py` - make retrieval query-aware and add assess, rewrite, and no-answer tools.
- `app/agent/runner.py` - execute one controller-selected step at a time.
- `scripts/eval_agent_actions.py` - request `FixedPlanController` explicitly.
- `tests/test_agent_runner.py` - make historical fixed-flow intent explicit.
- `tests/test_agent_tools.py` - cover new context updates and original-question preservation.
- `tests/test_agent_api.py` - assert extended trace fields remain API-compatible.
- `tests/test_rag_service_agent_flow.py` - keep the transport monkeypatch seam after extraction.
- `.env.example` - document bounded-loop settings only if settings are exposed.
- `README.md`, `PROJECT_STATUS.md`, `docs/RAG_EVAL_USAGE.md`, `docs/api.md` - document verified behavior and measured results after fresh runs.

### Task 1: Extract the Shared Ollama Chat Transport

**Files:**
- Create: `tests/test_ollama_chat.py`
- Create: `app/ollama_chat.py`
- Modify: `app/rag_service.py:1-90`
- Test: `tests/test_rag_service_agent_flow.py`

**Interfaces:**
- Produces: `chat_with_ollama(model: str, messages: list[dict], *, response_format: str | dict | None = None) -> str`.
- Preserves: `app.rag_service._chat_with_ollama` as an imported module-level alias so existing tests and callers keep the same seam.

- [ ] **Step 1: Write the failing transport test**

```python
from types import SimpleNamespace

import app.ollama_chat as ollama_chat


class FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": "{\"verdict\": \"sufficient\"}"}}


def test_chat_with_ollama_passes_json_format_without_changing_defaults(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured.update(url=url, payload=payload, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        lambda: SimpleNamespace(llm_base_url="http://127.0.0.1:11434/v1"),
    )
    monkeypatch.setattr(ollama_chat, "_post_ollama", fake_post)

    result = ollama_chat.chat_with_ollama(
        "qwen2.5:3b",
        [{"role": "user", "content": "judge"}],
        response_format="json",
    )

    assert result == '{"verdict": "sufficient"}'
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["options"] == {"temperature": 0}
    assert captured["payload"]["stream"] is False
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ollama_chat.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.ollama_chat'`.

- [ ] **Step 3: Add the transport and preserve the RAG seam**

Move `_ollama_api_base_url`, `_post_ollama`, and the retry loop from `app/rag_service.py` into `app/ollama_chat.py`. Build the payload first and add `payload["format"] = response_format` only when the optional argument is not `None`. In `app/rag_service.py` use:

```python
from app.ollama_chat import chat_with_ollama as _chat_with_ollama
```

Do not change the prompts or `answer_from_retrieved()`.

- [ ] **Step 4: Run focused and regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ollama_chat.py tests/test_rag_service_agent_flow.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit only the transport slice**

```powershell
git add app/ollama_chat.py app/rag_service.py tests/test_ollama_chat.py tests/test_rag_service_agent_flow.py
git commit -m "refactor: share Ollama chat transport"
```

### Task 2: Implement Structured Evidence Assessment

**Files:**
- Create: `tests/test_agent_evidence.py`
- Create: `app/agent/evidence.py`
- Consume: `app/ollama_chat.py`

**Interfaces:**
- Produces: `EvidenceAssessment` with `verdict`, `reason`, and `rewritten_query`.
- Produces: `EvidenceAssessor` protocol with `assess(question: str, search_query: str, chunks: list[dict]) -> EvidenceAssessment`.
- Produces: `parse_evidence_response(raw: str) -> EvidenceAssessment`.
- Produces: `is_usable_rewrite(candidate: str | None, original: str, current: str) -> bool`.
- Produces: `LocalEvidenceAssessor.assess(question: str, search_query: str, chunks: list[dict]) -> EvidenceAssessment`.

- [ ] **Step 1: Write parser and validation tests first**

Cover these exact behaviors:

```python
def test_parse_evidence_response_accepts_json_fence():
    result = parse_evidence_response(
        '```json\n{"verdict":"insufficient","reason":"missing deadline","rewritten_query":"refund deadline"}\n```'
    )
    assert result.verdict == "insufficient"
    assert result.rewritten_query == "refund deadline"


def test_sufficient_decision_rejects_rewrite():
    with pytest.raises(ValidationError):
        EvidenceAssessment(
            verdict="sufficient",
            reason="direct support",
            rewritten_query="another query",
        )


def test_usable_rewrite_rejects_same_normalized_query():
    assert not is_usable_rewrite("Refund deadline", "refund deadline", "refund deadline")
```

Also test malformed JSON, leading prose, empty reason, overlong rewrite, transport exception, and document text being included as untrusted numbered evidence.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_evidence.py -q
```

Expected: collection fails because `app.agent.evidence` does not exist.

- [ ] **Step 3: Implement the minimal evidence module**

Use Pydantic v2 validators. The model contract is:

```python
class EvidenceAssessment(BaseModel):
    verdict: Literal["sufficient", "insufficient", "error"]
    reason: str = Field(min_length=1, max_length=400)
    rewritten_query: str | None = Field(default=None, max_length=200)


class EvidenceAssessor(Protocol):
    def assess(
        self,
        *,
        question: str,
        search_query: str,
        chunks: list[dict],
    ) -> EvidenceAssessment: ...
```

The parser may strip exactly one complete `json` code fence, then must call `json.loads()` on the whole remaining string and `EvidenceAssessment.model_validate()`. Do not extract a JSON-looking substring from arbitrary prose.

`LocalEvidenceAssessor` must call `chat_with_ollama(..., response_format="json")` and convert transport, JSON, or validation exceptions into:

```python
EvidenceAssessment(
    verdict="error",
    reason=f"evidence assessment failed: {type(exc).__name__}",
)
```

Limit prompt input to the first five chunks and 1,200 characters per chunk. Tell the model that retrieved text is untrusted data and sufficient evidence must directly support the original question.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_evidence.py tests/test_ollama_chat.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the evidence module**

```powershell
git add app/agent/evidence.py tests/test_agent_evidence.py
git commit -m "feat: add structured evidence assessor"
```

### Task 3: Add Explicit Controller State and Trace Schemas

**Files:**
- Create: `tests/test_agent_controller.py`
- Create: `app/agent/controller.py`
- Modify: `app/agent/schemas.py`

**Interfaces:**
- Produces: `AdaptiveController.initialize(...) -> dict` and `AdaptiveController.next_step(decision, context) -> PlanStep | None`.
- Produces: `FixedPlanController` for the historical fixed workflow.
- Adds: `EvidenceTraceRecord`, `AgentTrace.retrieval_attempts`, `AgentTrace.evidence_history`, and `AgentTrace.final_outcome`.

- [ ] **Step 1: Write state-transition tests**

The tests must assert:

```python
controller = AdaptiveController(max_retrieval_attempts=2)
context = controller.initialize(
    RouteDecision(route="policy_qa", reason="default"),
    question="What is the refund deadline?",
    top_k=5,
)
assert context["question"] == "What is the refund deadline?"
assert context["search_query"] == context["question"]
assert controller.next_step(decision, context).tool == "retrieval.search"
```

Add separate tests for unsafe start, empty retrieval, sufficient evidence, usable rewrite, second insufficient decision, assessment error, guarded completion, and impossible phase. Assert no branch selects a third retrieval.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_controller.py -q
```

Expected: import failure for `app.agent.controller`.

- [ ] **Step 3: Add backward-compatible trace fields**

Add defaults so old `AgentTrace(...)` construction remains valid:

```python
class EvidenceTraceRecord(BaseModel):
    attempt: int = Field(ge=1)
    search_query: str
    verdict: Literal["sufficient", "insufficient", "error"]
    reason: str
    rewritten_query: str | None = None


class AgentTrace(BaseModel):
    route: RouteName
    route_reason: str
    plan: list[PlanStep] = Field(default_factory=list)
    steps: list[ToolTraceStep] = Field(default_factory=list)
    retrieval_attempts: int = 0
    evidence_history: list[EvidenceTraceRecord] = Field(default_factory=list)
    final_outcome: Literal["answered", "grounded_no_answer", "refused", "error"] | None = None
```

- [ ] **Step 4: Implement both controllers**

`AdaptiveController` uses explicit `phase` values: `start`, `retrieved`, `assessed`, `rewritten`, `answered`, `no_answer`, `refused`, and `guarded`. It returns one `PlanStep` per call and raises `RuntimeError` for impossible state.

`FixedPlanController` stores `build_plan(decision)` and a current index in context, returning one historical step at a time.

- [ ] **Step 5: Run controller and schema regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_controller.py tests/test_agent_api.py tests/test_agent_planner.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the controller slice**

```powershell
git add app/agent/controller.py app/agent/schemas.py tests/test_agent_controller.py
git commit -m "feat: add adaptive agent controller"
```

### Task 4: Make Tools Update Adaptive Runtime State

**Files:**
- Modify: `app/agent/tools.py`
- Modify: `tests/test_agent_tools.py`

**Interfaces:**
- Produces tools: `evidence.assess`, `query.rewrite`, and `rag.no_answer`.
- Changes `retrieval.search` to read `search_query` and increment `retrieval_attempts`.
- Preserves `rag.answer` generation against immutable `question`.

- [ ] **Step 1: Write failing tool tests**

Add tests that verify:

```python
def test_retrieval_uses_search_query_and_keeps_original_question(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agent_tools,
        "hybrid_search",
        lambda question, top_k=None: calls.append((question, top_k)) or [chunk()],
    )
    context = {
        "question": "original question",
        "search_query": "rewritten search query",
        "top_k": 5,
        "retrieval_attempts": 1,
    }

    result = agent_tools.retrieval_search_tool(context)

    assert calls == [("rewritten search query", 5)]
    assert result.updates["retrieval_attempts"] == 2
    assert result.updates["phase"] == "retrieved"
    assert context["question"] == "original question"
```

Also cover assessment history, error conversion, rewrite application, deterministic insufficient-evidence message, assessment-unavailable message, answer phase, refusal phase, and guardrail completion.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -q
```

Expected: failures show missing adaptive updates and tools.

- [ ] **Step 3: Implement state-aware tools**

Use a tool factory for the injected assessor:

```python
def make_evidence_assess_tool(assessor: EvidenceAssessor) -> ToolFn:
    def evidence_assess_tool(context: dict[str, Any]) -> ToolExecutionResult:
        assessment = assessor.assess(
            question=context["question"],
            search_query=context["search_query"],
            chunks=context["retrieved_chunks"],
        )
        record = EvidenceTraceRecord(
            attempt=context["retrieval_attempts"],
            search_query=context["search_query"],
            **assessment.model_dump(),
        )
        return ToolExecutionResult(
            updates={
                "evidence_assessment": assessment,
                "evidence_history": [*context.get("evidence_history", []), record],
                "phase": "assessed",
            },
            output_summary=f"evidence {assessment.verdict}: {assessment.reason}",
        )

    return evidence_assess_tool
```

`query.rewrite` only applies an already validated candidate. `rag.no_answer` sets no sources and sets `final_outcome` to `error` for assessment failure or `grounded_no_answer` for insufficient evidence.

Register all seven production tool names in `build_default_registry(assessor=None)`.

- [ ] **Step 4: Run tool and baseline tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py tests/test_rag_service_agent_flow.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the tool slice**

```powershell
git add app/agent/tools.py tests/test_agent_tools.py
git commit -m "feat: add adaptive RAG tools"
```

### Task 5: Convert AgentRunner to Observe-Decide-Act

**Files:**
- Create: `tests/test_agent_adaptive_runner.py`
- Modify: `app/agent/runner.py`
- Modify: `tests/test_agent_runner.py`
- Modify: `scripts/eval_agent_actions.py`
- Modify: `tests/test_agent_action_eval.py`
- Modify: `tests/test_agent_api.py`

**Interfaces:**
- `AgentRunner(controller=AdaptiveController())` is the production default.
- `run_agent_chat()` builds the default registry and adaptive controller.
- Stage 7 calls `AgentRunner(controller=FixedPlanController(), registry=build_eval_registry())`.

- [ ] **Step 1: Write the five failing trajectory tests**

Use deterministic in-memory tools and assessors to assert these exact sequences:

```text
first pass:
retrieval.search -> evidence.assess -> rag.answer -> guardrail.check

retry then answer:
retrieval.search -> evidence.assess -> query.rewrite
-> retrieval.search -> evidence.assess -> rag.answer -> guardrail.check

retry then no-answer:
retrieval.search -> evidence.assess -> query.rewrite
-> retrieval.search -> evidence.assess -> rag.no_answer -> guardrail.check

assessment error:
retrieval.search -> evidence.assess -> rag.no_answer -> guardrail.check

unsafe:
guardrail.refuse
```

For the retry paths, capture the generation call and assert that it receives the original question, not the rewritten search query. Assert `trace.plan` and `trace.steps` match, retrieval attempts never exceed two, and evidence history has one record per assessment.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_adaptive_runner.py -q
```

Expected: failures show that `AgentRunner` does not accept/use a controller and still executes a fixed plan.

- [ ] **Step 3: Implement the bounded runner loop**

Replace the fixed `for step in plan` with:

```python
context = self.controller.initialize(
    decision,
    question=question,
    top_k=top_k,
)
actual_plan = []
step_traces = []

for _ in range(self.max_steps):
    step = self.controller.next_step(decision, context)
    if step is None:
        break
    actual_plan.append(step)
    result = self._execute_step(step, context, step_traces)
    context.update(result.updates)
else:
    raise RuntimeError("Agent exceeded maximum step count")
```

Keep existing error trace creation. Build `AgentTrace` from `actual_plan` and the structured context fields.

- [ ] **Step 4: Version the historical evaluator explicitly**

Change every Stage 7 evaluator construction to:

```python
AgentRunner(
    registry=build_eval_registry(),
    controller=FixedPlanController(),
)
```

Update old runner tests to request `FixedPlanController` when asserting the historical three-step path. Do not change `agent_action_dev.json` or `agent_action_test.json`.

- [ ] **Step 5: Run Agent regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_adaptive_runner.py tests/test_agent_runner.py tests/test_agent_action_eval.py tests/test_agent_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Re-run the Stage 7 historical evaluator**

Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_agent_actions --split test
```

Expected: the recorded fixed-plan baseline remains `20` cases with route accuracy `0.55`, plan/tool sequence rates `0.90`, trace completeness `1.00`, unsafe no-retrieval `0.50`, and case pass `0.55`.

- [ ] **Step 7: Commit the runtime loop**

```powershell
git add app/agent/runner.py scripts/eval_agent_actions.py tests/test_agent_adaptive_runner.py tests/test_agent_runner.py tests/test_agent_action_eval.py tests/test_agent_api.py
git commit -m "feat: run bounded adaptive RAG loop"
```

### Task 6: Add the Versioned Stage 8 Action Evaluation

**Files:**
- Create: `data/eval/agent_loop_dev.json`
- Create: `data/eval/agent_loop_test.json`
- Create: `scripts/eval_agent_loop.py`
- Create: `tests/test_agent_loop_dataset.py`
- Create: `tests/test_agent_loop_eval.py`
- Modify: `data/eval/metadata.json`

**Interfaces:**
- Dataset row fields: `id`, `question`, `expected_route`, `scenario`, `expected_tools`, `expected_outcome`, and `tags`.
- Supported scenarios: `first_pass_answer`, `rewrite_then_answer`, `rewrite_then_no_answer`, and `unsafe_refusal`.
- CLI: `python -m scripts.eval_agent_loop --split dev|test --mode deterministic|live`.

- [ ] **Step 1: Write dataset contract tests**

Each split contains 16 unique cases, four per scenario. IDs and questions are disjoint across splits. Expected sequences exactly match the four trajectories in Task 5. Unsafe cases expect zero retrieval attempts; retry cases expect two.

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop_dataset.py -q
```

Expected: failure because the two dataset files do not exist.

- [ ] **Step 3: Add development and held-out datasets**

Use paraphrased Chinese enterprise-policy questions. Do not copy Stage 7 rows verbatim. The deterministic scenario fixture is selected by `scenario`, while routing still uses the real router.

- [ ] **Step 4: Write failing evaluator tests**

Test one passing row, one route failure, one retry-limit failure, summary denominators, complete-trace validation, CSV failure filtering, and malformed dataset errors that include source, row, and field.

- [ ] **Step 5: Run and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop_eval.py -q
```

Expected: import failure for `scripts.eval_agent_loop`.

- [ ] **Step 6: Implement the deterministic evaluator**

In `deterministic` mode, build a per-scenario fake registry and fake assessor, but use the real router, `AdaptiveController`, `AgentRunner`, and trace models. In `live` mode, use the production registry, real indexes, and local evidence assessor. Report:

```text
route_accuracy
outcome_accuracy
retry_decision_accuracy
tool_sequence_accuracy
trace_complete_rate
unsafe_no_retrieval_rate
max_retry_compliance_rate
assessment_parse_success_rate
case_pass_rate
```

Write:

```text
data/eval_outputs/agent_loop_<mode>_<split>_results.json
data/eval_outputs/agent_loop_<mode>_<split>_details.jsonl
data/eval_outputs/agent_loop_<mode>_<split>_failures.csv
```

- [ ] **Step 7: Run focused tests and both splits**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop_dataset.py tests/test_agent_loop_eval.py -q
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split dev --mode deterministic
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode deterministic
```

Expected: tests pass and both commands write internally consistent reports. Metric values are recorded as observed, not forced to a target.

- [ ] **Step 8: Commit evaluation source and datasets**

```powershell
git add data/eval/agent_loop_dev.json data/eval/agent_loop_test.json data/eval/metadata.json scripts/eval_agent_loop.py tests/test_agent_loop_dataset.py tests/test_agent_loop_eval.py
git commit -m "test: add adaptive agent loop evaluation"
```

### Task 7: Live Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_STATUS.md`
- Modify: `docs/RAG_EVAL_USAGE.md`
- Modify: `docs/api.md`
- Modify: `.env.example` only if runtime settings were added

**Interfaces:**
- Documents the fixed baseline, deterministic Stage 8 result, separate live result, exact commands, known failures, and bounded-agent claim.

- [ ] **Step 1: Run the full automated suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass. Existing FAISS/SWIG and FastAPI deprecation warnings may remain; no new warning is accepted without explanation.

- [ ] **Step 2: Verify local Ollama and indexes**

Use explicit IPv4 when validating this machine:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
.\.venv\Scripts\python.exe -m scripts.test_retrieval
```

Expected: `qwen2.5:3b` and `bge-m3` are available, and retrieval returns chunks.

- [ ] **Step 3: Exercise all live branches**

Run the versioned development set through the production registry:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split dev --mode live
```

Inspect safe answerable, unknown, rewrite-prone, and unsafe rows in the saved JSONL trace. Confirm:

- The safe answer path has an evidence decision before generation.
- A retry path changes `search_query` but generation still targets the original question.
- An unsupported question returns no sources and no fabricated answer.
- An unsafe-routed request has only `guardrail.refuse`.
- No trace contains more than two retrieval calls.

- [ ] **Step 4: Record honest live limitations**

Report the local assessor's parse success, observed decisions, latency, and any semantic mistakes separately from deterministic controller metrics. Do not claim the live model is correct because fake-assessor tests passed.

After prompt and transition behavior are frozen from development results, run the held-out live split once:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode live
```

- [ ] **Step 5: Update documentation from fresh artifacts**

Explain each new file, the state transitions, metric definitions, actual commands, actual values, and failure examples. State the capability as a bounded adaptive Agentic RAG loop, not a fully autonomous multi-agent system.

- [ ] **Step 6: Run final verification after docs**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.eval_agent_actions --split test
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode deterministic
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode live
git diff --check
```

Expected: tests pass, both evaluators complete, Stage 7 remains reproducible, Stage 8 outputs are consistent, and Git reports no whitespace errors.

- [ ] **Step 7: Commit verified documentation**

```powershell
git add README.md PROJECT_STATUS.md docs/RAG_EVAL_USAGE.md docs/api.md .env.example
git commit -m "docs: explain adaptive Agentic RAG loop"
```
