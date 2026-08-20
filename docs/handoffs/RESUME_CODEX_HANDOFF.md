# Resume Codex Handoff

Any resume-drafting task must read this file, the target job description, and
`docs/handoffs/resume_package/FINAL_RESUME_ENTRY_CN.md`. Architecture wording
comes from the evidence map; every number comes from the metric ledger.

## Canonical status

Current branch: `codex/agent-runtime-vnext`.

Current state: `RAG_VNEXT_CLOSED`.

The branch is suitable for portfolio, resume, teaching, and interview use within
the published scopes. It is not production-ready. Merge, release, and deployment
remain user decisions. The 2026-08-11
`PORTFOLIO_ARCHIVED_READY_FOR_RESUME_AND_INTERVIEW` state is historical and was
superseded by the vNext runtime closeout; its rejected quality experiments remain
valid negative evidence.

## Authority order

1. `docs/handoffs/RESUME_METRIC_LEDGER.md`: sole numeric authority.
2. `docs/handoffs/PROJECT_EVIDENCE_MAP.md`: claim-to-code/test/artifact binding.
3. `docs/resume/RESUME_SAFE_VNEXT_METRICS.md`: claim-selection boundary.
4. `docs/handoffs/resume_package/FINAL_RESUME_ENTRY_CN.md`: current Chinese draft.

## Drafting algorithm

1. Select one role angle; use no more than three project bullets.
2. Keep runtime architecture, measured retrieval, and platform/reliability as
   separate bullets instead of listing every technology in one sentence.
3. Bind every number to the metric ledger and preserve dataset, denominator,
   split, and metric name.
4. Bind every mechanism to code, tests, evidence, and a limitation.
5. Prefer `action -> problem -> scope -> verified result` over adjectives.
6. Omit any requested number whose evidence mapping is absent.

## Allowed vNext wording

- One `AgentOrchestrator` with bounded default and a real LangGraph alternative.
- Shared `ToolGateway`, identity/ACL, Guard, Evidence Ledger, and citation gate.
- Official MCP SDK local/in-process adapter using opaque server-issued context.
- SHA-256-linked trajectory, deterministic replay, bounded same-process HITL,
  and `enterprise.agent-run/1.0` artifact.

LangGraph and MCP are now implemented and evidence-backed architecture terms.
They must still carry the limits above and must not be presented as quality
uplift, network deployment, OAuth, or production readiness.

## Mandatory exclusions

- Recall@5/nDCG@5 as answer accuracy.
- Agent or LangGraph quality improvement.
- Five-case parity as product quality or production latency.
- Durable crash-safe HITL, WORM audit storage, production MCP/OAuth.
- Universal injection defense, 100% security, SOTA, production SLO/HA.
- Blind holdout or third-party validation where only fixed public labels or
  same-owner clean replay exist.
- Synthetic, oracle, consumed-development, or varying test counts as headline
  quality.

Keep this project focused on controlled enterprise RAG, runtime boundaries,
evaluation, security, and reproducibility. Do not import unrelated platform
claims from a separate EvalOps project.
