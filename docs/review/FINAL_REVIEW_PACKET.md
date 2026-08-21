# Final Public Review Packet

## Current P1 integrity review overlay

Review branch: `codex/durable-runtime-integrity-fix-v1`.

Implementation commit:
`730f58e2988f981780a76ca66a878c675d873f50`.

Implementation CI: GitHub Actions run `32511685853`, success across PostgreSQL,
Windows, Ubuntu, and Linux-container job groups.

Implementation ancestor:
`e848d8e6090267b28d351758fe8d3cb557dcd586`.

This overlay fixes concurrency and completion-integrity defects in the one
access-request DRAFT approval workflow. Review
[`P1_INTEGRITY_FIX_REPORT.md`](P1_INTEGRITY_FIX_REPORT.md) and the commit-bound
`P1_INTEGRITY_EVIDENCE_MANIFEST.json`
before reading the older durable baseline packet below. The implementation
uses database CAS/lease/version fencing and atomically commits the local draft
effect command, immutable completion outbox, and approval final state. It does
not make the whole Agent runtime durable and does not claim distributed
exactly-once execution.

The prior `e848d8e` / Actions `32470591376` record below remains historical base
evidence. It is not proof that the current integrity-fix branch passes CI. The
new branch's exact implementation commit and Actions run are bound in the P1
manifest.

This is the single entry point for a human reviewer or a web-enabled GPT. It is
an index of public evidence, not a new experiment and not a production-readiness
certificate.

## Review coordinates

| Field | Exact value |
|---|---|
| Repository | `godofxuan/Attempt-of-enterprise-rag-copilot` |
| Review branch | `codex/durable-agent-runtime-and-policy-v1` |
| Baseline | `909a9710932c6c4744c462db0e33ed0d222ecb1a` |
| Final implementation commit | `e848d8e6090267b28d351758fe8d3cb557dcd586` |
| Commit message | `feat: add durable agent runtime policy hooks and trace continuity` |
| GitHub Actions run | `32470591376`, success, 12m 20s |
| Pull request state | not created or merged; branch review only |

The branch may contain a documentation-only evidence-packaging commit after the
final implementation commit. Review code at the exact implementation SHA and
verify that the current branch contains it as an ancestor; do not require the
moving branch HEAD to equal the implementation SHA.

Public URLs:

- Branch: <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/codex/durable-agent-runtime-and-policy-v1>
- Exact commit: <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e848d8e6090267b28d351758fe8d3cb557dcd586>
- CI: <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32470591376>
- Commit patch: <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e848d8e6090267b28d351758fe8d3cb557dcd586.patch>

## Final delivery summary

The optional runtime now provides:

1. Deterministic `DENY > ASK > ALLOW` tool policy with typed, in-process,
   fail-closed lifecycle hooks.
2. Official LangGraph SQLite/PostgreSQL checkpointers, stable thread identity,
   durable interrupt/resume, and resume-time tenant, ACL, reviewer, role,
   policy, argument-hash, expiry, deadline, and authentication revalidation.
3. One deliberately narrow side effect: transactionally creating an
   access-request `DRAFT`. It cannot grant ACL access and duplicate retries
   return the same persisted result.
4. W3C Trace Context and privacy-default OpenTelemetry spans across harness,
   Agent, policy, tool, interrupt/resume, citation, and EvalOps boundaries.
5. A versioned local evaluation harness contract with deterministic fixtures,
   JSON Schemas, CLI, and optional local-model mode.

This work does not change the default bounded controller and does not claim a
retrieval or answer-quality improvement.

## Evidence reading order

1. [`README.md`](../../README.md): project purpose, strongest frozen metrics,
   architecture, and code map.
2. [`PROJECT_STATUS.md`](../../PROJECT_STATUS.md): current branch and claim
   boundaries.
3. [`PROJECT_EVIDENCE_MAP.md`](../handoffs/PROJECT_EVIDENCE_MAP.md): canonical
   claim-to-code, test, artifact, and wording bindings, especially P9.
4. [`ARCHITECTURE.md`](../production_runtime/ARCHITECTURE.md): runtime and
   authority boundaries.
5. [`TOOL_POLICY.md`](../production_runtime/TOOL_POLICY.md) and
   [`DURABLE_LANGGRAPH.md`](../production_runtime/DURABLE_LANGGRAPH.md): policy
   and recovery design.
6. [`IDEMPOTENT_SIDE_EFFECTS.md`](../production_runtime/IDEMPOTENT_SIDE_EFFECTS.md)
   and [`FAILURE_MATRIX.md`](../production_runtime/FAILURE_MATRIX.md): retry and
   failure semantics.
7. [`OTEL_GENAI.md`](../production_runtime/OTEL_GENAI.md): trace and privacy
   design.
8. [`RESULTS.md`](../production_runtime/RESULTS.md): commands, failures, fixes,
   local results, and remote CI closure.
9. [`RESUME_SAFE_CLAIMS.md`](../production_runtime/RESUME_SAFE_CLAIMS.md) and
   [`KNOWN_LIMITATIONS.md`](../production_runtime/KNOWN_LIMITATIONS.md): allowed
   and forbidden wording.
10. [`EXTERNAL_HARNESS_PATTERN_DECISIONS.md`](../agent_runtime/EXTERNAL_HARNESS_PATTERN_DECISIONS.md)
    and [`THIRD_PARTY_PROVENANCE.md`](../handoffs/THIRD_PARTY_PROVENANCE.md):
    external patterns, licenses, adoption, adaptation, rejection, and deferral.

## Code and test evidence

| Concern | Implementation | Primary tests |
|---|---|---|
| Tool policy and hooks | `app/agent_runtime/tool_policy.py`, `tool_gateway.py` | `test_tool_policy.py` |
| Durable approval | `durable_orchestrator.py` | `test_durable_orchestrator.py` |
| Idempotent draft | `side_effects.py` | `test_side_effects.py` |
| Trace continuity | `telemetry.py`, `evalops_artifact.py` | `test_telemetry.py`, `test_evalops_artifact.py` |
| Harness contract | `harness_contract.py`, `scripts/run_agent_harness.py` | `test_harness_contract.py` |
| Public schemas/docs | `docs/production_runtime/schemas` | `test_production_runtime_docs.py` |

## Verification record

| Verification | Observed result |
|---|---|
| `python -m pip check` | passed |
| `python -m compileall -q app scripts streamlit_app tests` | passed |
| `python -m pytest tests/agent_runtime -q` | `81 passed, 1 skipped` locally; PostgreSQL skipped only because no local DSN |
| Full local suite | `3322 passed, 30 skipped`; three existing SWIG warnings |
| Public repository audit | `1689 candidates / 0 findings` |
| Clean portfolio verifier | `VERIFIED`, 5/5 gates |
| GitHub Actions | Windows, Ubuntu, PostgreSQL 17.6, and Linux-container jobs passed |

The CI run is the authoritative evidence for the real PostgreSQL checkpointer
test and container contract. Local Docker was unavailable and that negative
environment result remains recorded rather than being presented as a pass.

## Safe claims

- Implemented restart-tested LangGraph approval checkpoints with authority
  revalidation.
- Implemented deterministic tool policy hooks and append-only, privacy-limited
  policy audit records.
- Implemented an idempotent SQLite transaction for one draft-only side effect.
- Implemented W3C trace propagation and interrupt/resume Span Links with content
  capture disabled.
- Passed the exact-commit remote CI matrix, including PostgreSQL and container
  contracts.

## Claims the evidence does not support

- Production readiness, high availability, production SLOs, or external audit.
- Distributed exactly-once behavior or atomicity across checkpoints, policy,
  effects, and telemetry stores.
- Production IAM, approval inbox, notification delivery, or arbitrary actions.
- LangGraph answer-quality improvement or any new model-quality metric.
- AgentDojo coverage, universal prompt-injection safety, or zero-risk security.

## Instructions for a reviewer

Do not judge from the README alone. Pin the exact implementation commit, inspect
implementation and tests, confirm the CI run belongs to that SHA, and trace every proposed
resume number to the canonical evidence map. Report inaccessible URLs instead
of inferring missing evidence. Treat mechanism tests, external dataset metrics,
and production claims as three different evidence classes.

The ready-to-paste Chinese review prompt is
[`GPT_GITHUB_REVIEW_PROMPT_CN.md`](GPT_GITHUB_REVIEW_PROMPT_CN.md).
