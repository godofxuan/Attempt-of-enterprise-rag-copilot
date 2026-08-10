# Final Evidence Closure: Gap and Fix Journal

## 1. Computation-cache lock initialization race

### Symptom

The complete suite failed intermittently at
`app/indexing/computation_cache.py::_open_safe_lock_file`. Multiple spawned
processes saw a zero-length lock file and all attempted `os.write(b"\0")`
before entering `_lock_descriptor()`.

### Why it failed

A lock only serializes work after it is acquired. Initializing shared lock
state before the lock made the initialization itself racy. Windows ACL
hardening increased the chance that one already-open descriptor lost the
ability to complete the write in the default temporary directory.

### Minimal repair

`_open_safe_lock_file()` now only opens and validates file identity.
`_locked()` first acquires the byte-range lock and only the exclusive owner
initializes and fsyncs the byte. A regression test observes file size `0` at
lock acquisition and `1` inside the protected region.

### Result

Before: 5 failures in 20 same-environment repetitions. After: 0 failures in
30 repetitions. This is a concurrency correctness fix, not a retry mask.

## 2. FTS stale single-writer lock after process death

### Symptom

The old builder used a lock directory. `finally` removed it during a normal
exit, but a hard process termination skips Python `finally`; every later build
then treated the stale directory as a live writer.

### Minimal repair

The builder now uses a validated regular file plus an OS lock (`msvcrt` on
Windows, `flock` on POSIX). The owner JSON remains diagnostic content. The OS,
not PID polling, releases the lock when a process dies, so PID reuse cannot
create a false owner decision.

### Result

The formal matrix terminated a real child at 10 committed-document points,
three repetitions each. All 30 builds resumed, passed SQLite integrity and
manifest/hash verification, activated the intended run, and required no
manual lock deletion. Power-loss testing remains `NOT_RUN`.

## 3. Active pointer atomicity versus crash durability

### Existing strength and missing proof

The code already wrote a complete temp file, flushed and fsynced it, then used
`os.replace`. Unit tests observed atomic replacement, but monkeypatch failure
is weaker than a terminated process and the parent directory was not synced on
POSIX.

### Minimal repair

- publication-lock initialization moved inside the exclusive lock;
- stale `.active.json.*.tmp` files are removed only while holding the
  publication lock and only if they are regular single-link files;
- the parent directory is fsynced after replacement on POSIX;
- private fault hooks support real child termination at four exact stages.

### Result

Across 12 child-process exits, pre-replace stages preserved the verified old
pointer and post-replace preserved the verified new pointer. There were no
mixed or truncated pointers, restart failures or residual temps after retry.
Windows power-loss durability is still `NOT_RUN`, because process exit does
not simulate storage-controller or machine power loss.

## 4. Portfolio target identity

### Symptom

Verifier v1 printed branch and SHA but accepted any clean branch or detached
HEAD. A green report therefore did not prove it ran on the intended target.

### Minimal repair

Verifier v2 requires `codex/rag-eval-system` by default and accepts an optional
exact `--expected-sha`. Detached HEAD, wrong branch, wrong SHA and dirty state
all fail closed. The gate remains offline and has no deployment authority.

## 5. Agent deadline semantics

### Experiment

A fake navigator slept 50 ms while its request timeout was 10 ms. The registry
returned a structured timeout, but only after the blocking call returned.

### Correct claim

The Agent has bounded call counts, steps, context and cooperative deadlines.
It checks time before and after retrieval and Guard admission. It does not
provide hard wall-clock interruption for arbitrary blocking navigator code.
Adding a thread wrapper would not safely kill I/O and could leave residual
work, so the implementation stayed unchanged and the claim was narrowed.

## 6. Final-suite environment false failures

### Symptom

The first closeout rerun set global `TEMP/TMP` to a deeply nested evidence
directory and reported `97 failed, 3105 passed`. A second run used the short
`.t` basetemp and reported four identity-path failures.

### Diagnosis

The 97 failures shared missing-parent `FileNotFoundError` traces. The combined
evidence path, pytest node directory and application staging name exceeded the
practical Windows path limit. Running the earliest deployment failure plus all
46 email-parser tests with a short basetemp produced `47 passed` without a code
change.

The remaining four failures were a separate expected boundary check: identity
JWKS and feedback keys are rejected unless their paths are under `.private`.
Moving only the pytest basetemp from `.t` to `.private\t` made all four pass.

### Result

With normal process `TEMP/TMP` and `--basetemp .private\t\full`, the complete
suite produced `3202 passed, 30 skipped, 3 warnings`. No production repair was
made for these environment-induced failures. The reusable lesson is to keep
Windows test paths short without bypassing the repository's private-artifact
boundary.
