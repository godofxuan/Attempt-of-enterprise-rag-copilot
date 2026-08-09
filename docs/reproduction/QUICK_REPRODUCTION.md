# Quick Reproduction

All commands run from the repository root. Generated corpora, indexes, identity
keys, model caches, and raw benchmark files stay in ignored repository-local
paths. No author-specific absolute path is required.

## 1. Install

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item .env.example .env
```

## 2. Deterministic clone gate, no local model required

```powershell
.\.venv\Scripts\python.exe -m compileall -q app scripts streamlit_app tests
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded --output-dir .private\reproduction\expanded
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --input-dir .private\reproduction\expanded --profile expanded --dry-run
.\.venv\Scripts\python.exe -m pytest tests\agent_v2 tests\retrieval\test_pipeline_acl.py tests\security\test_retrieved_content_guard.py -q
.\.venv\Scripts\python.exe -m scripts.audit_public_repo
```

This checks corpus contracts, Agent state/tool behavior, ACL filtering,
retrieved-content Guard behavior, public paths, secrets, and committed evidence.
It does not reproduce live model quality.

## 3. Inspect external evidence without downloading large corpora

```powershell
.\.venv\Scripts\python.exe -m pytest tests\external_datasets\test_wixqa_public_evidence.py tests\external_datasets\test_wixqa_multidoc_fast_track.py tests\external_datasets\test_enterprise_dense_capacity_evidence.py -q
```

Read these aggregate artifacts:

- `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`
- `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`
- `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json`
- `docs/rapid_upgrade/evidence/MULTIDOC_FAST_TRACK_PUBLIC.json`
- `docs/rapid_upgrade/evidence/ENTERPRISE_DENSE_CAPACITY_PUBLIC.json`

## 4. Build the small live demo

Install Ollama separately and make `bge-m3` plus the configured chat model
available. Then run:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded --output-dir data\v2\generated\expanded
$runId = "local-expanded-$(Get-Date -Format yyyyMMddHHmmss)"
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --input-dir data\v2\generated\expanded --output-dir data\indexes_v2 --profile expanded --run-id $runId --chunker fixed
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity init --force
```

Start the API and UI in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`. The Ask/Trace workflow demonstrates retrieval,
bounded Agent decisions, citations, ACL-scoped personas, and safe outcomes.

## 5. Large benchmark boundary

WixQA raw data/indexes and the 511,962-row EnterpriseRAG-Bench corpus are not in
Git. Their download/build scripts require explicit commands and store assets
under `.private/external`. Full Dense is intentionally not part of CI: the 50k
qualification projects 12.87 hours and the full-run gate is currently NO-GO.
