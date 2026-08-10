# Final Evidence Closure: Environment and Baseline

## Locked environment

- Branch: `codex/rag-eval-system`
- Baseline SHA: `02d855d40766af954d5a744a5eb78a9be9438895`
- Baseline worktree: clean
- Python: 3.11.9, 64-bit
- OS: Windows 11 Pro `10.0.26200`
- Time zone: Asia/Shanghai
- Baseline run ID: `baseline-20260810T120926Z-02d855d`

Raw logs remain under `.private/final_evidence_closure/reproduction/` because
they contain local absolute paths. Public evidence contains only sanitized
aggregates and hashes.

## Baseline commands

| Command | Exit | Runtime | Result |
|---|---:|---:|---|
| `python -m pip check` | 0 | 1.283 s | no broken requirements |
| `python -m compileall app scripts tests` | 0 | 1.226 s | 75 files/messages compiled |
| `python -m pytest -q` | 1 | 293.766 s wrapper / 281.59 s pytest | 1 failed, 3187 passed, 29 skipped, 3 warnings |
| `python -m scripts.verify_portfolio_release` | 0 | 20.332 s | 5/5 gates, but old v1 identity was observational only |

The only full-suite failure was
`test_concurrent_same_key_writers_converge_to_one_canonical_entry`. Four
spawned Windows processes raced while initializing `.cache.lock`; one received
`PermissionError` from `os.write()` before the file lock had been acquired.

## Reproduction that isolated the cause

| Probe | Result |
|---|---:|
| D-drive repository-local `basetemp`, unchanged code | 0/10 failures |
| Default C-drive pytest temp, unchanged code | 2/10 failures |
| Default C-drive temp outside sandbox, unchanged code | 3/10 failures |
| Windows empty-file `msvcrt.locking` probe | lock succeeds before any byte is written |
| Default C-drive temp after ordering fix | 0/30 failures |

The first baseline is intentionally retained as `FAILED`. The later green
evidence demonstrates a repair; it does not rewrite history.

## Final regression validation

The repaired tree was validated with a short repository-local pytest root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .private\t\full
```

Result: `3202 passed, 30 skipped, 3 warnings in 299.92 s`.

The location is deliberate on Windows. A deeply nested global `TEMP/TMP`
caused path-length `FileNotFoundError` failures, while a short basetemp outside
`.private` correctly failed four identity tests because runtime identity
artifacts must stay under the private boundary. Keeping the ordinary process
temporary directory unchanged and using short `.private\t` satisfies both
contracts without moving the test workload to the C drive.

## Evidence boundary

This stage verifies local process behavior, deterministic tests, hashes and
offline repository contracts. It does not prove production uptime, power-loss
durability, semantic answer quality, third-party reproduction or an SLO.
