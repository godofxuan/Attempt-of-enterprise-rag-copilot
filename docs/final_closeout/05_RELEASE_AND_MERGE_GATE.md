# Release and Merge Gate

## Identity

- Branch: `codex/agent-runtime-vnext`
- Previous audited SHA: `f291019dc1df80ac741782365ebf6960d7f1de19`
- Runtime fix SHA: `ab5c48735a69aec43e26abb240275f08004789e7`
- Working tree at runtime gate: clean
- New commits: PR-aware identity, ACL scope invariant, retry-safe HITL resume

## Local acceptance

| Gate | Result |
|---|---|
| Python 3.11.9 environment | PASS |
| pinned requirements / `pip check` | PASS |
| compileall app/scripts/UI/tests | PASS |
| targeted required-fix suite | PASS (38) |
| full pytest | PASS (3,290 passed; 29 skipped) |
| frozen/closeout evidence suite | PASS (53) |
| Agent Run Artifact verification | PASS (13 events; valid hash) |
| public repository audit | PASS (1,644 candidates; 0 findings before closeout docs) |
| clean portfolio release verifier | VERIFIED (5/5 subgates) |

## GitHub Actions

Run: `32274793459`

URL: <https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32274793459>

| Job/contract | Result |
|---|---|
| deterministic Ubuntu | PASS |
| deterministic Windows | PASS |
| linux-container-contract | PASS |
| pinned test/runtime image build | PASS |
| non-root runtime identity | PASS |
| read-only runtime filesystem | PASS |
| deterministic gates inside image | PASS |
| readiness success | PASS |
| expected readiness failure | PASS |
| rollback drill | PASS |
| SBOM generation and upload | PASS |

## PR identity contract

Push verifies checked-out branch against `github.ref_name` and HEAD against
`github.sha`. Pull requests check out the PR head SHA in detached mode, require
that SHA to equal event metadata, and require the event head ref to equal the
expected PR head branch. Missing or mismatched metadata fails closed.

## Decision

`MERGE_RECOMMENDATION: READY_TO_MERGE`

This file is not merge authority. The task explicitly leaves merging `main` to
the user.

