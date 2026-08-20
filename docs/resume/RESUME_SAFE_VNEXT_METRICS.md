# Resume-safe vNext claims

This file is a claim-selection guide, not a second metric ledger. The sole
numeric authority is `docs/handoffs/RESUME_METRIC_LEDGER.md`; whenever a value
or denominator changes there, this guide and every resume draft must follow it.

## VERIFIED_POSITIVE

These are the only measured headline families currently suitable for a resume,
and only with the exact dataset and boundary recorded in the ledger:

1. WixQA ExpertWritten retrieval: Dense versus BM25 Recall@5 and nDCG@5.
   These are retrieval-ranking metrics, never answer accuracy.
2. EnterpriseRAG-Bench lexical indexing: one-host record count, source types,
   build time, artifact size, and peak RSS.
3. Retrieved-content Guard: one pinned 12-attack garak subset with two benign
   controls. This is a narrow observed OFF/ON result, not universal safety.

The vNext runtime is also resume-safe as an **implemented architecture claim**:
one `AgentOrchestrator` contract, bounded default, real LangGraph alternative,
shared `ToolGateway`, ACL, Guard, Evidence Ledger, and citation gate. It does
not carry an external quality-uplift number.

## INTERVIEW_ONLY

- The bounded and LangGraph arms both passed five deterministic mechanism
  cases. Use this to explain migration compatibility and framework overhead,
  not Agent accuracy or production performance.
- The public `enterprise.agent-run/1.0` sample verifies an ordered hash-linked
  trajectory and deterministic no-network replay. One sample does not establish
  production audit certification or external EvalOps adoption.
- Clean-root replay, process-exit recovery, reused-ID sensitivity, and lexical
  benchmark recall are supporting engineering evidence. Their exact values and
  limitations live only in the canonical ledger.
- MCP is an official-SDK local/in-process adapter. Its tools still execute
  through server-held context, `ToolGateway`, identity, ACL, budget, deadline,
  and retrieved-content admission.
- HITL supports retry-safe, single-process pause/resume with tenant and reviewer
  checks. Pending review state is not durable across process restart.

## HISTORICAL_NEGATIVE

- Equal RRF underperformed Dense on the frozen WixQA comparison and was rejected.
- The 20-case multi-document development candidate produced no complete-case
  fixes, reduced precision, and added latency, so it was not integrated.
- These records remain valid decision evidence. Later runtime mechanisms do not
  convert either experiment into a quality improvement.

## FORBIDDEN_CLAIM

- Calling Recall@5 or nDCG@5 answer accuracy.
- Claiming LangGraph improved answer quality or is faster.
- Treating five mechanism cases as production performance or 100% Agent accuracy.
- Claiming production network MCP, OAuth, durable execution, or crash-safe HITL.
- Claiming a WORM ledger, production audit certification, universal injection
  defense, SOTA, production readiness, or third-party reproduction.
- Promoting a synthetic, oracle, consumed-development, or changing test-pass
  count as a headline product-quality result.

For exact values, evidence paths, SHAs, and safe/unsafe wording, read
`docs/handoffs/RESUME_METRIC_LEDGER.md` before drafting.
