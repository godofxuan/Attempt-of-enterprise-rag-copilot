# Interview Demo Runbook

## Before the interview

Run from the repository root. Keep raw corpora, keys, caches, and indexes in
ignored repository-local paths. Prepare the small synthetic demo rather than
the 511k external corpus.

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_portfolio_release
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity init --force
.\.venv\Scripts\python.exe -m pytest tests\agent_v2 tests\retrieval\test_pipeline_acl.py tests\security\test_retrieved_content_guard.py -q
```

The first command is the authoritative offline portfolio gate. The focused
pytest command is repeated only so an interviewer can see the specific Agent,
ACL, and Guard scope without reading the aggregate JSON.

Start the API and UI in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py --server.address 127.0.0.1 --server.port 8501
```

## Ten-minute path

1. **Problem and boundary, 1 minute.** Explain that this is an enterprise
   knowledge RAG and bounded Agent Copilot. The Python host owns identity, ACL,
   tools, evidence admission, citations, and terminal states.
2. **Normal question, 2 minutes.** Ask a policy question. Show the answer,
   visible sources, and that citations refer to admitted evidence.
3. **ACL difference, 2 minutes.** Switch to a persona without the required
   group. Repeat the question and show that hidden evidence never enters the
   prompt, trace, or citation result.
4. **Trace, 2 minutes.** Show typed search/open actions, budgets, evidence
   coverage, stop reason, and aggregate security fields. Do not call an
   `answered` state correctness.
5. **Evidence, 2 minutes.** Open the Evaluation page. Lead with WixQA Dense
   66.42% Recall@5 and 52.16% nDCG@5, then the 511,962-row FTS build and the
   garak OFF/ON result. State each denominator and limitation.
6. **Engineering decision, 1 minute.** Explain that equal RRF and the current
   external Agent route were rejected because measured quality/cost gates failed.

## Twenty-minute path

Use the ten-minute path, then add: clean WixQA replay and zero-tolerance
verification; FTS staging/single-writer/atomic activation; a retrieved-content
injection example; citation negation checks; Reused Source ID sensitivity; and
the STOP/RESUME triggers in `docs/PROJECT_STATUS.md`.

## Failure-safe path

The interview must still work if Ollama or the API is unavailable:

- show `docs/assets/ask.png`, `trace.png`, and `evaluation.png`;
- open `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json` and
  point to `status: VERIFIED`, zero tolerance, and zero differences;
- open `docs/final_closeout/02_REUSED_SOURCE_ID_SENSITIVITY.md` to demonstrate
  honest metric-boundary analysis;
- run only the deterministic evidence tests and public audit;
- prefer `python -m scripts.verify_portfolio_release` so every offline gate is
  reported under one stable schema;
- never improvise a new model run or claim screenshots as live output.

## Claims to avoid

Do not say production-ready, blind test, answer accuracy 66.42%, RAG accuracy
60.37%, Agent quality improvement, full Enterprise Dense, universal safety,
SOTA, GraphRAG, MCP, or production SLO. Use retrieval metric names exactly.
