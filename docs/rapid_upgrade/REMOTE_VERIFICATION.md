# Remote Release Verification

## Validated release payload

- Branch: `codex/rag-eval-system`
- Commit: `68523e840a8f03b32d02ac78efd14af9889765ec`
- Workflow: `ci`
- GitHub Actions Run: `31316231539`
- URL: `https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/31316231539`
- Created: `2026-08-09T13:36:06Z`
- Completed: `2026-08-09T13:47:04Z`
- Conclusion: `success`

## Jobs

| Job | Job ID | Conclusion |
|---|---:|---|
| `deterministic-ubuntu-latest` | `93251819794` | `success` |
| `deterministic-windows-latest` | `93251819819` | `success` |
| `linux-container-contract` | `93252615946` | `success` |

The Windows success is additional evidence that the earlier local sandbox
`PermissionError` was not reproduced by the real Windows CI runner. The Linux
container job also passed the read-only/non-root runtime contract, deterministic
gates, readiness failure and rollback drill, and SBOM generation.

## Claim boundary

This workflow verifies repository correctness and deployment contracts at the
specified SHA. It does not convert development-only experiments into held-out
quality evidence, approve the multi-document Agent candidate, or qualify the
rejected full Dense build. Any later documentation-only commit is a descendant
of this validated payload and must be identified separately from this Run ID.
