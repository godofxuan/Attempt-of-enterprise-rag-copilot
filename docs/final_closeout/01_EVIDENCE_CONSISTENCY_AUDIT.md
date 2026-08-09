# Evidence Consistency Audit

## Claim status vocabulary

`CURRENT_VERIFIED`, `HISTORICAL_VERIFIED`, `LIMITED`, `DEVELOPMENT_ONLY`,
`REJECTED`, `NOT_RUN`, and `FORBIDDEN` are evidence states, not marketing
labels.

## Initial audit

| Claim | Status | Authoritative evidence | Audit result |
|---|---|---|---|
| WixQA ExpertWritten BM25/Dense/equal-RRF retrieval | `HISTORICAL_VERIFIED` | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` | v2 contains all three protocol arms and all frozen aggregate fields |
| Resume WixQA pointer | `CURRENT_VERIFIED` after this sprint fix | `docs/enterprise_eval/RESUME_SAFE_METRICS.md` | stale v1 pointer changed to self-contained v2; numeric claim unchanged |
| EnterpriseRAG FTS5 full-corpus retrieval | `CURRENT_VERIFIED` | `enterprise_rag_bench_bm25_public_v1.json` | 511,962 physical rows, 470 retrieval cases, retrieval-only semantics |
| Reused Enterprise source-ID sensitivity | `NOT_RUN` at pre-flight | capacity evidence and private fixed details | requires explicit record-identity sensitivity closeout |
| Garak LatentInjectionReport subset | `LIMITED` | `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json` | 12 attacks and 2 benign controls; not full garak or universal safety |
| Multi-document Agent candidate | `REJECTED` | `MULTIDOC_FAST_TRACK_PUBLIC.json` | completeness gain accompanied by material citation-precision loss |
| Full Enterprise Dense quality | `NOT_RUN` | `ENTERPRISE_DENSE_CAPACITY_PUBLIC.json` | capacity measured; persistent full index and quality evaluation not run |
| Answer/citation end-to-end external quality | `NOT_RUN` | WixQA retrieval evidence claim boundary | retrieval metrics must not be described as answer accuracy |
| Production proof | `FORBIDDEN` | project-wide evidence boundary | no production traffic, SLO, or third-party production verification |

## Deterministic contract

`tests/external_datasets/test_wixqa_public_evidence.py` now requires the resume
pointer to target v2 and requires v2 to contain the BM25, Dense, and equal-RRF
aggregates declared by the frozen protocol. A stale v1 reference or missing arm
fails CI.

This audit is finalized after clean reproduction, reused-ID sensitivity, public
JSON validation, local gates, and exact-HEAD remote Actions.
