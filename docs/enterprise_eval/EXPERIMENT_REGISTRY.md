# Enterprise Experiment Registry

This file is append-only. `NOT_RUN` is a result state, not a missing detail.

| ID | Exact source SHA | Dataset / split | Hypothesis | Arms | Status | Decision / artifact |
|---|---|---|---|---|---|---|
| ENT-E0-001 | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` | Repository audit | Existing finance/security/lifecycle evidence is insufficient for the primary enterprise product claim | audit only | COMPLETE | Primary story repositioned; WixQA selected first |
| ENT-E0-002 | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` | Official benchmark sources | At most three official benchmarks cover support, heterogeneous internal knowledge, and deep search | WixQA / EnterpriseRAG-Bench / HERB plus alternatives | COMPLETE | Three-track bounded shortlist; HERB remains conditional |
| ENT-E1-001 | `234734657fe354a0ecd767022c6f7c22cdc329da` | WixQA Synthetic / Simulated / ExpertWritten | BM25, BGE-M3 Dense, and equal RRF establish an enterprise-support retrieval baseline | B0/B1/B2 | COMPLETE | Dense champion; equal RRF rejected; public evidence `wixqa_retrieval_baseline_public_v1.json` |
| ENT-E1-001B | `07b156ed4d1b4e7ff24a06aac7a8d8b41630e03b` | WixQA Simulated + ExpertWritten fixed baseline cohorts | Current bounded search/open policy establishes same-retriever quality/cost baseline | B2/B3 | COMPLETE_REJECTED | Search recall unchanged; find/open 0; multi-doc citation complete 0%; p95 1.59x/1.47x; `AGENTIC_ROUTE_REJECTED` |
| ENT-E1-002 | `NOT_FROZEN` | WixQA development then fixed validation | Structure-aware article processing improves retrieval/completeness over flat chunks | WIX_FLAT / WIX_STRUCTURE_AWARE | NOT_RUN | May run only after baseline failure taxonomy |
| ENT-E2-001 | `955d86f1ca244bc90025c89806fd786f978b98ff` | EnterpriseRAG-Bench official full corpus | Current system establishes category-level heterogeneous enterprise baseline | B0/B1/B2/B3 | PARTIAL_B0_COMPLETE | Full-corpus FTS5 B0 complete; B1 dense, B2 RRF, B3 Agent remain `NOT_RUN` |
| ENT-E2-CAP-001 | `7c10f48d35c587edb6cf5a6d9d90c76d3f95e392` | EnterpriseRAG-Bench official full corpus, labels unused | Streaming qualification can prove whether the current builder fits before an expensive formal run | schema/quality/capacity profiler | COMPLETE | 511,962 rows; 4 reused source IDs with distinct records; 15 empty titles; 1 empty body; public evidence `enterprise_rag_bench_capacity_public_v1.json` |
| ENT-E2-B0-001 | `955d86f1ca244bc90025c89806fd786f978b98ff` | EnterpriseRAG-Bench 470 document-grounded questions / full 511,962-row corpus | Disk-backed FTS5 can establish a bounded full-corpus lexical baseline | BM25 FTS5 B0 | COMPLETE | Recall@5 60.37%, MRR@5 57.96%, nDCG@5 55.89%, multi-doc complete@5 28.26%, p95 1,821.0 ms |
| ENT-E4-001 | `ad3005201e73dd7d5af3d8621c39b3e9c670bbca` | EnterpriseRAG-Bench B0 private detail, 470 cases | Deterministic failure priority identifies the next evidence-backed candidate | retrieval miss / multi-doc incomplete / wrong document / OK | COMPLETE | 153 / 59 / 58 / 200; semantic contributes 80 misses; taxonomy CSV hash-bound |
| ENT-E4-002 | `d29639c8b3f037560385d5c7ad1b847dae4fc4ab` | WixQA ExpertWritten frozen consumed 20-case multi-document subset | Bounded clause-query fusion plus admitted-only selective evidence improves complete citations without repeating the prior precision collapse | current / decompose-only / select-only / combined | COMPLETE_REJECTED | Completeness `0% -> 0%`, citation recall `+2.50 pp`, precision `-5.83 pp`, p95 `1.859x`, paired fixes `0`; no validation or serving promotion; `docs/multidoc_candidate/evidence/aggregate_v1.json` |
| ENT-E3-001 | `NOT_FROZEN` | HERB official protocol | Bounded search/open improves deep-search quality enough to justify tool cost | single-shot / bounded Agent | LICENSE_AND_CAPACITY_BLOCKED | No local data or score yet |

Each completed live experiment must add: exact Git SHA, dataset revision and
split IDs hash, model/digest, embedding, reranker, seed, hardware, command,
latency distribution, result, failures, and artifact SHA-256.
