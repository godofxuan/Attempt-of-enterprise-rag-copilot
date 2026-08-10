# Portfolio Release Verification Gate

Date: 2026-08-10

Status: implemented after final evidence closure. This is an offline portfolio
verification gate, not a production deployment gate.

## Problem found

The project already had strong individual checks, but a reviewer had to know
which pytest files, audit command, and dependency checks to run. CI and the
interview runbook listed overlapping commands separately. That creates two
industrial risks:

1. **State drift.** README still said final exact-SHA CI was pending after that
   run had succeeded.
2. **Acceptance drift.** A developer could update one command list while CI or
   the demo runbook continued using another list.

Neither problem requires another model, retriever, Agent, or framework. The
correct fix is one named, executable acceptance contract.

## Implementation

The entry point is `scripts/verify_portfolio_release.py`:

```powershell
python -m scripts.verify_portfolio_release
```

It runs five bounded subgates from the repository root:

| Gate | What it proves | What it does not prove |
|---|---|---|
| `dependency_consistency` | Installed packages satisfy the pinned resolver state | Supply-chain safety or vulnerability absence |
| `python_compile` | Application, scripts, UI, and tests parse and compile | Runtime behavior |
| `final_evidence_consistency` | Headline metrics and recruiter documents still derive from public JSON | New model quality |
| `agent_acl_guard_regression` | Offline Agent state, ACL filtering, and retrieved-content Guard contracts pass | Production traffic or universal security |
| `public_repository_audit` | Configured path, secret, size, link, and evidence checks find no disclosure issue | Legal, privacy, or formal security certification |

The process runs every subgate even after one fails so the caller receives the
complete failure set. The final process exit code is nonzero if any subgate
fails or Git identity cannot be read.

## Git identity and dirty-worktree rule

The JSON records `HEAD`, branch, and dirty state. A normal run requires a clean
worktree. This matters because evidence tied to commit `A` cannot attest to an
uncommitted implementation `A + local edits`.

During development only, this command is allowed:

```powershell
python -m scripts.verify_portfolio_release --allow-dirty
```

It can exit successfully for diagnostics, but its status is
`DEVELOPMENT_VERIFIED` and `release_authority` remains `false`. It cannot be
mistaken for the clean result `VERIFIED`.

## Machine-readable output

The stable schema is `portfolio_release_verification_v1`. Each result contains:

- normalized command arguments, with the local Python absolute path replaced
  by `python`;
- gate ID, description, duration, status, and exit code;
- bounded stdout/stderr tails only when a gate fails;
- Git SHA, branch, dirty state, repository gate, and overall status;
- an explicit claim boundary and `release_authority: false`.
- aggregate total, passed, and failed gate counts for simple CI consumers.

Absolute interpreter paths are not published in the report. Successful command
logs are omitted because they add noise and may contain machine-specific paths.

## CI integration

Ubuntu and Windows now run the same `python -m
scripts.verify_portfolio_release` command used by a public clone. The existing
full pytest suite still runs first. The aggregate gate intentionally repeats a
small focused subset: this checks the public acceptance entry point itself, not
just the underlying tests.

## Tests added

`tests/test_portfolio_release_verifier.py` covers:

1. stable gate order and schema;
2. fail-closed behavior and bounded diagnostics;
3. clean versus dirty repository semantics;
4. JSON serialization and absolute-command-path redaction.

`tests/test_final_closeout_evidence.py` additionally rejects the stale pending-
CI sentence and requires README to expose the one-command entry point.

## Local validation

The implementation pass produced:

```text
focused verifier and closeout tests   8 passed
dirty development rehearsal           5/5 subgates passed
rehearsal status                       DEVELOPMENT_VERIFIED
full repository regression             3188 passed / 29 skipped
known warnings                         3 SWIG deprecation warnings
public repository audit                1544 candidates / 0 findings
```

The development rehearsal intentionally did not claim `VERIFIED` because the
new files were not committed yet. The strict clean-worktree run is performed
only after committing the exact implementation.

## Interview explanation

**Why not just tell reviewers to run all tests?**

`pytest` proves test behavior but does not check dependency consistency, Python
compilation, repository disclosure rules, or whether the worktree matches a
commit. The portfolio gate composes those existing checks under one stable
contract.

**Why is `release_authority` false when status is `VERIFIED`?**

`VERIFIED` is scoped to offline portfolio evidence. A production release would
also need an authorized environment, immutable image and configuration,
deployment approval, readiness, rollback, SLO, monitoring, and owner sign-off.
Using different authority labels prevents a local script from promoting itself.

**Did this improve RAG accuracy?**

No. It improved auditability and reproducibility. WixQA, EnterpriseRAG-Bench,
FinQA, and security metrics are unchanged. Claiming a quality gain from this
work would be incorrect.
