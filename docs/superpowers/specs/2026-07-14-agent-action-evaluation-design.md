# Agent Action Evaluation Design

## Stage Goal

Add a deterministic evaluation layer for the existing minimal Agentic RAG loop. This stage measures whether the agent selects the expected route, builds the expected plan, executes the expected tool sequence, short-circuits unsafe requests before retrieval, and returns a complete trace.

This is an orchestration evaluation, not an answer-quality evaluation. It must run without Ollama, embeddings, FAISS, or external network access.

## Why This Stage Comes Next

The current `/agent/chat` path already has a real shared-context tool chain:

```text
route_query()
-> build_plan()
-> ToolRegistry
-> retrieval.search
-> rag.answer
-> guardrail.check
-> AgentTrace
```

Unsafe requests take the separate `guardrail.refuse` path. However, the project does not yet quantify whether routing, planning, short-circuiting, and tracing are correct across a representative set of questions. Adding adaptive retrieval or query rewriting before this baseline would make regressions difficult to detect and claims difficult to support.

## Scope

This stage will add:

- A development split and a held-out test split for Agent actions.
- A command-line evaluator that uses the real router, planner, runner, and trace models.
- Deterministic in-memory tool implementations for evaluating orchestration without running retrieval or generation.
- Overall and per-route metrics.
- JSON summary, JSONL details, and CSV failure-analysis outputs.
- Dataset-schema, metric, runner-integration, and CLI tests.
- Evaluation usage and project-status documentation based on a fresh local run.

This stage will not:

- Change the production behavior of `/agent/chat`.
- Tune the router against the held-out test split.
- Add an LLM judge.
- Add query rewriting, evidence grading, retries, long-term memory, or trace persistence.
- Change the Streamlit interface.
- Commit generated files under `data/eval_outputs/`.

## Options Considered

### 1. Agent action evaluation first (selected)

Establishes a reproducible behavior baseline before changing the controller. It is fast, deterministic, inexpensive, and produces evidence that can drive the next adaptive-loop stage.

### 2. Adaptive retrieval loop first

Would make the runtime more agentic immediately, but there would be no stable baseline for deciding whether routing and tool behavior improved or regressed.

### 3. Trace UI first

Would improve interview presentation, but it would expose the current fixed workflow without increasing or measuring the controller's capability.

## Dataset Design

Create:

```text
data/eval/agent_action_dev.json
data/eval/agent_action_test.json
```

Each split contains 20 manually reviewed cases, balanced across the five current routes: four cases each for `policy_qa`, `process`, `comparison`, `no_answer_check`, and `unsafe_request`.

Each case has this schema:

```json
{
  "id": "agent_test_001",
  "question": "退款和退货是同一个流程吗？",
  "expected_route": "comparison",
  "expected_plan": [
    "retrieval.search",
    "rag.answer",
    "guardrail.check"
  ],
  "tags": ["comparison", "zh-CN"]
}
```

Dataset constraints:

- IDs and questions are unique within and across splits.
- Every current route appears exactly four times per split.
- The test split is used only for final reporting, not for keyword tuning.
- Questions include paraphrases rather than only copying the router's literal keyword list.
- Unsafe cases expect only `guardrail.refuse` and must never execute retrieval or answer generation.

## Evaluation Architecture

Create `scripts/eval_agent_actions.py` with four responsibilities:

1. Load and validate the selected split.
2. Construct an `AgentRunner` with the real `route_query()` and `build_plan()` functions.
3. Replace external tools with deterministic in-memory tools registered under the production tool names.
4. Compare the resulting route, plan, executed trace, and safety behavior with each case's expected values.

The in-memory registry preserves the production contract:

```text
retrieval.search -> writes retrieved_chunks and retrieved_sources
rag.answer       -> reads retrieved_chunks and writes answer and sources
guardrail.check  -> writes guardrail_blocked=false
guardrail.refuse -> writes refusal answer, empty sources, guardrail_blocked=true
```

This design deliberately uses the real `AgentRunner`. A static comparison of `route_query()` and `build_plan()` would not verify that the runner executes the plan in order or records trace steps correctly.

## Metrics

For each case, calculate binary values:

- `route_correct`: actual route exactly equals `expected_route`.
- `plan_exact_match`: ordered planned tool names exactly equal `expected_plan`.
- `tool_sequence_correct`: ordered executed trace tools exactly equal `expected_plan`.
- `trace_complete`: route is present; plan and executed steps have equal length; each step has the expected tool name, status `ok`, non-negative latency, and a non-empty output summary.
- `unsafe_no_retrieval`: for unsafe cases, neither `retrieval.search` nor `rag.answer` appears in executed steps. This value is null for non-unsafe cases.
- `case_pass`: all applicable checks for the case are true.

Aggregate metrics:

```text
route_accuracy             = mean(route_correct over all cases)
plan_exact_match_rate      = mean(plan_exact_match over all cases)
tool_sequence_accuracy     = mean(tool_sequence_correct over all cases)
trace_complete_rate        = mean(trace_complete over all cases)
unsafe_no_retrieval_rate   = mean(unsafe_no_retrieval over unsafe cases only)
case_pass_rate             = mean(case_pass over all cases)
```

The report also groups `count`, `route_accuracy`, `plan_exact_match_rate`, `tool_sequence_accuracy`, `trace_complete_rate`, and `case_pass_rate` by expected route. A score below 1.0 is a finding to investigate, not a reason to rewrite the result.

## Output Files

For `--split test`, write:

```text
data/eval_outputs/agent_action_test_results.json
data/eval_outputs/agent_action_test_details.jsonl
data/eval_outputs/agent_action_test_failures.csv
```

The summary JSON contains overall metrics, per-route metrics, configuration, and output paths. The JSONL file contains every case. The CSV contains only cases where `case_pass` is false, sorted by expected route and ID.

Generated evaluation outputs remain untracked. Documentation may record verified aggregate numbers and the command that produced them.

## Error Handling

- Invalid dataset rows fail before evaluation with an error naming the file, row index, and invalid field.
- Duplicate IDs or questions and missing route coverage fail dataset validation.
- A per-case runner exception is captured as `execution_error`; all binary metrics for that case become false, and evaluation continues so the failure appears in the report.
- The CLI exits non-zero for invalid input or output-write failure. Metric scores below 1.0 do not make the command fail because the evaluator is a measurement tool, not a release gate in this stage.

## Testing Strategy

Add:

```text
tests/test_agent_action_dataset.py
tests/test_agent_action_eval.py
```

The tests will verify:

- Both split files exist, satisfy the schema, are disjoint, and cover all routes evenly.
- Metric calculations distinguish route, plan, execution, trace, and unsafe-short-circuit failures.
- The deterministic registry preserves the production shared-context contract.
- A normal case executes `retrieval.search -> rag.answer -> guardrail.check`.
- An unsafe case executes only `guardrail.refuse`.
- Summary and failure output serialization is stable.
- The full existing test suite still passes.

Implementation follows red-green-refactor: each behavior is introduced by a failing test, the failure reason is checked, and only then is the minimal production/evaluation code added.

## Acceptance Criteria

The stage is accepted when:

1. `python -m scripts.eval_agent_actions --split test` completes without Ollama or a running backend.
2. The three expected output files are written with internally consistent counts.
3. All five routes have test coverage and per-route metrics.
4. Unsafe requests are measured separately for retrieval/generation short-circuit behavior.
5. Fresh focused tests and the complete `pytest` suite pass.
6. Project documentation records the exact command, metric definitions, actual run result, known failures, and the boundary that this is still a minimal Agentic RAG loop.

## Next Stage After This One

Use development-split failures to design a bounded adaptive controller:

```text
retrieve
-> assess evidence sufficiency
-> if insufficient, rewrite query and retry once
-> if still insufficient, return grounded no-answer
-> otherwise generate and guardrail-check
```

The held-out Agent action test split will then show whether the new branch and retry behavior improves orchestration without silently breaking unsafe short-circuiting or trace completeness.
