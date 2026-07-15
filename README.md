# Enterprise RAG Copilot

A local-first RAG application for question answering over enterprise-style documents.

The project uses a FastAPI backend, a Streamlit UI, local Ollama models, and hybrid retrieval with FAISS and BM25.

## Features

- Ingest Markdown and text documents
- Split documents by section and chunk them for retrieval
- Build local FAISS and BM25 indexes
- Answer questions with retrieved source context
- Return source snippets with each answer
- Run a bounded adaptive Agentic RAG loop with evidence assessment, one retry, grounded no-answer, guardrails, and trace output
- Collect simple thumbs up / thumbs down feedback
- Run basic retrieval and answer evaluation scripts

## Tech Stack

- Python
- FastAPI
- Streamlit
- Ollama
- FAISS
- BM25
- SQLite

## Project Structure

```text
app/                 # FastAPI backend and RAG pipeline
app/agent/           # Router, adaptive controller, evidence assessor, tools, runner, and trace schemas
streamlit_app/        # Streamlit UI
scripts/              # Data preparation, evaluation, and smoke-test scripts
data/raw_docs/        # Enterprise-style policy documents
data/eval/            # Golden-set evaluation data
data/eval_outputs/    # Generated local evaluation outputs
```

Generated files such as indexes, SQLite databases, caches, and local `.env` files are ignored by Git.

## Configuration

Copy the example environment file:

```powershell
copy .env.example .env
```

Default model settings:

```text
CHAT_MODEL=qwen2.5:3b
EVIDENCE_MODEL=qwen3:8b
EMBEDDING_MODEL=bge-m3
```

Other Ollama models can be used by changing the values in `.env`.

If the embedding model is changed, rebuild the index.

## Run

Install dependencies:

```powershell
pip install -r requirements.txt
```

The repository now uses the golden-set documents in `data/raw_docs/`.
Do not run `scripts.prepare_sample_docs` unless you intentionally want to restore the old toy sample documents.
The canonical evaluation data lives under `data/eval/`; the older `data/eval_questions.json` file is kept only as a small legacy smoke-test set.

```powershell
python -m scripts.build_indexes
```

Start the backend:

```powershell
uvicorn app.main:app --reload
```

Start the UI in another terminal:

```powershell
streamlit run streamlit_app/ui.py
```

Open the Streamlit UI, build the index from the sidebar, then ask a question.

Call the baseline RAG API:

```powershell
$body = @{ question = "超过14天还能申请无理由退款吗？"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/chat -Method Post -ContentType "application/json" -Body $body
```

Call the bounded Agentic RAG API:

```powershell
$body = @{ question = "超过14天还能申请无理由退款吗？"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/agent/chat -Method Post -ContentType "application/json" -Body $body
```

Example questions:

```text
退款期限是多少？
什么情况下不支持退款？
VPN 报错 691 怎么处理？
```

## Bounded Adaptive Agentic RAG

The baseline `/chat` endpoint keeps the original RAG flow: retrieve relevant chunks, build a grounded prompt, and generate an answer.

The `/agent/chat` endpoint runs a bounded evidence-aware loop:

```text
question
-> query router
-> adaptive controller
-> retrieval.search
-> evidence.assess
-> answer when sufficient
   OR rewrite and retrieve once more
   OR return a grounded no-answer
-> guardrail.check
-> answer + sources + trace
```

Current agent components:

- `app/agent/router.py`: deterministic query router for policy QA, comparison, process, likely no-answer, and unsafe requests.
- `app/agent/controller.py`: selects one next action from explicit state and enforces at most two retrieval attempts.
- `app/agent/evidence.py`: asks the independently configured local evidence model for a validated sufficient/insufficient decision and an optional rewrite.
- `app/agent/tools.py`: registers retrieval, evidence assessment, query rewrite, answer, grounded no-answer, and guardrail tools.
- `app/agent/runner.py`: executes an observe-decide-act loop, merges tool updates, and returns the final answer.
- `app/agent/trace.py` and `app/agent/schemas.py`: define trace output for route, plan, tool status, latency, and tool summaries.

The original `question` is immutable while `search_query` may be rewritten. Each retrieval stores both the latest result and a cross-attempt evidence workspace deduplicated by `chunk_id`. The controller uses the latest result to detect an empty retry, while the assessor and generator use accumulated evidence. `rag.answer` consumes that evidence through `answer_from_retrieved()` instead of silently searching again.

The verified local setup uses `qwen3:8b` for evidence assessment with Ollama `think: false`, `qwen2.5:3b` for answer generation, and `bge-m3` for embeddings. Python, not the LLM, owns retry limits, terminal states, and safety short-circuits.

This is intentionally a bounded adaptive Agentic RAG workflow, not a fully autonomous multi-tool agent. See `docs/AGENTIC_RAG_EVOLUTION_LOG.md` for the failure-driven design history, code map, experiments, and interview explanations.

## Evaluation

### Dataset

The evaluation set is a synthetic enterprise-style golden set, not real private company data.

- 15 Chinese enterprise-style policy documents
- 120 labeled questions
- Question types: `fact`, `constraint`, `list`, `process`, `comparison`, `synonym`, `no_answer`, `adversarial`
- Retrieval splits: `data/eval/retrieval_dev.json`, `data/eval/retrieval_test.json`
- Answer splits: `data/eval/answer_dev.json`, `data/eval/answer_test.json`, `data/eval/adversarial_test.json`
- Agent action splits: `data/eval/agent_action_dev.json`, `data/eval/agent_action_test.json`
- Adaptive Agent loop splits: `data/eval/agent_loop_dev.json`, `data/eval/agent_loop_test.json`

### How To Run

Build indexes:

```powershell
python -m scripts.build_indexes
```

Evaluate Hybrid RRF retrieval:

```powershell
python -m scripts.eval_retrieval_v2 --split test --top-k 5
```

Compare BM25, dense retrieval, and Hybrid RRF:

```powershell
python -m scripts.eval_ablation_v2 --split test --top-k 5
```

Compare fusion strategies:

```powershell
python -m scripts.eval_fusion_ablation --split test --top-k 5
```

Run answer evaluation:

```powershell
python -m scripts.eval_answer_v1 --split test
python -m scripts.eval_answer_v1 --split adversarial
```

Run deterministic Agent action evaluation without Ollama or indexes:

```powershell
python -m scripts.eval_agent_actions --split test
```

Run the Stage 8 adaptive loop evaluation. Deterministic mode isolates the controller; live mode uses real retrieval and local Ollama models:

```powershell
python -m scripts.eval_agent_loop --split dev --mode deterministic
python -m scripts.eval_agent_loop --split test --mode deterministic
python -m scripts.eval_agent_loop --split dev --mode live
python -m scripts.eval_agent_loop --split test --mode live
```

On Windows, if `python` points to Anaconda instead of the project virtual environment, use:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_retrieval_v2 --split test --top-k 5
```

### Metrics Explanation

- `Hit@k`: whether at least one gold source appears in the top-k retrieved chunks.
- `Recall@k`: fraction of gold sources retrieved in top-k.
- `Coverage@k`: whether all gold sources are retrieved in top-k.
- `Precision@k`: relevant retrieved chunks in top-k divided by k.
- `MRR`: reciprocal rank of the first relevant result.
- `nDCG@k`: ranking quality with binary relevance in the first version.
- `must_include_rate`: fraction of required answer points present in the model answer.
- `must_not_include_ok_rate`: fraction of answers without forbidden content.
- `citation_hit_rate`: whether returned sources include any gold source.
- `citation_coverage_rate`: whether returned sources cover all gold sources.
- `refusal_accuracy`: refusal success rate on `no_answer` and `adversarial` questions.
- `route_accuracy`: fraction of Agent questions assigned to the expected route.
- `plan_exact_match_rate`: fraction whose ordered planned tools exactly match the expected plan.
- `tool_sequence_accuracy`: fraction whose executed trace tools exactly match the expected sequence.
- `trace_complete_rate`: fraction with a structurally complete successful trace.
- `unsafe_no_retrieval_rate`: fraction of unsafe cases stopped before retrieval or generation.
- `case_pass_rate`: fraction passing every applicable Agent action check.
- `outcome_accuracy`: fraction whose final outcome is answered, grounded no-answer, refusal, or error as expected.
- `retry_decision_accuracy`: exact agreement with the fixture's expected retrieval/rewrite count; diagnostic rather than a live pass gate.
- `max_retry_compliance_rate`: fraction that stays within two retrieval calls and one rewrite.
- `policy_compliance_rate`: fraction whose trajectory is one of the allowed bounded safe/refusal paths.
- `assessment_parse_success_rate`: fraction of live evidence assessments that returned valid structured output.

`answerable=false` and ordinary `no_answer` questions are excluded from ordinary retrieval metrics and evaluated through refusal / hallucination checks.

### Current Results

The metrics below should be treated as reproducible project results only after rerunning the commands above in the current environment.
Generated result files are written under `data/eval_outputs/` and are ignored by Git.

Indexes:

- 15 documents
- 75 chunks

Retrieval test with Hybrid RRF:

- Hit@1: 0.9333
- Hit@3: 1.0
- Hit@5: 1.0
- Recall@5: 0.9917
- Coverage@5: 0.9833
- Precision@3: 0.3611
- Precision@5: 0.2167
- MRR: 0.9639
- nDCG@3: 0.9678
- nDCG@5: 0.9678

Ablation test:

| Method | Hit@1 | Hit@3 | Hit@5 | Precision@5 | MRR | nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 only | 0.8500 | 0.9833 | 0.9833 | 0.2100 | 0.9056 | 0.9146 |
| Dense only | 0.9167 | 0.9833 | 1.0000 | 0.2200 | 0.9486 | 0.9612 |
| Hybrid RRF | 0.9333 | 1.0000 | 1.0000 | 0.2167 | 0.9639 | 0.9678 |

Fusion strategy comparison:

| Method | Hit@1 | Hit@3 | Hit@5 | Recall@5 | Coverage@5 | Precision@5 | MRR | nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 only | 0.8500 | 0.9833 | 0.9833 | 0.9667 | 0.9500 | 0.2100 | 0.9056 | 0.9146 |
| Dense only | 0.9167 | 0.9833 | 1.0000 | 1.0000 | 1.0000 | 0.2200 | 0.9486 | 0.9612 |
| Concat union | 0.9167 | 0.9833 | 1.0000 | 1.0000 | 1.0000 | 0.2200 | 0.9486 | 0.9612 |
| Weighted score fusion | 0.9500 | 0.9833 | 1.0000 | 1.0000 | 1.0000 | 0.2200 | 0.9681 | 0.9744 |
| RRF fusion | 0.9333 | 1.0000 | 1.0000 | 0.9917 | 0.9833 | 0.2167 | 0.9639 | 0.9678 |

Weighted score fusion performs best on Hit@1, MRR, and nDCG@5 in this synthetic dataset, while RRF reaches perfect Hit@3 and avoids depending on the raw score scales of dense and sparse retrievers. The production pipeline keeps RRF as the conservative default and treats weighted score fusion as an experimental baseline.

### Answer Evaluation

Answer evaluation v1 runs the full RAG pipeline and checks whether the model answer covers required points, avoids forbidden claims, returns the expected sources, and refuses unanswerable questions. The current metrics are heuristic automatic checks, not a final human-graded answer quality score.

`answer_test` result:

- Count: 70
- Answerable questions: 60
- No-answer questions: 10
- `must_include_rate_avg`: 0.8083
- `must_not_include_ok_rate`: 0.9286
- `citation_hit_rate`: 1.0
- `citation_coverage_rate`: 0.9833
- `refusal_accuracy`: 0.8
- Main error types: `generation_omission` 18, `forbidden_content` 4, `refusal_error` 2, `ok` 46

Prompt optimization improved required-point coverage from the earlier pilot result of 0.7486 to 0.8083 on the full `answer_test` split. Remaining errors are mostly missing policy details and over-including unsupported terms in no-answer cases.

### Safety Evaluation

`adversarial_test` result:

- Count: 10
- `must_not_include_ok_rate`: 1.0
- `refusal_accuracy`: 1.0
- Main error types: `ok` 10

The current safety layer catches most prompt-injection and unsafe requests through refusal rules and grounded answering, but it is still rule-based and not a complete guardrail system.

### Agent Action Evaluation

The Agent action evaluator runs the production router, planner, `AgentRunner`, and trace models with deterministic in-memory tools. It measures orchestration only and does not call Ollama, embeddings, FAISS, or a running backend.

Held-out `agent_action_test` result from 2026-07-14:

| Metric | Result |
| --- | ---: |
| Count | 20 |
| Route accuracy | 0.55 |
| Plan exact match | 0.90 |
| Tool sequence accuracy | 0.90 |
| Trace complete rate | 1.00 |
| Unsafe no-retrieval rate | 0.50 |
| Case pass rate | 0.55 |

Per-route accuracy was `policy_qa=1.00`, `process=0.50`, `comparison=0.25`, `no_answer_check=0.50`, and `unsafe_request=0.50`. Nine cases failed. The misses are natural paraphrases not covered by the current keyword router, including “手续”, “差异”, “各自”, unknown topics such as employee housing or cafeteria menus, and unsafe wording such as “无视审批要求” or “跳过法务审核”.

`trace_complete_rate=1.00` means the executed plan was fully recorded; it does not mean the selected route was correct. `plan_exact_match_rate` and `tool_sequence_accuracy` remain higher because all current non-unsafe routes use the same three-tool plan. The two missed unsafe routes are the important control-flow failures: they did not short-circuit before the deterministic retrieval/answer tools.

### Adaptive Agent Loop Evaluation

Fresh 2026-07-15 results after freezing the development changes:

| Mode / split | Count | Route | Outcome | Retry decision | Tool sequence | Trace | Unsafe no retrieval | Policy | Parse | Case pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Deterministic dev | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | 1.00 |
| Deterministic test | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | 1.00 |
| Live dev | 16 | 1.00 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Live held-out test | 16 | 1.00 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Live `case_pass` uses outcome plus bounded-policy correctness, not forced exact trajectories. Four fixtures labeled `rewrite_then_answer` returned the expected `answered` outcome after the first assessment, so live retry/tool exact-match metrics are `0.75` while outcome and policy metrics remain `1.00`. The held-out live split was initially run once after development behavior was frozen. A later independent code review found general state-contract issues; after fixing them, dev and test were rerun as regression checks and retained the same metrics. The second test run is not presented as an unseen evaluation. These small synthetic sets are regression evidence, not a production generalization claim.

Stage 8 does not semantically grade every generated sentence and does not yet include `gold_sources` coverage in its pass gate. Use the separate answer evaluation for required-point, forbidden-content, citation, and refusal checks; the `1.00` Agent loop case-pass rate is not an answer-accuracy claim.

### Known Limitations

- The documents are synthetic enterprise-style data.
- Answer evaluation is heuristic and still being optimized.
- The current refusal behavior has known bad cases and should be improved before claiming strong adversarial robustness.
- The project has not yet integrated a reranker.
- The project implements a bounded adaptive Agentic RAG workflow, but not a fully autonomous open-ended Agent platform.
- The current router is deterministic and keyword-based; held-out Agent action route accuracy is 0.55.
- Agent loop data is synthetic and small; live 16/16 results must not be presented as a production accuracy estimate.
- Trace is returned by the API but is not yet persisted or visualized in Streamlit.
- nDCG uses binary relevance in the first version; it can later be upgraded to graded relevance.
- `weighted_score_fusion` uses per-query min-max score normalization and should be treated as an experimental baseline.

## Notes

- The included documents are fictional sample data.
- `data/indexes/` is generated locally after indexing.
- `data/app.db` is generated locally for feedback storage.
- `.env` should stay local and should not be committed.
