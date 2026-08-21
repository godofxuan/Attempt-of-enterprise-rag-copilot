# Production Runtime Validation Results

## 2026-08-22 P1 integrity overlay

Branch: `codex/durable-runtime-integrity-fix-v1`. Start HEAD:
`2e1c93cc8713bb2804a665221af38457b79afa44`.

Local results recorded before the implementation commit:

| Command | Result |
|---|---|
| `python -m pip check` | passed |
| `python -m compileall -q app scripts streamlit_app tests` | passed |
| scoped Ruff check and format check | passed |
| scoped mypy with `--follow-imports=skip` | passed for seven integrity modules; not a whole-repository claim |
| `python -m pytest tests/agent_runtime -q` | `103 passed, 2 skipped`; both skips require `TEST_POSTGRES_DSN` |
| bounded controller and harness regression | `144 passed` |
| first full repository run | `3341 passed, 31 skipped, 3 failed`; all three failures were stale documentation/CI contract expectations |
| targeted rerun after contract fixes | `3 passed` |
| final full repository rerun | `3344 passed, 31 skipped`, 3 existing SWIG warnings |
| first public audit | `1695 candidates / 2 findings`; deterministic token fixture naming and a pre-commit manifest link, fixed before closeout |
| final pre-commit public audit | `1695 candidates / 0 findings` |

The three full-run failures were retained and diagnosed: P10 initially reused a
historical table-count contract incorrectly, the canonical vNext branch phrase
was missing from the overlay text, and CI no longer contained its explicit
runtime dependency-install command. No product test failed. A final full rerun,
clean-worktree verifier, exact implementation SHA, and remote CI are recorded
in the P1 report/manifest only after they complete.

Evidence date: 2026-08-21. Baseline SHA: `909a9710932c6c4744c462db0e33ed0d222ecb1a`.
Final implementation SHA: `e848d8e6090267b28d351758fe8d3cb557dcd586`.

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
mock. Local status is `SKIPPED: TEST_POSTGRES_DSN is not configured`. The
dedicated PostgreSQL 17.6 GitHub Actions service job passed at the exact final
SHA. Windows, Ubuntu, and Linux-container jobs also passed in run
`32470591376`; total workflow duration was 12 minutes 20 seconds.

## Clean closeout

| Check | Result |
|---|---|
| Clean portfolio verifier at final SHA | `VERIFIED`, 5/5 gates passed |
| GitHub Actions run `32470591376` | `SUCCESS` |
| PostgreSQL checkpointer integration | passed against PostgreSQL 17.6 service |
| Deterministic Windows and Ubuntu jobs | both passed |
| Linux container contract | passed |
| Runtime SBOM | generated by CI, digest retained by the Actions artifact |

## Interpretation

These are deterministic mechanism and failure-recovery tests. They do not show
answer-quality gain, production throughput, high availability, exactly-once
delivery, or a complete human-approval product.
