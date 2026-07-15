# RAG evaluation usage

Copy these files into the root of `Attempt-of-enterprise-rag-copilot` after copying `enterprise_rag_golden_set_v1/data/raw_docs` to `data/raw_docs` and `enterprise_rag_golden_set_v1/data/eval` to `data/eval`.

## Commands

```bash
# 1. Optional: repair shortened evidence strings.
python -m scripts.patch_evidence_exact

# 2. Build indexes from the new 15 documents.
python -m scripts.build_indexes

# 3. Retrieval smoke test on dev.
python -m scripts.eval_retrieval_v2 --split dev --top-k 5

# 4. Retrieval final test.
python -m scripts.eval_retrieval_v2 --split test --top-k 5

# 5. Ablation: BM25 only vs dense only vs hybrid RRF.
python -m scripts.eval_ablation_v2 --split test --top-k 5

# 6. Fusion ablation: BM25, dense, concat union, weighted score fusion, RRF.
python -m scripts.eval_fusion_ablation --split test --top-k 5
python -m scripts.eval_fusion_ablation --split test --top-k 5 --alpha 0.3
python -m scripts.eval_fusion_ablation --split test --top-k 5 --rrf-k 60

# 7. Answer eval; start small because it calls the chat model.
python -m scripts.eval_answer_v1 --split test --limit 10
python -m scripts.eval_answer_v1 --split test
python -m scripts.eval_answer_v1 --split adversarial

# 8. Agent action eval; no Ollama, indexes, or running backend required.
python -m scripts.eval_agent_actions --split dev
python -m scripts.eval_agent_actions --split test

# 9. Adaptive Agent loop control evaluation; deterministic dependencies.
python -m scripts.eval_agent_loop --split dev --mode deterministic
python -m scripts.eval_agent_loop --split test --mode deterministic

# 10. Adaptive Agent loop integration evaluation; requires indexes and Ollama.
python -m scripts.eval_agent_loop --split dev --mode live
# Freeze implementation and prompts before running held-out live test once.
python -m scripts.eval_agent_loop --split test --mode live
```

## Agent Action Metrics

Agent action evaluation isolates the orchestration layer from retrieval and answer quality. It runs the production router, planner, `AgentRunner`, and trace models, but replaces external tools with deterministic in-memory implementations.

- `route_accuracy`: fraction of questions assigned to the expected route.
- `plan_exact_match_rate`: fraction whose ordered planned tool names exactly match `expected_plan`.
- `tool_sequence_accuracy`: fraction whose executed trace tools exactly match `expected_plan`.
- `trace_complete_rate`: fraction whose plan and trace have matching tools, successful statuses, non-negative latency, and non-empty summaries.
- `unsafe_no_retrieval_rate`: unsafe cases that execute neither `retrieval.search` nor `rag.answer`, divided only by the number of unsafe cases.
- `case_pass_rate`: fraction passing every applicable check.

The held-out test split is `data/eval/agent_action_test.json`. Do not add router keywords after inspecting this file and then report the same split as an unbiased test result. Use `agent_action_dev.json` for future routing changes and rerun the test split only after the change is fixed.

For `--split test`, the generated files are:

```text
data/eval_outputs/agent_action_test_results.json
data/eval_outputs/agent_action_test_details.jsonl
data/eval_outputs/agent_action_test_failures.csv
```

The CSV contains only failed cases and records expected/actual route, plan, executed tools, trace checks, and any runner exception.

## Adaptive Agent Loop Metrics

`scripts.eval_agent_loop` evaluates the evidence-aware state machine with four scenario classes: first-pass answer, rewrite then answer, rewrite then grounded no-answer, and unsafe refusal.

- `outcome_accuracy`: expected final outcome versus `answered`, `grounded_no_answer`, `refused`, or `error`.
- `retry_decision_accuracy`: exact expected retrieval/rewrite count.
- `tool_sequence_accuracy`: exact expected tool trajectory.
- `trace_complete_rate`: selected plan and executed steps agree, every step succeeded, and evidence-history counts are consistent.
- `unsafe_no_retrieval_rate`: unsafe requests execute no retrieval, assessment, or answer generation.
- `max_retry_compliance_rate`: no more than two retrieval calls or one rewrite.
- `policy_compliance_rate`: trajectory is one of the allowed bounded paths and its final evidence verdict agrees with the outcome.
- `assessment_parse_success_rate`: live evidence assessments returned valid structured results.
- `case_pass_rate`: deterministic mode requires exact trajectory; live mode requires correct route/outcome plus complete, parseable, policy-compliant bounded execution.

The live contract intentionally permits an efficient first-pass answer for a fixture labeled `rewrite_then_answer`. Exact retry and tool metrics remain visible as diagnostics, but the evaluator does not force unnecessary tool calls merely to match one reference trajectory.

This evaluator scores orchestration outcome and policy, not full answer semantics. `gold_sources` are validated dataset metadata and recorded in details, but their coverage is not currently a `case_pass` gate. Run `eval_answer_v1` for required content, forbidden content, citation, and refusal checks.

Fresh results from 2026-07-15:

| Mode / split | Count | Outcome | Retry | Tools | Trace | Unsafe | Limit | Policy | Parse | Case pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deterministic dev | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | 1.00 |
| deterministic test | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | 1.00 |
| live dev | 16 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| live held-out test | 16 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

The frozen implementation was evaluated on the live test split once. After an independent code review found general state-contract bugs, both live splits were rerun as regression checks; dev took about 155 seconds and test took 151.1 seconds with unchanged metrics. The second test run is regression evidence, not an unseen-test claim.

Generated files follow this pattern:

```text
data/eval_outputs/agent_loop_{mode}_{split}_results.json
data/eval_outputs/agent_loop_{mode}_{split}_details.jsonl
data/eval_outputs/agent_loop_{mode}_{split}_failures.csv
```

## Notes

- Retrieval metrics skip `answerable=false` by default.
- Generated outputs are saved under `data/eval_outputs/`.
- Retrieval details are saved as JSONL files for per-question error analysis.
- Answer eval also writes `answer_{split}_error_analysis.csv`.
- Agent action eval does not call the embedding or chat model and does not measure answer quality.
- Deterministic Agent loop eval proves controller behavior, not local-model semantic quality; use live mode separately.
- The held-out live split should not be repeatedly tuned against. Add failures to a future development set instead.
- A complete trace does not imply that the route or plan was correct; inspect the metrics separately.
- `weighted_score_fusion` is an experimental baseline because dense and BM25 scores are normalized per query.
- Commit raw docs, eval JSON files, scripts, tests, and README results.
- Do not commit `data/indexes/`, `data/app.db`, or generated eval output files unless you intentionally want result snapshots.
