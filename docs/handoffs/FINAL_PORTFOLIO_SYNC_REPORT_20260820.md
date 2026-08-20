# Final portfolio sync report - 2026-08-20

## Identity

- Repository: `godofxuan/Attempt-of-enterprise-rag-copilot`
- Branch: `codex/agent-runtime-vnext`
- PRE_SYNC_HEAD: `ef9d0a919d3c002b7d868035c90b9f9624202513`
- Canonical current state: `RAG_VNEXT_CLOSED`
- Scope: documentation, claim, teaching, provenance, and contract-test sync only
- Production/release authority: none; merge remains the repository owner's choice

## Audit scope

The review compared the runtime implementation and tests with README,
`PROJECT_STATUS.md`, the evidence map, resume surfaces, recruiter summary,
teaching curriculum, interview stories, CI/verifier commands, frozen evidence,
dependency pins, source headers, Git history, and public project references. No
metric JSON, frozen experiment output, model, dataset, retrieval algorithm, or
serving path was changed.

## Cross-surface conflicts and repairs

| Conflict | Evidence-backed resolution |
|---|---|
| `PROJECT_STATUS.md` opened with the 2026-08-11 archive enum and a rejected Agent candidate | Added a 2026-08-20 vNext block first; retained all old sections under `Historical stages`; clarified that the rejected item was the consumed-cohort multi-document quality candidate |
| Evidence and resume handoffs treated the archive state as current | Set current state to `RAG_VNEXT_CLOSED`; retained the archive enum only as dated history |
| Numeric claims were duplicated across ledgers with different class names | Made `docs/handoffs/RESUME_METRIC_LEDGER.md` the single numeric authority and standardized `VERIFIED_POSITIVE`, `INTERVIEW_ONLY`, `HISTORICAL_NEGATIVE`, `FORBIDDEN_CLAIM` |
| Current Chinese resume entry omitted the implemented vNext runtime | Added separate role-specific bullets for Agent Runtime, MCP/tool security, trajectory/replay/EvalOps, retrieval, indexing, and Guard, each with code/test/evidence bindings |
| Teaching stopped at the older controller/evaluation stage | Expanded the canonical curriculum from 8 to 13 modules and added source traces, failure modes, interview questions, learner targets, and code/test exercises |
| Story bank had no runtime migration, MCP, replay, HITL, or EvalOps narratives | Preserved stories 1-8 and added stories 9-13 without relabeling mechanism evidence as quality |
| No public harness/AI-assistance provenance record existed | Added a classified source/license matrix, recorded direct API use, concept-only references, unknowns, and the missing root-license boundary |
| No automated cross-surface drift gate existed | Extended the existing portfolio handoff test to verify current state, canonical paths, metric authority, safe wording, provenance, and historical markers |

The detailed source-by-source matrix is
`docs/handoffs/VNEXT_CROSS_SURFACE_AUDIT_20260820.md`.

## Files changed

- `PROJECT_STATUS.md`
- `docs/handoffs/VNEXT_CROSS_SURFACE_AUDIT_20260820.md`
- `docs/handoffs/PROJECT_EVIDENCE_MAP.md`
- `docs/handoffs/RESUME_METRIC_LEDGER.md`
- `docs/resume/RESUME_SAFE_VNEXT_METRICS.md`
- `docs/handoffs/resume_package/FINAL_RESUME_ENTRY_CN.md`
- `docs/handoffs/resume_package/PROJECT_SUMMARY.md`
- `docs/handoffs/resume_package/SAFE_METRICS.md`
- `docs/handoffs/resume_package/BULLET_CANDIDATES.md`
- `docs/handoffs/resume_package/EVIDENCE_MAP.md`
- `docs/handoffs/resume_package/ROLE_POSITIONING.md`
- `docs/handoffs/resume_package/INTERVIEW_STORIES.md`
- `docs/handoffs/resume_package/FORBIDDEN_CLAIMS.md`
- `docs/handoffs/RESUME_CODEX_HANDOFF.md`
- `docs/handoffs/RECRUITER_SUMMARY.md`
- `docs/handoffs/TEACHING_CODEX_HANDOFF.md`
- `docs/handoffs/INTERVIEW_STORY_BANK.md`
- `docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md`
- `docs/learning/RAG_INTERVIEW_UPDATE.md`
- `docs/final_closeout/resume/RAG_RESUME_FACT_SHEET.md`
- `docs/handoffs/THIRD_PARTY_PROVENANCE.md`
- `tests/test_portfolio_handoff_evidence.py`
- `docs/handoffs/FINAL_PORTFOLIO_SYNC_REPORT_20260820.md`

## Canonical current state

- The bounded controller is the default implementation of `AgentOrchestrator`.
- The LangGraph `StateGraph` adapter is a real alternative behind the same host-
  owned authority and publication path. It has no demonstrated quality uplift.
- MCP uses the official Python SDK locally/in-process. Opaque server-issued
  context resolves to the same ToolGateway and cannot grant identity, ACL,
  budget, deadline, or Guard authority.
- Trajectories are canonical, ordered, append-only at the application boundary,
  SHA-256 linked, and deterministically replayable without rerunning tools,
  models, or network calls.
- HITL resume is reviewer/tenant checked, single-use, and retry-safe in one
  process. It is not crash-durable.
- `enterprise.agent-run/1.0` is a versioned local Agent-to-EvalOps artifact, not
  evidence of an externally deployed EvalOps platform.

## Safe resume claims

Exact values and denominators must come from the metric ledger.

1. WixQA ExpertWritten Dense-versus-BM25 Recall@5 and nDCG@5 improvement on 200
   fixed public-label retrieval questions, explicitly labeled retrieval-only.
2. A one-host SQLite FTS5 index build over 511,962 public synthetic enterprise
   records with recorded artifact size, build time, and peak RSS.
3. A narrow Guard OFF/ON result on a pinned 12-attack garak subset, including its
   two-benign-control and non-generalization limitations.
4. A replaceable Agent Runtime with bounded default, LangGraph alternative, and
   shared ToolGateway/ACL/Guard/evidence/citation boundaries, without a quality
   uplift number.
5. Local/in-process MCP `search/find/open`, hash-linked trajectories,
   deterministic replay, bounded same-process HITL, and the versioned Agent Run
   Artifact as implementation claims.

## Forbidden claims

- Recall@5/nDCG@5 as answer accuracy or overall RAG accuracy
- LangGraph or Agent answer-quality improvement
- five-case parity as production latency, reliability, or Agent accuracy
- production network MCP, OAuth, durable execution, or crash-safe HITL
- WORM/external audit certification or external EvalOps adoption
- universal prompt-injection defense, 100% security, SOTA, production readiness
- production traffic/QPS/SLO/HA or real enterprise deployment
- blind holdout or independent third-party validation where neither occurred
- rewriting equal-RRF or multi-document rejection as a positive result

## Teaching reading order

1. `docs/handoffs/PROJECT_EVIDENCE_MAP.md`
2. `docs/learning/RAG_PROJECT_TEACHING_HANDOFF.md`
3. `docs/learning/AGENT_RUNTIME_TUTORIAL.md`
4. `docs/agent_runtime/10_FINAL_ARCHITECTURE.md`
5. `docs/agent_runtime/09_SECURITY_REVIEW.md`
6. `docs/agent_runtime/08_AB_EVALUATION.md`
7. `docs/resume/RESUME_SAFE_VNEXT_METRICS.md`
8. `docs/handoffs/INTERVIEW_STORY_BANK.md`
9. Historical attribution/candidate/final-evidence learning guides listed in
   `docs/handoffs/TEACHING_CODEX_HANDOFF.md`

## Provenance and license result

- VERIFIED: LangGraph and MCP SDK are direct MIT-licensed package/API use.
- VERIFIED: OpenAI Agents SDK, RAGFlow, Haystack, Docling, and MinerU are
  concept-only or not-implemented references in the reviewed repository paths.
- VERIFIED: Claude Code's public repository is not treated as open source; no
  core harness replication or copied source was identified.
- PARTIAL: Codex/Claude-related assistance is recorded, but exact line-level
  human/AI contribution cannot be proven from Git metadata.
- UNKNOWN/OPEN: transitive dependency/model/data terms require release-time SBOM
  review; the generated SBOM may contain `NOASSERTION` fields.
- UNKNOWN/OPEN: the repository has no root `LICENSE`; public visibility does not
  establish reuse permission. No license was chosen on the owner's behalf.
- New attribution: `docs/handoffs/THIRD_PARTY_PROVENANCE.md`; no NOTICE was added
  because no copied/adapted upstream source was confirmed.

## Local validation

Environment: Windows PowerShell, repository `.venv`, Python 3.11.9. Model/network
evaluation was not invoked.

| Command | Exit | Result |
|---|---:|---|
| `git diff --check` | 0 | PASS; no whitespace errors before validation |
| `python -m compileall -q app scripts streamlit_app tests` | 0 | PASS |
| `python -m pytest tests/test_portfolio_handoff_evidence.py tests/test_public_repository.py tests/test_portfolio_release_verifier.py tests/test_final_closeout_evidence.py tests/test_final_evidence_closure.py tests/test_resume_metrics_closeout.py -q -p no:cacheprovider` | 0 | PASS; 125 passed, 3 dependency warnings |
| `python -m pytest tests/agent_runtime -q -p no:cacheprovider` | 0 | PASS; 51 passed, 3 dependency warnings |
| `python -m scripts.audit_public_repo` | 0 | PASS; 1,663 public candidates, 0 findings |
| `python -m scripts.verify_portfolio_release --allow-dirty --expected-branch codex/agent-runtime-vnext --expected-sha ef9d0a919d3c002b7d868035c90b9f9624202513` | 0 | DEVELOPMENT_VERIFIED; 5/5 gates passed; dirty state explicitly non-release |
| `python -u -X faulthandler -m pytest -q -p no:cacheprovider` | 0 | PASS; 3,292 passed, 29 skipped, 3 dependency warnings in 211.13 s |
| `python -m scripts.verify_portfolio_release --expected-branch codex/agent-runtime-vnext --expected-sha <POST_SYNC_HEAD>` | 0 | VERIFIED; clean worktree, exact branch/SHA identity, 5/5 subgates passed; rerun after report-only amend before push |

The three warnings are SWIG/FAISS import deprecation warnings. The 29 skips are
environment/data/model-gated tests reported by pytest; they are not counted as
passes.

## Unrun validation

- New model, Dense, WixQA, EnterpriseRAG-Bench, FinQA, garak, or other large
  experiments: intentionally NOT RUN because this closeout prohibits metric
  recomputation and downloads.
- Human semantic review and independent reviewer sign-off: NOT RUN; an automated
  agent cannot sign human judgement fields.
- Production network MCP/OAuth, restart-durable HITL, distributed state, live
  traffic, SLO/HA, power-loss durability, and external audit anchoring: NOT RUN
  because those implementations/environments do not exist here.
- GitHub Actions for the final commit: pending push; it cannot be reported as a
  pass before the commit exists remotely.

## Remaining production boundaries

The project still lacks a real enterprise IdP/SSO deployment, durable distributed
workflow state, network MCP threat testing and operations, multi-worker
coordination, WORM/external trajectory anchoring, live tenant traffic, SLOs,
capacity/load testing, backup/restore drills, power-loss storage tests, broad
security red-team coverage, blind end-to-end answer validation, and independent
third-party reproduction. The missing root repository license is also an open
public-reuse boundary.

## Closeout status

- `PORTFOLIO_DOCS_SYNCED`: PASS
- `RESUME_HANDOFF_SYNCED`: PASS
- `TEACHING_HANDOFF_SYNCED`: PASS
- `PROVENANCE_REVIEWED`: PASS WITH RECORDED UNKNOWN/OPEN ITEMS
- final clean-worktree verifier: PASS (`VERIFIED`, 5/5 subgates)

Portfolio-ready means that implementation, tests, evidence, decisions, and
limitations are inspectable. Portfolio-ready does not mean production-ready.
