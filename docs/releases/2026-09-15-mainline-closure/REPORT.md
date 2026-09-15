# Mainline Release Closure - 2026-09-15

## Decision

The bounded Enterprise Agentic RAG candidate is eligible for mainline
integration after the clean-commit release gate and remote CI pass. This is an
engineering release decision, not a production-readiness or model-quality
promotion.

The release keeps the host-owned identity, ACL, retrieved-content admission,
tool budget, evidence, citation, and answer-publication boundaries. It adds the
bounded query-part, evidence-gap recovery, structured document navigation,
local identity renewal, cooperative cancellation, and Qwen3.5 local default
work completed on `codex/local-closeout-20260910`.

## Release Identity

| Field | Value |
|---|---|
| Pre-release committed HEAD | `152981aba3bc9a15a1035dbfa53dc57651b3c97f` |
| Candidate branch | `codex/local-closeout-20260910` |
| Scoped Python source count | `991` |
| Pre-commit scoped source fingerprint | `774b583f573897137847b070b87ef9cb9a6f01bf7f1972d24ce4288d60bce39e` |
| Target public branch | `main` |
| Target stable tag | `portfolio-v1.2.0-mainline-closure` |

The final commit SHA is the Git commit referenced by the stable tag and the
successful GitHub Actions run. It is intentionally not self-recorded inside
the commit.

The CI workflow runs on branch pushes and pull requests. Stable tags are
created only after the same mainline SHA passes the full matrix; tag pushes do
not rerun the branch-identity gate against a detached HEAD.

## Verification History

The first repository-wide run preserved four real failures:

```text
4140 passed, 4 failed, 36 skipped
```

The failures identified three release problems:

1. the WixQA diagnostic controller wrapper did not forward the new
   `prepare_advice()` method, so enabling observation could change the response;
2. the dependency contract had not been updated for the already installed and
   used `markdown-it-py==4.2.0` parser dependency;
3. two current evidence tests still pointed at historical artifacts whose
   implementation hashes no longer matched the changed source.

The wrapper now delegates the method while recording state, the dependency
contract includes the parser, and new append-only evidence files bind the
current implementation. Historical evidence remains present and is tested as
historical rather than silently rewritten.

A second full run correctly found that formatting after evidence generation
made the newly bound artifacts stale:

```text
4144 passed, 2 failed, 36 skipped
```

That failure demonstrates that implementation binding is active. Evidence was
regenerated after the final source formatting. The candidate repository-wide
run was:

```text
4148 passed, 0 failed, 36 skipped
```

After integrating the preserved main-worktree reports, the same candidate tree
again produced `4148 passed, 0 failed, 36 skipped`. The candidate SHA
`43f6c6b40a0be4ab093116e06bc50a425360ff5b` then passed Ubuntu, Windows,
PostgreSQL, and container jobs in GitHub Actions run `34951582738`.

The first GitHub `main` run of that SHA preserved two Windows failures. A large
monotonic-clock value made a 10-second configured budget subtract to
`10.000000000000057`, violating the deterministic upper-bound contract. The
runtime now clamps the computed remainder to the configured budget and a new
regression reproduces the pre-fix rounding deterministically. Because
`app/runtime/resources.py` is evidence-bound, new append-only v3 identity and
dark-observation evidence was generated after the fix; v1/v2 evidence remains
historical and parseable.

The final main-worktree repository run was:

```text
4155 passed, 0 failed, 32 skipped
```

Four conditional public-data replay/protocol tests that skipped in the isolated
candidate path ran and passed from the main worktree. The 32 remaining skips are
retained in the JUnit output and are not counted as passes. The final GitHub
`main` run is still required before tagging.

## Public Repository Audit

The first publication audit found 44 local-path, username, or non-example email
findings across 2,494 candidate files. Only public derivative evidence was
redacted. Original bytes remain in the private D-drive audit archive.

Nested and outer manifests were recomputed, while original source hashes and
historical result/status fields were retained. The transformation is recorded
in:

`docs/review/bounded_correctness_public_20260907/PUBLIC_REDACTION_MAP.json`

Final result:

```text
public candidates=2524 findings=0
```

## Final Local Gates

Before the release commit, all five portfolio gates passed:

| Gate | Result |
|---|---|
| Dependency consistency | PASS |
| Python compile | PASS |
| Final evidence consistency | PASS |
| Agent, ACL, and Guard regression | PASS |
| Public repository audit (`2524 candidates / 0 findings`) | PASS |

Changed and newly added Python files also passed Ruff, and `git diff --check`
reported no whitespace errors. A clean-commit gate and the GitHub Actions matrix
are required before the tag is treated as released.

## Quality Evidence Boundary

This release does not create a new WixQA retrieval result, independent answer
accuracy result, production latency SLO, or universal security result. The
existing measured claims remain governed by
`docs/handoffs/RESUME_METRIC_LEDGER.md`.

The September 15 real-model development comparison remains a negative release
decision: Qwen3.5:4b recovery increased the deterministic publication proxy
from 40/100 to 56/100 but changed wrong-answered cases from 0/120 to 1/120 and
did not satisfy the predeclared promotion gate. Later 94/100 and 96/100 figures
are consumed-output replay diagnostics, not fresh end-to-end accuracy, and are
not resume claims.

## Safe Public Statement

The repository can be described as a mainline, locally reproducible portfolio
release with bounded Agent control, evidence-governed publication, defense in
depth, append-only evidence, and 4,155 passing tests at release verification.
It cannot be described as deployed to production, independently validated for
answer accuracy, universally secure, or governed by a production SLA.
