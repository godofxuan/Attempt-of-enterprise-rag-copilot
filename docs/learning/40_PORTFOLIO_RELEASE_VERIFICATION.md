# 40. Portfolio Release Verification: from scattered checks to one contract

## 1. What problem does this solve?

The repository already had thousands of tests. That did not automatically give
an external reviewer one unambiguous answer to this question:

> Which command tells me whether the public portfolio evidence is internally
> consistent and safe to inspect?

Before this change, the answer was a list: run `pip check`, compile Python, run
several pytest paths, then run the public audit. README, CI, and the interview
runbook could copy that list differently. In fact, README kept saying the final
CI run was pending after it had succeeded. This is called **state drift**.

The improvement is not a new RAG feature. It turns existing checks into an
explicit acceptance contract:

```powershell
python -m scripts.verify_portfolio_release
```

## 2. End-to-end flow

```text
CLI main
  -> parse --allow-dirty
  -> read Git HEAD / branch / worktree status
  -> run all five fixed gates
  -> normalize machine-specific command paths
  -> retain bounded diagnostics for failed gates
  -> derive repository_gate and overall status
  -> print portfolio_release_verification_v2 JSON
  -> exit 0 only for VERIFIED or DEVELOPMENT_VERIFIED
```

The five gates are deliberately fixed in code. The CLI does not accept an
arbitrary shell command, so a caller cannot replace the real checks while still
receiving the same schema and status.

## 3. Code walkthrough

### `Gate`

`Gate` is a frozen dataclass with `gate_id`, `description`, and `argv`. Frozen
objects cannot be modified after construction. That keeps gate identity stable
during one run.

### `GATES`

`GATES` is an ordered tuple. Order matters for readable diagnostics:

1. dependency consistency;
2. Python compilation;
3. evidence/prose consistency;
4. Agent, ACL, and Guard regression;
5. public repository disclosure audit.

The verifier still runs later gates when an earlier gate fails. This costs a
few extra seconds but gives the developer the complete repair list instead of
one failure per rerun.

### `_run_command`

The subprocess always receives a list of arguments and an explicit repository
root as `cwd`. It does not construct a shell string. This avoids quoting bugs
between Windows and Linux and avoids accidental shell expansion.

`sys.executable` makes every child command use the same Python interpreter as
the verifier. This matters when a machine has Conda, system Python, and `.venv`
at the same time.

### `_public_command`

Internally, the first argument may be a local absolute path such as a virtual-
environment interpreter. The JSON changes only that display value to `python`.
Execution still uses the real interpreter, while shareable diagnostics do not
leak an author-specific path.

### Git state

The verifier records:

- `git rev-parse HEAD`;
- `git branch --show-current`;
- `git status --short`.

A dirty worktree fails by default. Suppose Git says HEAD is commit `A`, but
`app/agent/controller_v2.py` has an uncommitted edit. A successful test would
describe `A + unknown local content`, not commit `A`. An external reviewer could
not reproduce that state from GitHub.

`--allow-dirty` exists only for development. Its successful label is
`DEVELOPMENT_VERIFIED`, which prevents a local diagnostic from being presented
as a clean release verification.

### Overall status

```text
any subgate failed             -> FAILED
Git identity unavailable       -> FAILED
dirty without explicit flag    -> FAILED
dirty with --allow-dirty       -> DEVELOPMENT_VERIFIED
clean and every subgate passed -> VERIFIED
```

`release_authority` is always `false`. This field prevents a scope error:
offline evidence verification cannot authorize a production deployment.

## 4. Why JSON instead of only green text?

JSON gives CI, a future wrapper, and an external reviewer stable field names.
Humans can still read the indented output, but automation does not need to parse
sentences such as "all checks look good".

The schema includes durations for operational visibility. It does not interpret
a faster run as a product optimization because runner load and filesystem cache
can change durations.

## 5. How the tests protect the contract

`tests/test_portfolio_release_verifier.py` injects a fake command runner. That
lets tests simulate Git and child-process outcomes without recursively starting
pytest inside pytest.

- the success test locks schema, repository identity, and gate order;
- the failure test proves one nonzero child exit makes the whole report fail;
- the dirty test distinguishes release and development semantics;
- the serialization test proves displayed Python commands contain no absolute
  interpreter path.

`tests/test_final_closeout_evidence.py` protects the user-facing side. It fails
if README again says final CI is pending or removes the one-command entry point.

## 6. Why this is industrial engineering

Industrialization is not the number of frameworks. It is the ability to state,
execute, observe, and enforce an acceptance condition consistently. This change
has four useful properties:

- the same entry point works for a public clone, Windows/Ubuntu CI, and an
  interview laptop;
- failures carry bounded diagnostics and a nonzero process exit code;
- Git identity prevents uncommitted local state from borrowing a commit's name;
- claim boundaries prevent an offline gate from becoming a production claim.

## 7. Interview questions and answers

**Why not use a Makefile?**

The repository is developed on Windows and tested on Windows and Linux. A Python
module reuses the already-required runtime and avoids adding a platform-specific
command dependency. A Make target could call this module later, but should not
become a second source of gate logic.

**Why repeat focused tests after the full CI test suite?**

CI must verify that the public one-command entry point itself works. The focused
subset takes little time and protects the exact workflow promised to reviewers.

**Does `VERIFIED` mean the RAG answer is correct?**

No. It means the defined offline portfolio gates passed. Model quality comes
from bound benchmark evidence; production quality additionally needs traffic,
human acceptance, and operational evidence.

**What happens when the audit finds one secret?**

The audit child exits nonzero, its gate becomes `FAILED`, the aggregate process
returns nonzero, and CI blocks the commit. Other gates still run so unrelated
failures are visible in the same report.

## 8. Exercises

1. Explain why a clean worktree is part of reproducibility rather than code
   style.
2. Add a fake-runner test for `git rev-parse` failure without invoking Git.
3. Explain why command durations are observations rather than SLO evidence.
4. Compare fail-fast and run-all-subgates behavior for a developer fixing CI.
5. Identify which additional evidence would be required before
   `release_authority` could represent production promotion.
