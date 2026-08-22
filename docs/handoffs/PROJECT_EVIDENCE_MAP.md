# Project Evidence Map

## Claim P11: Start/Resume lifecycle integrity

| Field | Binding |
|---|---|
| Claim | The access-request DRAFT approval path supports same-key idempotent Start, approval generations, generation-bound checkpoints, recoverable non-authorizing Handles, and separately fenced Start/Resume ownership. |
| Metric | Local deterministic Start lifecycle suite: `21 passed`; combined Agent Runtime suite: `123 passed, 2 PostgreSQL skipped`; exact remote CI pending the implementation commit. |
| Current status | `IMPLEMENTATION_COMPLETE`; `EXACT_SHA_CI_REQUIRED`; final SHA is intentionally not predicted before the two-stage evidence process. |
| Scope | `ACCESS_REQUEST_DRAFT_ONLY`; `NOT_MERGED`; `NOT_RELEASED`; `PORTFOLIO_READY`; `PRODUCTION_NOT_VERIFIED`. |
| Dataset | Deterministic approval, generation, checkpoint, identity, concurrency, crash-injection, response-loss, migration, and privacy fixtures; no model or retrieval dataset. |
| Code path | `app/agent_runtime/durable_store.py`; `durable_orchestrator.py`; `harness_contract.py` |
| Test path | `tests/agent_runtime/test_start_lifecycle.py`; `test_durable_orchestrator.py`; `test_harness_contract.py` |
| Evidence JSON | `docs/review/FINAL_RESUME_READINESS_MANIFEST.json` after stage-two evidence binding. |
| Reproduction command | `python -m pytest tests/agent_runtime/test_start_lifecycle.py tests/agent_runtime/test_durable_orchestrator.py -q`; complete commands are recorded in the final readiness entry. |
| Code SHA | `EXACT_SHA_CI_REQUIRED` until the implementation commit is created and its GitHub Actions run succeeds. |
| Failure evidence | Seven Start crash points, missing client acknowledgement, two-thread/two-process Start, stale Start owner recovery, existing Resume crash matrix, and final single-fact assertions. |
| Security boundary | Handle locates an approval but never replaces service authentication, tenant binding, reviewer role, ACL/policy, expiry, or argument-hash checks. |
| Invariants | `docs/production_runtime/APPROVAL_LIFECYCLE_INVARIANTS.md` |
| Final evidence | `docs/review/FINAL_RESUME_READINESS_ENTRY.md` and `FINAL_RESUME_READINESS_MANIFEST.json` after implementation CI succeeds. |
| Allowed wording | "Implemented idempotent Start/Resume recovery with database CAS, leases, versions and approval generations for an access-request draft workflow." |
| Forbidden wording | "Entire Agent runtime is durable"; "exactly-once"; "production HITL"; "multi-instance HA". |
| Interview explanation | Start and Resume use separate database ownership fences; one Start key selects one generation, while a recoverable Handle remains a locator and never replaces authorization. |

P11 supersedes only the lifecycle scope of P10. It does not change any frozen
retrieval, answer, indexing, or prompt-injection metric.

## Claim P10: durable approval completion integrity

| Field | Binding |
|---|---|
| Claim | The access-request DRAFT approval path uses database CAS, expiring ownership leases, version fencing, and a transactionally coupled effect command/completion outbox/approval final state. |
| Metric | Local deterministic durable suite: `24 passed, 2 PostgreSQL skipped`; implementation CI run `32511685853` passed both real PostgreSQL tests and all four job groups. |
| Scope | One local SQLite-backed draft workflow only; LangGraph checkpoint and trajectory projection are outside the transaction. |
| Dataset | Deterministic approval, concurrency, crash-injection, migration, and privacy fixtures; no model or retrieval dataset. |
| Code path | `app/agent_runtime/durable_store.py`; `durable_orchestrator.py`; `side_effects.py`; `trajectory.py` |
| Test path | `tests/agent_runtime/test_durable_orchestrator.py`; `test_trajectory.py` |
| Evidence JSON | `docs/review/P1_INTEGRITY_EVIDENCE_MANIFEST.json` |
| Reproduction command | `python -m pytest tests/agent_runtime/test_durable_orchestrator.py -q`; full command matrix is in `docs/review/P1_INTEGRITY_FIX_REPORT.md`. |
| Code SHA | `730f58e2988f981780a76ca66a878c675d873f50` |
| Concurrency evidence | Two workflow objects and independent DB/checkpointer connections race through a `ThreadPoolExecutor`; one owner acquires and one gets `ALREADY_RESUMING`. A stale owner is rejected after lease recovery by version/token fencing. |
| Failure evidence | Five injection points cover rollback before commit and stable recovery after commit-before-response; final state has one draft, one completion envelope, and one terminal approval. |
| Allowed wording | "Implemented CAS/lease/fencing and idempotent completion for a restart-recoverable access-request draft approval workflow." |
| Forbidden wording | "General durable Agent runtime"; "distributed exactly-once"; "production HITL"; "multi-host HA". |
| Interview explanation | Database ownership prevents duplicate resume; a local outbox closes the three-fact transaction, while idempotent projection handles the separate trajectory store honestly. |
| Review report | `docs/review/P1_INTEGRITY_FIX_REPORT.md` |
| Evidence manifest | `docs/review/P1_INTEGRITY_EVIDENCE_MANIFEST.json` (bound after implementation commit) |

This P10 overlay is newer than the P9/base durable evidence below. The
underlying canonical vNext branch remains `codex/agent-runtime-vnext`. P10 does not
change any frozen retrieval, answer-quality, indexing, or security benchmark
number. Remote PostgreSQL evidence is limited to implementation Actions run
`32511685853`; it is not a production-database or HA claim.

This is the canonical claim-to-evidence index for the public portfolio. Read it
before reusing a project number in a README, interview answer, or resume. Metric
execution SHAs identify the code that produced an artifact; the current
documentation HEAD must be checked separately with `git rev-parse HEAD` and the
portfolio verifier.

Current public review overlay is branch
`codex/durable-agent-runtime-and-policy-v1` at exact implementation commit
`e848d8e6090267b28d351758fe8d3cb557dcd586`. Its GitHub Actions run
`32470591376` passed Windows, Ubuntu, PostgreSQL 17.6, and Linux-container
contracts. The underlying vNext baseline remains `RAG_VNEXT_CLOSED`; this
overlay adds runtime durability, policy, idempotency, and trace-continuity
mechanisms without changing frozen retrieval or answer-quality results.

That state means the vNext implementation, evidence, resume handoff, and
teaching handoff are closed for this branch and are usable within their stated
scopes. It does not mean production readiness. The historical multi-document
quality candidate remains rejected; the later Agent Runtime mechanisms do not
turn that negative quality result into an uplift. Blind answer correctness is
not established, the security claim is narrow, and merge remains a user
decision.

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

## Claim P7: replaceable Agent Runtime and guarded tools

| Field | Binding |
|---|---|
| Claim | The bounded default and a real LangGraph `StateGraph` alternative implement one `AgentOrchestrator` contract and share ToolGateway, ACL, Guard, evidence, citation, and terminal boundaries. |
| Metric | Both arms passed `5/5` fixed mechanism cases with behavioral parity and zero permission violations; bounded p95 `1.283 ms`, LangGraph p95 `6.838 ms` in this small local diagnostic. |
| Scope | Deterministic in-repo mechanism cases; not external answer quality, production latency, or a LangGraph uplift experiment. |
| Dataset | Five fixed cases covering answered, no-match, permission, unsafe request, and retrieved injection. |
| Code path | `app/agent_runtime/orchestrator.py`; `app/agent_runtime/tool_contract.py`; `app/agent_runtime/tool_gateway.py`; `app/agent_runtime/mcp_adapter.py` |
| Test path | `tests/agent_runtime/test_orchestrators.py`; `test_tool_contract.py`; `test_mcp_adapter.py`; `test_ab_evaluation.py` |
| Evidence JSON | `docs/agent_runtime/evidence/agent_runtime_ab_v1.json` |
| Reproduction command | `python -m scripts.eval_agent_runtime_ab` regenerates a diagnostic; public evidence contracts are covered by `python -m pytest tests/agent_runtime -q`. |
| Code SHA | Accepted A/B implementation `d20382d111cc6ee5a54a1daad92454ecf0c501f3`; final ACL/HITL closeout is bound by current verified branch HEAD. |
| Allowed wording | "Implemented a replaceable Agent Runtime in which bounded and LangGraph orchestrators share the same host-owned permission and publication path; bounded remains default." |
| Forbidden wording | "LangGraph improved answer quality"; "100% Agent accuracy"; "production latency"; "production MCP/OAuth deployment". |
| Interview explanation | Orchestration was separated from authority. The experiment showed compatibility and framework overhead, so LangGraph was retained for explicit state/HITL rather than promoted as a quality improvement. |

## Claim P8: verifiable trajectory, replay, HITL, and EvalOps artifact

| Field | Binding |
|---|---|
| Claim | Agent runs can produce an ordered SHA-256-linked semantic trajectory, deterministic no-network replay, retry-safe same-process HITL, and a versioned `enterprise.agent-run/1.0` artifact. |
| Metric | Published sample contains 13 ordered events and verifies with artifact hash `f9d32f1bff44a27bbde1bf92b47800d396c9700a8120c135abf9b842b8108233`. |
| Scope | Local portfolio mechanism and one public synthetic sample; not WORM audit certification, durable execution, or production recovery. |
| Dataset | One deterministic synthetic answered run; HITL behavior uses in-repo fixtures. |
| Code path | `app/agent_runtime/trajectory.py`; `app/agent_runtime/replay.py`; `app/agent_runtime/evalops_artifact.py`; HITL in `app/agent_runtime/orchestrator.py` |
| Test path | `tests/agent_runtime/test_trajectory.py`; `test_replay.py`; `test_evalops_artifact.py`; `test_human_review.py` |
| Evidence JSON | `docs/agent_runtime/evidence/agent_run_artifact_sample_v1.json`; schema at `docs/agent_runtime/schemas/agent_run_artifact_v1.schema.json` |
| Reproduction command | `python -m scripts.verify_agent_run_artifact docs/agent_runtime/evidence/agent_run_artifact_sample_v1.json` |
| Code SHA | Generator `9ff917bdf99b971a59754b731176e85d61f570e6`; sample commit `e6c41c56a0ffed59b895b482e60b7d1911ba0364`; retry-safe HITL `ab5c48735a69aec43e26abb240275f08004789e7`. |
| Allowed wording | "Implemented hash-chained Agent trajectories, deterministic replay, bounded HITL resume, and a versioned EvalOps artifact." |
| Forbidden wording | "WORM audit ledger"; "durable crash-safe resume"; "production audit certification"; "external EvalOps adoption". |
| Interview explanation | Replay reconstructs recorded facts after verifying the chain and does not rerun side effects. Pending HITL state is in memory, so process restart remains an explicit boundary. |

## Claim P9: durable approval runtime, policy hooks, and trace continuity

| Field | Binding |
|---|---|
| Claim | A bounded optional runtime persists LangGraph approval checkpoints, revalidates authority after restart, and executes one idempotent draft-only side effect through deterministic tool policy hooks. |
| Metric | Local Agent Runtime `81 passed, 1 skipped`; clean repository verifier `5/5`; GitHub Actions run `32470591376` passed Windows, Ubuntu, PostgreSQL 17.6, and Linux-container jobs. |
| Scope | Deterministic mechanism and failure-recovery evidence; one access-request draft operation; not answer-quality gain or production HA. |
| Code path | `app/agent_runtime/durable_orchestrator.py`; `tool_policy.py`; `side_effects.py`; `telemetry.py`; `harness_contract.py` |
| Test path | `tests/agent_runtime/test_durable_orchestrator.py`; `test_tool_policy.py`; `test_side_effects.py`; `test_telemetry.py`; `test_harness_contract.py` |
| Evidence | `docs/production_runtime/RESULTS.md`; `FAILURE_MATRIX.md`; `KNOWN_LIMITATIONS.md`; GitHub Actions run `32470591376` |
| Reproduction command | `python -m pytest tests/agent_runtime -q`; then run the clean portfolio verifier documented in the final review packet. |
| Code SHA | `e848d8e6090267b28d351758fe8d3cb557dcd586` |
| Allowed wording | "Implemented restart-tested LangGraph approval checkpoints, deterministic tool policy hooks, an idempotent draft transaction, and privacy-default W3C trace continuity; all remote CI jobs passed." |
| Forbidden wording | "Production-ready durable Agent"; "distributed exactly-once"; "production IAM"; "LangGraph improved answer quality"; "AgentDojo passed". |
| Interview explanation | Restart durability is useful only when authority is rechecked and side effects are retry-safe. The checkpoint resumes control flow; policy and ACL decide permission; the idempotency ledger prevents duplicate draft creation; trace links preserve observability across the interrupt boundary. |

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

- **Resume primary:** P1, P3, and architecture portions of P7/P8 without their
  small diagnostic numbers; narrowly qualified P4 for security-focused roles.
- **Interview supporting:** P2, P5, P6, and the measured details of P7/P8.
- **Negative experiment:** N1 and the equal-RRF result embedded in P1.
- **Forbidden as quality:** oracle probes, consumed-cohort tuning, mechanism-only
  tests, local full-suite counts, and any `NOT_RUN` field.
