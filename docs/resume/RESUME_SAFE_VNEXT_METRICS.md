# Resume-safe vNext metrics

This ledger separates externally meaningful results from small mechanism tests.
Do not move an item to a stronger category without a new frozen protocol and
artifact.

## VERIFIED_POSITIVE

The strongest resume metrics remain the independently scoped project metrics,
not the new five-case harness test:

| Claim | Dataset / N | Metric | Evidence | Boundary |
|---|---|---|---|---|
| Dense retrieval improved a public support-KB benchmark | WixQA ExpertWritten, 200 questions | Recall@5 `42.75% -> 66.42%`; nDCG@5 `32.15% -> 52.16%`; p95 `151.8 -> 157.4 ms` | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` | retrieval, not answer accuracy |
| Built and atomically activated a large lexical index | EnterpriseRAG-Bench-derived public corpus, 511,962 records / 9 types | 1.37 GiB index in 231.35 s, about 1.83 GiB peak RSS | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` | one-host benchmark, not production capacity |
| Reduced observed indirect-injection attacks in a pinned subset | garak LatentInjectionReport subset, 12 attacks | ASR `4/12 -> 0/12`; context exposure `12/12 -> 0/12`; mean scan 1.42 ms | `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json` | one subset, not universal safety |

Use the exact SHA and command embedded in each artifact. These results predate
vNext but remain valid because the baseline path and evidence files were not
overwritten.

## INTERVIEW_ONLY

### Agent Runtime parity diagnostic

- implementation SHA: `d20382d111cc6ee5a54a1daad92454ecf0c501f3`
- evidence commit: `4a6bfb400f042f2a4417f7c74da9a16103604ac4`
- dataset: 5 deterministic in-repo mechanism cases
- arms: existing bounded controller vs LangGraph StateGraph
- command: `.\.venv\Scripts\python.exe -m scripts.eval_agent_runtime_ab`
- artifact: `docs/agent_runtime/evidence/agent_runtime_ab_v1.json`
- result: both arms `5/5` task success, `100%` behavioral parity, zero
  permission violations, mean `0.8` tool calls and `1.8` steps
- latency: bounded p95 `1.283 ms`; LangGraph p95 `6.838 ms`

This is useful in an interview because it demonstrates controlled migration and
negative-result judgment. It is too small and synthetic to be a headline resume
quality metric.

### EvalOps artifact

- generator SHA: `9ff917bdf99b971a59754b731176e85d61f570e6`
- sample evidence commit: `e6c41c56a0ffed59b895b482e60b7d1911ba0364`
- schema: `enterprise.agent-run/1.0`
- sample: one deterministic answered run with 13 ordered events
- internal artifact hash: `f9d32f1bff44a27bbde1bf92b47800d396c9700a8120c135abf9b842b8108233`
- file: `docs/agent_runtime/evidence/agent_run_artifact_sample_v1.json`
- verifier: `.\.venv\Scripts\python.exe -m scripts.verify_agent_run_artifact docs\agent_runtime\evidence\agent_run_artifact_sample_v1.json`

Safe wording: "Designed a versioned Agent Run Artifact with append-only
hash-chained trajectories, deterministic replay, schema validation, and tamper
detection for EvalOps ingestion."

## NEGATIVE_OR_LIMITED

1. LangGraph did not improve outcome quality on the controlled mechanism set and
   added about `5.33x` p95 orchestration latency in that tiny local diagnostic.
2. The first A/B run had arm-order cold-start bias because bounded initialized
   jieba first. It was rejected; one discarded warm-up per arm was added before
   publishing the accepted artifact.
3. HITL is a real interrupt/resume flow, but its checkpointer and pending-review
   registry are in memory. Restart recovery is not implemented.
4. MCP uses the official SDK and real tools through the gateway, but only
   in-process dispatch is tested. Production network transport is not deployed.
5. SQLite trajectory storage detects mutation through triggers and hashes, but
   it is not immutable external audit storage.

## DO_NOT_CLAIM

- "LangGraph improved answer accuracy" or "LangGraph is faster".
- "5/5 proves 100% Agent accuracy" or any production SLO based on five cases.
- "production MCP server" or "OAuth-secured MCP deployment".
- "durable execution" or "crash-safe HITL resume".
- "100% safe", "prompt injection solved", or universal attack prevention.
- "multi-agent system", "autonomous file/SQL access", or implemented Skills.
- "independent third-party reproduction" of the vNext runtime.
- any claim that retrieval Recall@5 is end-to-end answer accuracy.

