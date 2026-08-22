# Enterprise Agentic RAG Copilot

[![CI](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/workflows/ci.yml?query=branch%3Amain)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB)](https://www.python.org/)
[![Portfolio status](https://img.shields.io/badge/status-portfolio--ready-2F7D4A)](PROJECT_STATUS.md)

> Reviewing this feature branch? Start with the
> [final public review packet](docs/review/FINAL_REVIEW_PACKET.md). It binds the
> exact commit, CI run, evidence files, safe claims, and known limitations.

Current closeout status: `IMPLEMENTATION_COMPLETE`, `EXACT_SHA_CI_REQUIRED`,
`NOT_MERGED`, `NOT_RELEASED`, `PORTFOLIO_READY`,
`PRODUCTION_NOT_VERIFIED`; `DURABILITY_SCOPE = ACCESS_REQUEST_DRAFT_ONLY`.

## What it does

This is a controlled enterprise knowledge Agent / Agentic RAG Runtime. Teams
ingest policies, Wiki pages, tickets, email, and meeting notes; an authenticated
user asks a question; the Agent retrieves only evidence visible to that user
and returns a cited answer, a bounded partial answer, or a safe refusal. Each
run can also emit a verifiable trajectory for replay and evaluation.

## Why it is different

- Authority stays in server-owned Python code: identity, ACL, budgets,
  retrieved-content admission, evidence, citations, and terminal policy.
- The proven bounded controller remains the default; a real LangGraph
  `StateGraph` is available behind the same `AgentOrchestrator` contract.
- Official MCP SDK tools still pass through the shared `ToolGateway`; MCP does
  not bypass permissions or the retrieved-content Guard.
- Append-only hash-chained trajectories support deterministic replay and a
  versioned `enterprise.agent-run/1.0` EvalOps artifact.
- An optional `DurableAccessRequestWorkflow` adds deterministic
  `DENY > ASK > ALLOW` policy hooks, database CAS/lease/fencing, file-backed
  LangGraph checkpoints, an atomic draft/completion/approval transaction, and
  typed privacy-default OpenTelemetry metadata. It covers only one
  access-request DRAFT workflow and does not replace the bounded default.

## Verified results

| Result | Verified observation | Boundary |
|---|---:|---|
| WixQA retrieval | On 200 fixed ExpertWritten questions, BGE-M3 Dense improved Recall@5 `42.75% -> 66.42%` and nDCG@5 `32.15% -> 52.16%` | Public-label retrieval, not answer accuracy. [Evidence](docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json) |
| EnterpriseRAG-Bench indexing | Built and atomically activated a `1.37 GiB` SQLite FTS5 index over `511,962` public records in `231.35 s`, at about `1.83 GiB` peak RSS | Single-host lexical baseline, not production capacity. [Evidence](docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json) |
| Clean retrieval replay | Rebuilt 11,975 embeddings and reproduced `63/63` frozen quality comparisons at tolerance `0.0` | Local replay of consumed public labels. [Evidence](docs/reproduction/evidence/wixqa_clean_reproduction_public_v1.json) |

This repository is an engineering portfolio, not a framework showcase. MCP is
an in-process protocol adapter rather than a network deployment; LangGraph is
an alternative orchestrator rather than a claimed quality improvement.

## What Is Finished

| Area | Implemented outcome |
|---|---|
| Bounded Agentic RAG | Rule-first query analysis, required-aspect decomposition, typed `search/find/open`, Evidence Ledger, explicit budgets, observable traces, and answer/partial/refuse/stop terminal states |
| Replaceable Agent Runtime | Common `AgentOrchestrator` contract with the existing bounded adapter and a real LangGraph `StateGraph`, both using the same guarded tool and publication path |
| MCP tool access | Official MCP SDK adapter for `search/find/open`; opaque server-issued context handles preserve identity, ACL, budget, expiry, and Guard enforcement |
| Replay and HITL | Append-only SHA-256-chained semantic trajectory, deterministic no-network replay, and a tenant/role-bound one-time human review resume path |
| Durable draft approval | Idempotent Start generations, recoverable non-authorizing client handles, SQLite CAS/lease/version fencing for Start and Resume, restart recovery, reviewer/tool-hash revalidation, one atomic draft/completion/approval transaction, PostgreSQL checkpointer CI contract, and W3C trace propagation |
| EvalOps integration | Versioned `enterprise.agent-run/1.0` JSON schema, serializer, verifier, public sample artifact, and reproducible CLI tooling |
| Enterprise retrieval | BM25, BGE-M3 Dense, RRF ablation, metadata and temporal authority, parent context, ACL filtering before evidence reaches the model |
| Grounded answers | Structured claims, visible-source citations, deterministic numeric/date/negation checks, and removal of unsupported claims |
| Retrieved-content security | Mandatory injection Guard on search/find/open content, quarantine, clean-candidate recovery, and Guard OFF/ON evaluation |
| Knowledge lifecycle | Restricted file validation, Markdown/text/PDF/DOCX/EML parsing, revision catalog, tombstones, incremental invalidation, immutable snapshots, atomic activation, and rollback |
| Industrial evidence | Frozen protocols, exact artifact hashes, negative-result gates, crash injection, cross-platform CI, clean-root reproduction, and public evidence packages |

Engineering judgment is part of the result: equal-weight RRF was not promoted,
and a bounded multi-document candidate was rejected after producing **zero
complete-case fixes**, reducing citation precision by `5.83pp`, and increasing
p95 latency to `1.859x`. See the [negative-result record](docs/multidoc_candidate/02_RESULTS_AND_DECISION.md).

## Architecture

![Enterprise Agentic RAG request flow](docs/diagrams/agentic_rag_flow_cn.png)

The runtime loop is:

```text
verified identity
  -> BoundedControllerAdapter or LangGraphOrchestratorAdapter
  -> shared Tool Contract / ToolGateway
  -> direct or MCP-adapted search / find / open
  -> ACL filtering, budget, deadline, and retrieved-content admission
  -> observation updates the Evidence Ledger
  -> continue, HITL for bounded partial evidence, answer, refuse, or stop
  -> generate structured claims
  -> host verifies citations and removes unsupported claims
  -> append semantic trajectory -> replay / EvalOps artifact

optional sensitive action
  -> ToolPolicy ASK -> idempotent Start key -> Approval Generation
  -> fenced Checkpoint creation -> stable non-authorizing Handle
  -> DurableAccessRequestWorkflow JSON interrupt
  -> reviewer/tenant/tool-hash revalidation after restart
  -> idempotent access-request DRAFT (never an ACL grant)
```

The default V2 controller searches once per required aspect. Completeness
queries may open an already visible document. `find` is implemented as a typed,
authorized tool boundary, but the default controller does not currently select
it. Automatic query rewrite and retrieval retry are also disabled by default.
This is a bounded enterprise Agent, not an open-ended autonomous Agent.

The paired runtime diagnostic used the same five deterministic mechanism cases,
tools, ACL, budget, retrieval fixtures, and answer builder. Both adapters passed
`5/5` with identical terminal behavior and zero permission violations. It did
**not** show a quality improvement: LangGraph p95 was `6.838 ms` versus bounded
`1.283 ms` in this tiny local test, so LangGraph remains an alternative for
explicit state and HITL rather than the default. [Protocol and limits](docs/agent_runtime/08_AB_EVALUATION.md).

Key code paths:

- [Query analysis](app/agent/query_analysis.py)
- [Agent controller](app/agent/controller_v2.py) and [execution loop](app/agent/runner_v2.py)
- [Agent Runtime and adapters](app/agent_runtime/orchestrator.py)
- [Tool contract and authority](app/agent_runtime/tool_contract.py) / [gateway](app/agent_runtime/tool_gateway.py)
- [Tool policy](app/agent_runtime/tool_policy.py), [durable runtime](app/agent_runtime/durable_orchestrator.py), [idempotent side effects](app/agent_runtime/side_effects.py), and [OTel](app/agent_runtime/telemetry.py)
- [External harness contract](app/agent_runtime/harness_contract.py) and [CLI](scripts/run_agent_harness.py)
- [MCP adapter](app/agent_runtime/mcp_adapter.py)
- [Trajectory](app/agent_runtime/trajectory.py), [replay](app/agent_runtime/replay.py), and [EvalOps artifact](app/agent_runtime/evalops_artifact.py)
- [Typed tools](app/agent/tools_v2.py) and [Evidence Ledger](app/agent/evidence_ledger.py)
- [ACL-aware retrieval](app/retrieval/pipeline.py)
- [Retrieved-content Guard](app/security/retrieved_content.py)
- [Claim generation](app/agent/generation_v2.py) and [citation verification](app/agent/citation_verifier.py)
- [Versioned lifecycle](app/lifecycle) and [incremental indexing](app/indexing)

## Demo

The Streamlit workbench exposes three views: the answer, the Agent trace, and
the frozen evaluation evidence.

### Ask

![Ask page with verified sources](docs/assets/ask.png)

### Trace

![Agent actions, evidence coverage, and budget](docs/assets/trace.png)

### Evaluation

![Retrieval, runtime, and security evidence](docs/assets/evaluation.png)

## Quick Start

The public demo runs locally with Python 3.11 and Ollama. Complete model and
index setup is documented in the [demo runbook](docs/demo_runbook.md).

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity init --force
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py --server.address 127.0.0.1 --server.port 8501
```

For a faster offline portfolio check that does not require Ollama or private
benchmark files:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_portfolio_release
```

## Repository Guide

```text
app/agent/                 bounded decision loop, tools, evidence, citations
app/agent_runtime/         orchestrators, guarded tool contract, MCP, trajectory, replay, HITL, EvalOps
app/retrieval/             hybrid retrieval, navigation, ranking, ACL filtering
app/security/              identity and retrieved-content security boundaries
app/ingestion/             validated parsing and revision preparation
app/indexing/              immutable and incremental index lifecycle
app/evaluation/            metrics, protocols, attribution, public evidence
streamlit_app/             Ask, Trace, and Evaluation UI
tests/                     deterministic, security, failure, and evidence gates
docs/handoffs/             recruiter, interview, teaching, and resume entry points
docs/enterprise_eval/      external retrieval protocols and results
docs/resume_metrics/       resume-safe metrics and forbidden claims
docs/agent_runtime/        vNext decisions, security review, architecture, schema, and evidence
docs/production_runtime/   policy, durable checkpoint, idempotency, OTel, failure evidence, and claim limits
```

The versioned deterministic harness reads one JSON request from stdin:

```powershell
'{"case_id":"readme-smoke","question":"What is the remote policy?"}' | .\.venv\Scripts\python.exe -m scripts.run_agent_harness --state-root .private\harness\readme
```

Start technical review with the [project evidence map](docs/handoffs/PROJECT_EVIDENCE_MAP.md).
For interview preparation, use the [teaching handoff](docs/handoffs/TEACHING_CODEX_HANDOFF.md)
and [interview story bank](docs/handoffs/INTERVIEW_STORY_BANK.md). The concise
Chinese resume entry is in [FINAL_RESUME_ENTRY_CN.md](docs/handoffs/resume_package/FINAL_RESUME_ENTRY_CN.md).

## Scope and Limitations

Completed engineering mechanisms and measured results are shown above. This
project does **not** claim:

- production deployment, production traffic, SLOs, or universal security;
- blind end-to-end answer accuracy or semantic entailment certification;
- that the current Agent route improves external retrieval quality;
- independent third-party reproduction;
- durable production HITL for arbitrary actions, production network MCP/OAuth,
  multi-Agent execution, GraphRAG, Redis, Kafka, or distributed multi-writer
  indexing; the durable candidate currently covers one local draft-only action;
- that LangGraph improved answer quality, or that the five-case diagnostic is a
  production latency or accuracy benchmark.

The public synthetic corpus exists to exercise ACL, versions, conflicts,
multi-document questions, and safe refusal without exposing private enterprise
data. External WixQA, EnterpriseRAG-Bench, and garak evidence is reported
separately with dataset, denominator, execution revision, and limitation.

Current state: `RAG_VNEXT_CLOSED` on the vNext branch; merge remains a user
decision.

## Documentation

- [Recruiter summary](docs/handoffs/RECRUITER_SUMMARY.md)
- [Claim-to-evidence map](docs/handoffs/PROJECT_EVIDENCE_MAP.md)
- [Resume metric ledger](docs/handoffs/RESUME_METRIC_LEDGER.md)
- [Evaluation methodology](docs/evaluation.md)
- [Architecture and trust boundaries](docs/architecture.md)
- [Known limitations](docs/known_limitations.md)
- [Full project evolution](docs/history/00_PROJECT_EVOLUTION.md)
- [Portfolio archive report](docs/handoffs/PORTFOLIO_ARCHIVE_REPORT.md)
- [Agent Runtime final architecture](docs/agent_runtime/10_FINAL_ARCHITECTURE.md)
- [Agent Runtime security review](docs/agent_runtime/09_SECURITY_REVIEW.md)
- [Agent Runtime learning tutorial](docs/learning/AGENT_RUNTIME_TUTORIAL.md)
- [vNext resume-safe evidence](docs/resume/RESUME_SAFE_VNEXT_METRICS.md)
- [Production runtime candidate architecture](docs/production_runtime/ARCHITECTURE.md)
- [Production runtime results and limitations](docs/production_runtime/RESULTS.md) / [limitations](docs/production_runtime/KNOWN_LIMITATIONS.md)
