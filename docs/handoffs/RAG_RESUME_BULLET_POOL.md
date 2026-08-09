# RAG Resume Bullet Pool

Select at most 3-4 bullets and keep each qualifier. Evidence paths are part of
the contract; do not rewrite Recall@5 as accuracy.

## AI / RAG roles

1. Built a hybrid enterprise knowledge retrieval benchmark on 200 authentic
   anonymized WixQA support questions; BGE-M3 Dense improved article Recall@5
   from 42.75% to 66.42% and nDCG@5 from 32.15% to 52.16%, with p95 latency
   increasing only 151.8 to 157.4 ms. Evidence: `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`.
2. Implemented a bounded enterprise Agent with typed search/find/open tools,
   evidence ledger, budgets, ACL-preserving tool boundaries, and host-side
   citation filtering; used paired external evaluation to reject a no-gain
   Agent route instead of promoting mechanism-only results. Evidence:
   `docs/enterprise_eval/evidence/wixqa_agent_public_v1.json`.
3. Designed an indirect prompt-injection Guard and OFF/ON protocol on a pinned
   garak subset, reducing ASR 4/12 to 0/12 and context exposure 12/12 to 0/12
   with 1.42 ms mean scan latency. Evidence:
   `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json`.
4. Added deterministic citation checks for source visibility, lexical/numeric/
   date consistency, and asymmetric English/Chinese negation; protected the fix
   with 22 focused tests. Evidence: `app/agent/citation_verifier.py` and
   `tests/agent_v2/test_citation_verifier.py`.
5. Built hash-bound external-evaluation evidence and consumption controls that
   separate development, public-label fixed, and fresh holdout claims; retained
   rejected RRF/Agent experiments to prevent test-set tuning. Evidence:
   `docs/enterprise_eval/CONSUMPTION_LEDGER.md` and
   `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json`.

## Python backend roles

1. Replaced an estimated 36.60 GiB in-memory BM25 design with a resumable,
   single-writer SQLite FTS5 index over 511,962 records; built a verified 1.37
   GiB artifact in 231.35 s at about 1.83 GiB peak RSS. Evidence:
   `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`.
2. Implemented staging verification, deterministic manifests/checkpoints,
   fail-fast writer exclusion, and atomic active-version switching with
   interruption/concurrency regression tests. Evidence:
   `app/external_datasets/enterprise_rag_bench_fts.py` and
   `tests/external_datasets/test_enterprise_rag_bench_fts.py`.
3. Built FastAPI identity and authorization boundaries using pinned RS256/JWKS,
   server-derived tenant/region/group context, safe errors, receipt-bound
   feedback, readiness, traces, and bounded model retries. Evidence:
   `docs/architecture.md` and `docs/security/r2_s5/`.
4. Added aggregate-only public evidence publication, SHA-256 bindings, secret/
   path/large-file audits, and Ubuntu/Windows/container CI contracts. Evidence:
   `scripts/audit_public_repo.py` and `.github/workflows/ci.yml`.

## Bank / state-owned enterprise AI roles

1. Built an auditable enterprise knowledge copilot where identity/ACL,
   retrieved-content admission, evidence completeness, citations, and terminal
   refusal states are controlled by trusted host code rather than model prompts.
   Evidence: `docs/architecture.md`.
2. Evaluated retrieval on a 511,962-record, nine-source enterprise-style corpus
   and reported Recall@5, nDCG@5, multi-document completeness, latency, build
   time, disk, and memory without presenting retrieval as business accuracy.
   Evidence: `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`.
3. Added versioned knowledge lifecycle controls for canonical source events,
   idempotency/conflict ledgers, staging/quarantine, tombstones, immutable
   snapshots, atomic activation, rollback, and audit evidence. Evidence:
   `docs/lifecycle/02_DECISIONS.md` and `docs/lifecycle/03_RESULTS.md`.
4. Established retrieved-content prompt-injection OFF/ON security evaluation
   and preserved its small-sample boundary instead of claiming universal
   safety. Evidence: `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json`.
