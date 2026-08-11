# Project Evidence Map

This is the canonical claim-to-evidence index for the public portfolio. Read it
before reusing a project number in a README, interview answer, or resume. Metric
execution SHAs identify the code that produced an artifact; the current
documentation HEAD must be checked separately with `git rev-parse HEAD` and the
portfolio verifier.

Current portfolio state:
`PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW`.

That state means the repository is usable for a portfolio and interview, its
engineering evidence is credible within the stated scopes, the current
multi-document Agent candidate was rejected, blind answer correctness is not
established, the security claim is narrow, production readiness is not claimed,
and feature development is stopped.

## Claim P1: external support-KB retrieval

| Field | Binding |
|---|---|
| Claim | BGE-M3 Dense outperformed BM25 on fixed WixQA ExpertWritten retrieval. |
| Metric | Recall@5 `42.75% -> 66.42%`; nDCG@5 `32.15% -> 52.16%`; p95 `151.80 -> 157.41 ms`. |
| Scope | Retrieval ranking only; no answer generation or semantic answer judge. |
| Dataset | WixQA ExpertWritten, 200 public-label questions, 52 multi-article cases, fixed and consumed. |
| Code path | `app/external_datasets/wixqa_retrieval.py`; `scripts/eval_wixqa_retrieval.py` |
| Test path | `tests/external_datasets/test_wixqa_retrieval.py`; `tests/external_datasets/test_wixqa_public_evidence.py` |
| Evidence JSON | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` |
| Reproduction command | `python -m pytest tests/external_datasets/test_wixqa_public_evidence.py -q` verifies the public contract; the full live replay is documented in `docs/reproduction/QUICK_REPRODUCTION.md`. |
| Code SHA | `234734657fe354a0ecd767022c6f7c22cdc329da` |
| Allowed wording | "On 200 WixQA ExpertWritten retrieval questions, BGE-M3 Dense improved Recall@5 from 42.75% to 66.42% and nDCG@5 from 32.15% to 52.16%." |
| Forbidden wording | "RAG accuracy is 66.42%"; "answer accuracy improved"; "blind test"; "SOTA". |
| Interview explanation | Gold article IDs make retrieval scoring deterministic. Dense handled natural paraphrases better; equal RRF later regressed because rank fusion cannot know that the BM25 arm is weaker on this cohort. |

## Claim P2: clean local reproducibility

| Field | Binding |
|---|---|
| Claim | A fresh local source/cache/index/output replay reproduced all frozen WixQA quality values exactly. |
| Metric | `63/63` quality comparisons equal at absolute tolerance `0.0`; 11,975 embeddings rebuilt. |
| Scope | Clean-environment local regression replay of consumed public labels. |
| Dataset | WixQA Synthetic 6,221, Simulated 200, and ExpertWritten 200. |
| Code path | `scripts/reproduce_wixqa_retrieval.py`; `scripts/verify_wixqa_clean_reproduction.py` |
| Test path | `tests/external_datasets/test_wixqa_public_evidence.py`; `tests/test_final_closeout_evidence.py` |
| Evidence JSON | `docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json` |
| Reproduction command | `python -m pytest tests/test_final_closeout_evidence.py::test_clean_reproduction_is_exact_and_self_contained -q` |
| Code SHA | `4d07d6a4f14bf4eaded8ff1bd6987b8a094dc064` |
| Allowed wording | "Rebuilt 11,975 embeddings and reproduced 63 frozen retrieval values exactly from clean local roots." |
| Forbidden wording | "Independent third-party reproduction"; "new holdout"; "latency reproduced exactly". |
| Interview explanation | Clean roots rule out accidental reuse of old downloads, vectors, indexes, or results. Exact quality equality is stronger than a rounded README comparison, but the same owner and public labels prevent a third-party or blind claim. |

## Claim P3: bounded large-corpus lexical indexing

| Field | Binding |
|---|---|
| Claim | A resumable single-writer SQLite FTS5 path made the full EnterpriseRAG-Bench lexical baseline executable on one host. |
| Metric | 511,962 records, 9 source types, 1.37 GiB artifact, 231.35 s build, about 1.83 GiB peak RSS; Macro Recall@5 60.3741% on 470 questions. |
| Scope | Full-corpus lexical retrieval and build capacity; not answer quality or Dense quality. |
| Dataset | EnterpriseRAG-Bench public synthetic enterprise corpus, fixed consumed labels. |
| Code path | `app/external_datasets/enterprise_rag_bench_fts.py`; `scripts/build_enterprise_rag_bench_fts.py` |
| Test path | `tests/external_datasets/test_enterprise_rag_bench_fts.py`; `tests/test_final_closeout_evidence.py` |
| Evidence JSON | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` |
| Reproduction command | `python -m pytest tests/test_final_closeout_evidence.py::test_resume_headline_metrics_derive_from_public_evidence -q` |
| Code SHA | `955d86f1ca244bc90025c89806fd786f978b98ff` |
| Allowed wording | "Built and atomically activated a 1.37 GiB FTS5 index over 511,962 records in 231.35 seconds at about 1.83 GiB peak RSS." |
| Forbidden wording | "Production search cluster"; "60.37% answer accuracy"; "distributed multi-writer index". |
| Interview explanation | An in-memory Python BM25 representation exceeded the host budget. Disk-backed postings, checkpoints, hash verification, immutable versions, and an active pointer solved executability and recovery, not semantic retrieval quality. |

## Claim P4: retrieved-content injection guard

| Field | Binding |
|---|---|
| Claim | On one pinned external probe subset, the retrieved-content Guard reduced observed attack and context-exposure events without harming two benign controls. |
| Metric | Attack success `4/12 -> 0/12`; context exposure `12/12 -> 0/12`; benign false positives `0/2`; mean Guard scan `1.42 ms`. |
| Scope | One combination-disjoint subset of garak `LatentInjectionReport`, local Qwen3-8B. |
| Dataset | 12 attack and 2 benign cases; exact fixture hash is in the JSON. |
| Code path | `app/security/retrieved_content.py`; `app/evaluation/garak_latent_report_eval.py` |
| Test path | `tests/evaluation/test_garak_latent_report.py`; `tests/test_resume_metrics_closeout.py` |
| Evidence JSON | `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json` |
| Reproduction command | `python -m pytest tests/test_resume_metrics_closeout.py tests/evaluation/test_garak_latent_report.py -q` |
| Code SHA | `1e7ea0c9fbd037277fc5feaa733d2063d315e63a` |
| Allowed wording | "On a pinned 12-attack garak subset, Guard reduced observed ASR from 4/12 to 0/12 and context exposure from 12/12 to 0/12." |
| Forbidden wording | "100% secure"; "full garak passed"; "general benign FPR is 0%"; "production red team certified". |
| Interview explanation | OFF/ON keeps model, retrieval, fixture, prompt, and order protocol fixed so Guard is the changed factor. The tiny benign denominator and one probe family sharply limit generalization. |

## Claim P5: host-controlled evidence path

| Field | Binding |
|---|---|
| Claim | Identity, ACL admission, tool budgets, retrieved-content admission, evidence state, and final citation filtering are host-owned rather than granted by model text. |
| Metric | Mechanism contracts pass in the portfolio gate; no external answer-quality uplift is attached to this claim. |
| Scope | Software architecture and deterministic contract tests. |
| Dataset | Synthetic fixtures and offline regression cases. |
| Code path | `app/api/identity.py`; `app/retrieval/pipeline.py`; `app/agent/controller_v2.py`; `app/agent/runner_v2.py`; `app/agent/citation_verifier.py` |
| Test path | `tests/api_v2/test_identity_boundary_api.py`; `tests/retrieval/test_pipeline_acl.py`; `tests/agent_v2`; `tests/security/test_retrieved_content_guard.py` |
| Evidence JSON | Public mechanism summaries are indexed by `data/v2/public/demo_snapshot.json`; this claim does not use it as an answer-quality score. |
| Reproduction command | `python -m scripts.verify_portfolio_release` |
| Code SHA | Current implementation is bound by the verified repository HEAD, not one metric execution SHA. |
| Allowed wording | "Implemented a bounded, host-controlled RAG path with authenticated identity, ACL, evidence admission, tool budgets, and deterministic citation filtering." |
| Forbidden wording | "The Agent is more accurate"; "semantic entailment guaranteed"; "enterprise SSO integrated". |
| Interview explanation | Prompts express intent but are not an authority boundary. Python types and state transitions decide what evidence is visible, what tools may run, and what claims can be published. |

## Claim P6: process-crash recovery evidence

| Field | Binding |
|---|---|
| Claim | FTS staging and active-pointer activation recovered from tested hard process exits without mixed state. |
| Metric | FTS `30/30` trials: zero corruption/manual intervention/unrecoverable stale locks. Active pointer `12/12`: zero mixed/truncated pointers or restart failures. |
| Scope | Process termination and restart on the measured platform; not power-loss durability. |
| Dataset | Deterministic failure-injection matrices. |
| Code path | `app/external_datasets/enterprise_rag_bench_fts.py`; `app/indexing/store.py`; `app/indexing/incremental_snapshot.py` |
| Test path | `tests/test_final_evidence_closure.py`; `tests/external_datasets/test_enterprise_rag_bench_fts.py` |
| Evidence JSON | `docs/final_evidence_closure/evidence/fts_hard_crash_matrix_v1.json`; `docs/final_evidence_closure/evidence/active_pointer_crash_matrix_v1.json` |
| Reproduction command | `python -m pytest tests/test_final_evidence_closure.py -q` |
| Code SHA | The evidence manifests retain their implementation bindings; verify them through the tests above. |
| Allowed wording | "Validated 30 FTS and 12 active-pointer hard-process-exit recovery trials with no mixed state or restart failure." |
| Forbidden wording | "Power-loss safe"; "Windows directory fsync guaranteed"; "production HA". |
| Interview explanation | Atomic replace prevents readers from observing a partially written pointer after process exit. It does not prove that hardware and filesystem caches survive sudden power loss. |

## Claim N1: rejected multi-document candidate

| Field | Binding |
|---|---|
| Claim | A bounded decomposition plus selective-evidence candidate failed its pre-registered development gate and was not integrated. |
| Metric | Citation completeness `0% -> 0%`; recall `21.67% -> 24.17%`; precision `45.00% -> 39.17%`; p95 `600.09 -> 1115.59 ms`; paired complete-case fixes `0`. |
| Scope | Retrospective development-only 20-case consumed WixQA multi-document cohort. |
| Dataset | The consumed cohort frozen by `docs/multidoc_candidate/evidence/protocol_v1.json`. |
| Code path | `app/evaluation/wixqa_multidoc_candidate.py`; production paths remained unchanged. |
| Test path | `tests/evaluation/test_wixqa_multidoc_candidate.py`; `tests/evaluation/test_wixqa_multidoc_candidate_evidence.py` |
| Evidence JSON | `docs/multidoc_candidate/evidence/aggregate_v1.json`; `failure_analysis_v1.json` |
| Reproduction command | `python -m scripts.verify_wixqa_multidoc_candidate` |
| Code SHA | `d29639c8b3f037560385d5c7ad1b847dae4fc4ab` |
| Allowed wording | "Built a pre-registered multi-document release gate and rejected a candidate that added 1.86x p95 latency with zero complete-case fixes." |
| Forbidden wording | "Agent improved multi-document quality"; "validation result"; "answer accuracy"; "candidate deployed". |
| Interview explanation | The idea changed ranking and selected more sources, but it did not acquire more gold evidence, did not fix one complete case, reduced precision, and increased latency. Engineering value came from preventing an attractive but ineffective feature from shipping. |

## Evidence classes

- **Resume primary:** P1, P3, and narrowly qualified P4.
- **Interview supporting:** P2, P5, and P6.
- **Negative experiment:** N1 and the equal-RRF result embedded in P1.
- **Forbidden as quality:** oracle probes, consumed-cohort tuning, mechanism-only
  tests, local full-suite counts, and any `NOT_RUN` field.
