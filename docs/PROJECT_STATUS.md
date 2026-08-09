# Project Status Historical Snapshot

> 历史快照：当前状态的唯一入口是根目录
> [`PROJECT_STATUS.md`](../PROJECT_STATUS.md)。本页保留 final-closeout 阶段的
> 说明，不能覆盖根目录的时间线状态。

Snapshot date: 2026-08-10

## Decision

`PORTFOLIO_READY_STOP_DEVELOPMENT`, subject only to the final exact-SHA local and
GitHub Actions release gates. The project has enough external retrieval,
large-corpus indexing, security, lifecycle, and failure-analysis evidence for a
portfolio and resume. It is not production certified and has no production SLO.

## What is verified

- WixQA fixed external retrieval: on 200 ExpertWritten questions, BGE-M3 Dense
  achieved 66.42% Article Recall@5 and 52.16% nDCG@5. BM25 was 42.75%/32.15%;
  equal RRF was 59.25%/47.16% and was rejected.
- WixQA clean reproduction: official data was downloaded into a new root, all
  11,975 chunk embeddings and the index were rebuilt in new roots, and 63/63
  frozen quality values matched historical public v2 evidence exactly at zero
  tolerance. This is a regression replay of consumed public labels, not blind.
- EnterpriseRAG-Bench: a single-writer, resumable SQLite FTS5 builder produced
  and atomically activated a verified 1.37 GiB index over 511,962 rows from nine
  source types. Build time was 231.35 s at about 1.83 GiB peak RSS.
- Enterprise retrieval: lexical Macro Recall@5 was 60.3741% over 470 scored
  questions. A full record-aware sensitivity audit found one affected question;
  the sensitivity value is 60.2677%, a 0.1064 percentage-point reduction.
- Retrieved-content security: on a pinned 12-attack garak subset, Guard changed
  ASR from 4/12 to 0/12 and context exposure from 12/12 to 0/12, with two benign
  controls preserved and 1.42 ms mean scan time.
- Host-owned boundaries cover identity/ACL, typed tool budgets, retrieved-content
  admission, evidence ledger, citation filtering, lifecycle activation,
  observability, and safe terminal states.

## What is rejected or limited

- Equal-weight WixQA RRF is rejected because it reduced Dense quality and almost
  doubled p95 latency.
- The paired WixQA Agent route is rejected: it used search once, never selected
  find/open, added latency, and did not improve retrieval or citation completeness.
- A 27-case retrospective multi-document Agent experiment improved completeness
  but harmed precision and has no fresh unconsumed validation; it remains HOLD.
- Full Enterprise Dense is NO-GO: capacity is measured, but a resumable sharded
  builder and fresh quality protocol are absent.
- Answer correctness, semantic citation quality, production traffic, SLOs,
  independent holdout, and universal security are not claimed.

## Operating contracts

- FTS5 is `SINGLE_WRITER_OFFLINE_BUILDER` plus `ATOMIC_ACTIVATION`, not a
  distributed online index service.
- Local demo identity is a reproducible RSA/JWKS simulation, not a real IdP.
- Raw external corpora, model caches, indexes, keys, tokens, and detailed run
  rows remain ignored under repository-local `.private` paths.
- Public claims must resolve to schema-validated aggregate JSON and execution
  SHAs; development, fixed-public, and holdout evidence classes remain distinct.

## Evidence entry points

- `README.md`
- `docs/reproduction/QUICK_REPRODUCTION.md`
- `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json`
- `docs/final_closeout/02_REUSED_SOURCE_ID_SENSITIVITY.md`
- `docs/enterprise_eval/RESUME_SAFE_METRICS.md`
- `docs/handoffs/RESUME_CODEX_UPDATE.md`
- `docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md`
- `docs/learning/RAG_INTERVIEW_UPDATE.md`

## Stop and resume triggers

Stop adding features after release. Resume Agent work only with a genuinely new,
unconsumed multi-document enterprise validation set or recurring real-user
failure pattern. Resume full Dense only after hardware capacity, resumable shard
construction, and a fresh quality protocol all exist. Framework additions such
as LangGraph, GraphRAG, Redis, Kafka, or MCP require evidence that a measured
bottleneck needs them.
