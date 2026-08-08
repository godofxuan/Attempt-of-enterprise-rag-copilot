# Enterprise Experiment Registry

This file is append-only. `NOT_RUN` is a result state, not a missing detail.

| ID | Exact source SHA | Dataset / split | Hypothesis | Arms | Status | Decision / artifact |
|---|---|---|---|---|---|---|
| ENT-E0-001 | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` | Repository audit | Existing finance/security/lifecycle evidence is insufficient for the primary enterprise product claim | audit only | COMPLETE | Primary story repositioned; WixQA selected first |
| ENT-E0-002 | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` | Official benchmark sources | At most three official benchmarks cover support, heterogeneous internal knowledge, and deep search | WixQA / EnterpriseRAG-Bench / HERB plus alternatives | COMPLETE | Three-track bounded shortlist; HERB remains conditional |
| ENT-E1-001 | `234734657fe354a0ecd767022c6f7c22cdc329da` | WixQA Synthetic / Simulated / ExpertWritten | BM25, BGE-M3 Dense, and equal RRF establish an enterprise-support retrieval baseline | B0/B1/B2 | COMPLETE | Dense champion; equal RRF rejected; public evidence `wixqa_retrieval_baseline_public_v1.json` |
| ENT-E1-001B | `NOT_FROZEN` | WixQA fixed baseline cohorts | Current bounded search/open policy establishes same-retriever quality/cost baseline | B2/B3 | NOT_RUN | Must not claim Agent value until implemented and paired |
| ENT-E1-002 | `NOT_FROZEN` | WixQA development then fixed validation | Structure-aware article processing improves retrieval/completeness over flat chunks | WIX_FLAT / WIX_STRUCTURE_AWARE | NOT_RUN | May run only after baseline failure taxonomy |
| ENT-E2-001 | `NOT_FROZEN` | EnterpriseRAG-Bench official full corpus | Current system establishes category-level heterogeneous enterprise baseline | B0/B1/B2/B3 | INDEX_CAPACITY_BLOCKED | Full 1.41 GB corpus verified and streamed; 1,702,370 chunks imply 36.60 GiB Python BM25 tokens plus 12.99 GiB cache/FAISS vectors; no quality score |
| ENT-E2-CAP-001 | `7c10f48d35c587edb6cf5a6d9d90c76d3f95e392` | EnterpriseRAG-Bench official full corpus, labels unused | Streaming qualification can prove whether the current builder fits before an expensive formal run | schema/quality/capacity profiler | COMPLETE | 511,962 rows; 4 reused source IDs with distinct records; 15 empty titles; 1 empty body; public evidence `enterprise_rag_bench_capacity_public_v1.json` |
| ENT-E3-001 | `NOT_FROZEN` | HERB official protocol | Bounded search/open improves deep-search quality enough to justify tool cost | single-shot / bounded Agent | LICENSE_AND_CAPACITY_BLOCKED | No local data or score yet |

Each completed live experiment must add: exact Git SHA, dataset revision and
split IDs hash, model/digest, embedding, reranker, seed, hardware, command,
latency distribution, result, failures, and artifact SHA-256.
