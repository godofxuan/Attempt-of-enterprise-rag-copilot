# Enterprise Experiment Registry

This file is append-only. `NOT_RUN` is a result state, not a missing detail.

| ID | Exact source SHA | Dataset / split | Hypothesis | Arms | Status | Decision / artifact |
|---|---|---|---|---|---|---|
| ENT-E0-001 | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` | Repository audit | Existing finance/security/lifecycle evidence is insufficient for the primary enterprise product claim | audit only | COMPLETE | Primary story repositioned; WixQA selected first |
| ENT-E0-002 | `d9c7294d59b166523febfcfe3b23a23c3c66b9b1` | Official benchmark sources | At most three official benchmarks cover support, heterogeneous internal knowledge, and deep search | WixQA / EnterpriseRAG-Bench / HERB plus alternatives | COMPLETE | Three-track bounded shortlist; HERB remains conditional |
| ENT-E1-001 | `NOT_FROZEN` | WixQA Synthetic / Simulated / ExpertWritten | Current BM25, dense, hybrid, and bounded Agent establish an enterprise-support baseline | B0/B1/B2/B3 | NOT_RUN | Protocol, manifest, and artifacts pending |
| ENT-E1-002 | `NOT_FROZEN` | WixQA development then fixed validation | Structure-aware article processing improves retrieval/completeness over flat chunks | WIX_FLAT / WIX_STRUCTURE_AWARE | NOT_RUN | May run only after baseline failure taxonomy |
| ENT-E2-001 | `NOT_FROZEN` | EnterpriseRAG-Bench official full corpus | Current system establishes category-level heterogeneous enterprise baseline | B0/B1/B2/B3 | CAPACITY_BLOCKED | No score until full-corpus capacity gate passes |
| ENT-E3-001 | `NOT_FROZEN` | HERB official protocol | Bounded search/open improves deep-search quality enough to justify tool cost | single-shot / bounded Agent | LICENSE_AND_CAPACITY_BLOCKED | No local data or score yet |

Each completed live experiment must add: exact Git SHA, dataset revision and
split IDs hash, model/digest, embedding, reranker, seed, hardware, command,
latency distribution, result, failures, and artifact SHA-256.

