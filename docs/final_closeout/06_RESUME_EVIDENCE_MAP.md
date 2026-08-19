# Resume Evidence Map

| Resume-safe fact | Primary evidence | Allowed scope |
|---|---|---|
| Enterprise knowledge Agent covers ingest -> retrieval -> Agent tools -> ACL/evidence/citations -> safe output | README; architecture; code paths under `app/` | Implemented portfolio system, not production deployment |
| Replaceable runtime with bounded default and LangGraph alternative | `orchestrator.py`; A/B artifact | Architecture fact; do not claim LangGraph quality gain |
| MCP `search/find/open` stays behind ToolGateway | `mcp_adapter.py`, `tool_gateway.py`, tests | Official SDK adapter/protocol integration, in-process |
| Hash-chained trajectory, replay, Agent Run Artifact | trajectory/replay/evalops code and sample verifier | Tamper-evident local execution evidence, not WORM |
| WixQA Recall@5 42.75% -> 66.42%; nDCG@5 32.15% -> 52.16% | `wixqa_retrieval_baseline_public_v2.json` | 200 fixed ExpertWritten public-label retrieval questions |
| EnterpriseRAG-Bench 511,962 records; 231.35 s; 1.37 GiB; ~1.83 GiB peak RSS | `enterprise_rag_bench_bm25_public_v1.json` | Public corpus, one-host SQLite FTS5 build |
| Clean replay 63/63 exact | `wixqa_clean_reproduction_public_v1.json` | Consumed public labels; local reproduction |
| garak 4/12 -> 0/12 | `garak_latent_report_holdout_v1.json` | Interview/security version only; pinned subset |

The normative per-claim fields, SHAs, denominators, role targeting, and
forbidden wording are in `resume/RAG_RESUME_FACT_SHEET.md`.

