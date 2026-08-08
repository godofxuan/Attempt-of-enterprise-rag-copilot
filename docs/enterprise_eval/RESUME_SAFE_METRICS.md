# Enterprise Resume-safe Metrics

This file contains wording that can be traced to committed aggregate evidence.
It does not replace the broader project metrics in `docs/resume_metrics`.

## Recommended bullets

### Real support knowledge-base retrieval

> Evaluated BM25, BGE-M3 Dense, and RRF on WixQA ExpertWritten's 200 authentic
> anonymized support questions; Dense improved article Recall@5 from 42.75% to
> 66.42% and nDCG@5 from 32.15% to 52.16%, with p95 latency 151.8 to 157.4 ms.

Evidence: `evidence/wixqa_retrieval_baseline_public_v1.json`, execution
`234734657fe354a0ecd767022c6f7c22cdc329da`. This is retrieval, not answer accuracy,
and the public-label fixed cohort is not a blind holdout.

### Full-scale heterogeneous enterprise retrieval

> Replaced an estimated 36.60 GiB in-memory lexical design with a resumable,
> atomically activated SQLite FTS5 index over all 511,962 EnterpriseRAG-Bench
> rows; built a verified 1.37 GiB artifact in 231.35 s at about 1.83 GiB peak
> memory and established a 60.37% document Recall@5 full-corpus baseline.

Evidence: `evidence/enterprise_rag_bench_capacity_public_v1.json` and
`evidence/enterprise_rag_bench_bm25_public_v1.json`, executions `7c10f48` and
`955d86f`. This is B0 lexical retrieval, not end-to-end accuracy.

### Negative-result engineering

> Built same-retriever Agent/RAG paired evaluation and rejected the current
> bounded Agent route after 400 WixQA cases produced zero `find/open` calls, no
> retrieval gain, zero multi-article citation completeness, and 1.47-1.59x p95
> latency.

Evidence: `evidence/wixqa_agent_public_v1.json`, execution `07b156e`. This bullet
shows experimental judgment; it must not claim Agent quality improvement.

## Strongest three numbers for a short resume

Use the WixQA Dense improvement, the Enterprise full-corpus scale/capacity
result, and the existing external garak Guard OFF/ON result documented in
`docs/resume_metrics/RAG_RESUME_METRICS.md`. Avoid filling a resume with several
metrics from the same experiment.

## Forbidden claims

- Do not call Recall@5, nDCG@5, answered rate, or citation presence "RAG
  accuracy".
- Do not call ExpertWritten hidden, blind, independent, or untouched after use.
- Do not claim full EnterpriseRAG Dense/RRF/Agent, HERB, source-aware chunking,
  external refusal quality, or external Evidence Ledger improvement.
- Do not quote WixQA Synthetic 97.88% without labeling it development-only.
- Do not report the current Agent as better than single-shot retrieval.
