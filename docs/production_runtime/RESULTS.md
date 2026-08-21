# Production Runtime Validation Results

Evidence date: 2026-08-21. Baseline SHA: `909a9710932c6c4744c462db0e33ed0d222ecb1a`.
The final implementation SHA is recorded after commit in the closeout update.

Environment: Windows `10.0.26200`, AMD64, CPython `3.11.9`, project `.venv`.
Commands below ran on the dirty implementation worktree based on the exact
baseline SHA; none is presented as a clean-release result.

## Development results

| Command | Result | Meaning |
|---|---|---|
| `python -m pip check` | exit 0, no broken requirements | Installed environment is resolver-consistent |
| `python -m compileall -q app scripts streamlit_app tests` | exit 0 | Application, scripts, UI, and tests compile |
| `python -m pytest tests/agent_runtime -q` | `81 passed, 1 skipped` | All local Agent Runtime tests passed; PostgreSQL was skipped because `TEST_POSTGRES_DSN` was absent |
| `python -u -X faulthandler -m pytest -q -p no:cacheprovider` (first full run) | exit 1: `3317 passed, 30 skipped, 2 failed` | Runtime tests passed; README command contract and exact dependency-set contract exposed two unsynchronized repository surfaces |
| targeted rerun of the two failed repository contracts | exit 0: `6 passed` | Harness command moved out of fixed Quick Start; four direct dependencies added to the exact contract |
| `python -u -X faulthandler -m pytest -q -p no:cacheprovider` (final development run) | exit 0: `3322 passed, 30 skipped`, 3 existing SWIG warnings | Full deterministic repository regression passed after public harness schema equality was added |
| `python -m scripts.audit_public_repo` | exit 0: `1689 candidates / 0 findings` | No public-candidate secret/path finding under the repository auditor |
| `python -m scripts.verify_portfolio_release --allow-dirty` | exit 1: `FAILED_TARGET_IDENTITY`; all 5 internal gates passed | Incorrect invocation defaulted to expected branch `main`; failure retained |
| same verifier with `--expected-branch codex/durable-agent-runtime-and-policy-v1` | exit 0: `DEVELOPMENT_VERIFIED`, 5/5 gates | Correct dirty feature-branch development contract; no release authority |
| deterministic harness CLI smoke | exit 0, terminal `answered` | Returned citations, two policy lifecycle rows, tool events, verified artifact, and W3C IDs |
| `docker version --format ...` | exit 1, command unavailable | Docker is not installed, so a local PostgreSQL container could not be started |

The first durable fault-injection run produced `1 failed, 14 passed, 1 skipped`.
The failing `before_commit` recovery replayed a checkpointed test fault because
the graph had already advanced beyond the interrupt. The fix inspects
`get_state().next`, clears the fault only on the pending execute node, and
continues without issuing a second approval decision. The rerun passed.

## PostgreSQL status

The test is a real `PostgresSaver.setup()` plus interrupt round trip and is not a
mock. Local status is `SKIPPED: TEST_POSTGRES_DSN is not configured`. CI now has
a dedicated PostgreSQL 17.6 service job. Its result must be recorded after the
branch is pushed; until then, PostgreSQL is implemented but not locally proven.

## Interpretation

These are deterministic mechanism and failure-recovery tests. They do not show
answer-quality gain, production throughput, high availability, exactly-once
delivery, or a complete human-approval product.
