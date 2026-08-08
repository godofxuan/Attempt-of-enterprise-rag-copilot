# Enterprise-aligned evaluation

This directory is the audit trail for repositioning the repository as an
Enterprise Knowledge RAG / Agent Copilot. It does not replace the historical
FinanceBench, FinQA, or UDA evidence. Those datasets remain a separate
`COMPLEX_DOCUMENT_TABLE_STRESS` track.

Read in this order:

1. `PRE_FLIGHT.md`: exact repository state and existing capabilities.
2. `BENCHMARK_GAP_ANALYSIS.md`: what the old evidence can and cannot prove.
3. `DATASET_SELECTION.md`: official-source research and the bounded shortlist.
4. `DATA_PROCESSING_DESIGN.md`: source-preserving canonicalization and controls.
5. `CONSUMPTION_LEDGER.md`: immutable development/test consumption labels.
6. `CAPACITY_PLAN.md`: local storage/compute qualification before large runs.
7. `EXPERIMENT_REGISTRY.md`: append-only experiment decisions.
8. `ENTERPRISE_BASELINE.md`: measured WixQA, EnterpriseRAG, and Agent results.
9. `ENTERPRISE_FAILURE_ANALYSIS.md`: deterministic full-corpus failure taxonomy.
10. `NEGATIVE_RESULTS.md`: rejected candidates and operational incidents.
11. `FINAL_REPORT.md`: final answers, Go/No-Go decisions, and remaining gaps.
12. `RESUME_SAFE_METRICS.md`: claim wording bound to public evidence.

The governing loop is:

`benchmark failure -> taxonomy -> hypothesis -> minimal candidate -> paired experiment -> Go/No-Go`

No framework, model, parser, or agent route is promoted without paired evidence.

Current closeout: WixQA Dense is the accepted customer-support retrieval
baseline; the current WixQA bounded Agent route is rejected; EnterpriseRAG-Bench
has a complete 511,962-row disk-backed B0 run, while Dense/RRF/Agent remain
`NOT_RUN` on that corpus.
