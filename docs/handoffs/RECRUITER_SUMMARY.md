# Recruiter Summary

Current state: `RAG_VNEXT_CLOSED` on public `main`. Use these as
speaking prompts. Resolve every number through
`docs/handoffs/RESUME_METRIC_LEDGER.md`.

## 15 seconds

I built an enterprise RAG system with a replaceable but bounded Agent Runtime.
Identity, ACL, tools, retrieved-content admission, evidence, and final citations
remain controlled by the Python host, while frozen evaluations decide what can
be claimed or shipped.

## 30 seconds

The bounded controller remains the default and a real LangGraph StateGraph is an
alternative behind the same ToolGateway. I also added local MCP tool adaptation,
hash-linked trajectories, deterministic replay, and an EvalOps artifact. On a
fresh-company UDA confirmation, page fusion improved known-report Hit@5 from
80.21% to 88.02% and nDCG@5 from 70.95% to 77.60%.

## 90 seconds

Enterprise RAG can fail at retrieval, authorization, poisoned content admission,
evidence completeness, or claim publication. I separated those boundaries in
Python and made the orchestrator replaceable without moving authority into the
framework or prompt. The default bounded path and LangGraph alternative use the
same typed search/find/open tools and security gates; MCP is local/in-process and
also returns through that gateway. Runs can emit a SHA-256-linked trajectory and
versioned Agent artifact for deterministic no-network replay. Externally, a
192-question UDA confirmation produced 15 page-retrieval rescues and no observed
paired regressions at 1.058x p95; Dense also improved WixQA retrieval Recall@5
from 42.75% to 66.42%; a one-host FTS5 build
handled 511,962 records; and a narrow pinned Guard comparison reduced observed
ASR from 4/12 to 0/12. I also retained negative results: equal RRF and a
multi-document candidate were rejected. This is portfolio-ready engineering
evidence, not a production deployment or a claim that LangGraph improved quality.

## Current boundary

- Portfolio/resume/interview usable: yes, within frozen claim scopes.
- Replaceable runtime and local MCP adapter implemented: yes.
- LangGraph quality uplift established: no.
- Blind end-to-end answer correctness established: no.
- R5 finance scope: public-label known-report page localization only.
- Production network MCP, durable HITL, SLO/HA, or universal security: no.
- Merge and deployment authority: user decision.
