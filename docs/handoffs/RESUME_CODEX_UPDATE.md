# Resume Codex Update

## Release identity

- Repository: `godofxuan/Attempt-of-enterprise-rag-copilot`
- Branch: `codex/rag-eval-system`
- Release payload SHA: `dad6336a3fb0094b625a4371bfbd716f2e67f93e`
- Release payload CI: `success`, Run
  [`31325310671`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/31325310671),
  Ubuntu/Windows/Linux-container all passed
- Project status: `PORTFOLIO_READY_STOP_DEVELOPMENT`
- Clean reproduction: `VERIFIED`, 63/63 frozen quality values exact at tolerance 0
- Production status: `NOT_CLAIMED`

The payload SHA and CI were recorded only after the exact-SHA run completed.
The following metadata-only commit does not change metric artifacts or runtime
code; its exact remote result is reported in the final delivery message. Metric
execution SHAs below are immutable.

## Top verified positive claims

| Claim | Metric/value | Dataset/denominator | Evidence class | Execution SHA | Public evidence | Limitation |
|---|---|---|---|---|---|---|
| Dense beats BM25 for support-KB retrieval | Recall@5 `42.75% -> 66.42%`; nDCG@5 `32.15% -> 52.16%`; p95 `151.8 -> 157.4 ms` | WixQA ExpertWritten, 200 questions, 52 multi-article | Fixed public-label external retrieval | `234734657fe354a0ecd767022c6f7c22cdc329da` | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` | Retrieval only; not blind or answer accuracy |
| WixQA result reproduces from clean roots | `63/63` quality values exact; tolerance `0.0`; fresh 11,975-chunk index/cache | WixQA Synthetic 6,221 + Simulated 200 + ExpertWritten 200 | Clean local regression replay | `4d07d6a4f14bf4eaded8ff1bd6987b8a094dc064` | `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json` | Consumed public labels; not third-party reproduction |
| Full lexical index fits one host | 511,962 rows/9 sources; 1.37 GiB; 231.35 s; about 1.83 GiB peak; Recall@5 60.3741%/470 | EnterpriseRAG-Bench full corpus | Fixed public-label external lexical retrieval + capacity | `955d86f1ca244bc90025c89806fd786f978b98ff` | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` | Retrieval only; record-aware sensitivity 60.2677%; full Dense not run |
| Retrieved-content Guard blocks selected external probes | ASR `4/12 -> 0/12`; exposure `12/12 -> 0/12`; mean scan 1.42 ms | Pinned garak LatentInjectionReport, 12 attacks + 2 benign | Combination-disjoint external-probe holdout | `1e7ea0c9fbd037277fc5feaa733d2063d315e63a` | Small subset; not full garak or universal safety |

## Strong engineering claims

- FTS5 is an explicit single-writer offline builder with resumable staging,
  integrity/count/hash verification, fail-fast writer exclusion, immutable
  versions, and atomic active-pointer replacement. Interruption, verification
  failure, and concurrency are covered by failure-injection tests.
- Identity/ACL, retrieved-content admission, typed tool budgets, evidence
  completeness, citations, and terminal refusal states are owned by Python host
  code rather than delegated to model prompts.
- Development, fixed-public, holdout, mechanism-only, and NOT_RUN evidence are
  kept separate; rejected RRF and Agent experiments remain visible.
- Reused source IDs were audited over the full 511,962-row corpus. One of 470
  scored questions is affected; record-aware Macro Recall@5 differs by only
  0.1064 percentage points, and the limitation is public.

## Rejected and historical-only results

- Equal RRF: rejected; ExpertWritten Recall@5 59.25% versus Dense 66.42%, p95
  304.6 versus 157.4 ms.
- WixQA paired Agent route: rejected; no retrieval gain, find/open 0, multi-
  article citation completeness 0%, higher latency.
- Multi-document retrospective: development-only completeness 0% -> 22.22%,
  precision 44.44% -> 18.52%; HOLD with no unconsumed validation.
- Synthetic WixQA Dense Recall@5 97.88% is development-only and must not be a
  resume headline.
- Old local/full-suite pass counts are historical snapshots, not product quality.

## NOT_RUN or not claimed

Full Enterprise Dense/RRF/Agent quality, WixQA answer correctness, semantic
citation judge/human agreement, production traffic, SLO, real IdP, distributed
multi-writer indexing, independent WixQA reproduction, universal security,
SOTA, LangGraph, GraphRAG, MCP, Redis, and Kafka.

## Forbidden claims

- Do not call Recall@5 "accuracy".
- Do not say "RAG accuracy 60.37%" or "answer accuracy 66.42%".
- Do not claim Agent quality improved, production-ready, blind test, 100% safe,
  full garak, full Enterprise Dense, production QPS/SLO, or third-party replay.
- Do not hide denominators, evidence class, or rejected results from the resume
  generation process, even though negative experiments need not appear in the
  final one-page resume.
