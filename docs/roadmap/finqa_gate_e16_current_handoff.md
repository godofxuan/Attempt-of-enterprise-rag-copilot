# FinQA Gate E16 Current Handoff

## Status

- Decision: `E16_MECHANISM_GATE_PASSED_DARK_OBSERVATION_REMAINS_DEFAULT_OFF`.
- Branch: `codex/rag-eval-system`.
- Scope: default-off service dark-observation mechanism.
- E11 FinQA service adapter: not implemented; typed contract mismatch recorded.
- Frozen test: untouched.
- Internal cohort: consumed, not accessed.

## Evidence

```text
protocol SHA-256
56ea7b40e7ec045e30fdedc30d3188475bd181e9321bacbc4e357fe0202037c0

public evidence SHA-256
1c997f2431f64b4d3fd158eb7bdf3e90ee4865c920f301612b6b8b1ec9f579f0
```

Local paired route audit:

```text
OFF provider calls                  0
OFF disabled offers                 24/24
enabled provider calls              24/24
primary response mismatches         0
model calls                         0
offer p50/p95/max                   0.017/0.024/0.033 ms
execution p50/p95/max               0.004/0.009/0.014 ms
admitted/terminal fault probe       2/2
controlled residual workers         0
frozen gates                        17/17
public audit                        1328 candidates / 0 findings after docs and v3 evidence
```

Final local repository closure:

```text
focused/API-runtime/security/external  28 / 177 / 245 / 446 passed
security skips                         6
full repository                        2977 passed / 29 skipped / 3 warnings
public audit                           1328 candidates / 0 findings
trusted identity v3                    20/20 / zero leak / zero denied side effect
trusted identity contract              trusted-identity-contract-e21503b0947a5608
trusted identity evidence SHA          4b967b62241c6cace088b5d99bf8df151e33c52bb4ce6a316ce983f9fc8d8e3e
```

The first full run exposed stale source hashes in the historical identity v2
result after E16 changed service files. The old artifact remains untouched and
parseable; current recomputation uses a new v3 artifact that includes the dark
runtime source in provenance.

## Immutable E16-v1 files

The public evidence binds exact hashes for these files. Do not edit them and
overwrite E16-v1 evidence. Use E16-v2 or E17:

- `app/config.py`
- `app/main.py`
- `app/runtime/dark_observation.py`
- `app/runtime/dark_observation_protocol_v1.py`
- `app/runtime/resources.py`
- `scripts/audit_dark_observation_service_v1.py`

The protocol and public evidence are also immutable historical records:

- `docs/external_datasets/evidence/dark_observation_service_protocol_v1.json`
- `docs/external_datasets/evidence/dark_observation_service_public_v1.json`

## Implementation summary

1. OFF/zero-sampling secure defaults and strict settings validation.
2. Process-local keyed request-ID sampling.
3. Bounded nonblocking admission and independent admission-time deadline.
4. Best-effort daemon workers with fixed outcome allowlist.
5. Queue cancellation, bounded close and residual-worker reporting.
6. Route integration after immutable primary response/receipt construction.
7. Aggregate-only operator metrics with no request rows or raw errors.
8. Real FastAPI OFF/ON paired audit and deterministic failure injection.

## Verification commands

```powershell
$env:TEMP=Join-Path (Split-Path (Get-Location) -Parent) '.rag-try-pytest-tmp'
$env:TMP=$env:TEMP

& '.\.venv\Scripts\python.exe' -m pytest `
  tests\runtime\test_dark_observation.py `
  tests\runtime\test_dark_observation_protocol_v1.py `
  tests\runtime\test_dark_observation_evidence_v1.py `
  tests\api_v2\test_dark_observation_api.py -q

& '.\.venv\Scripts\python.exe' -m scripts.audit_public_repo
```

The default audit command refuses to overwrite different immutable evidence.
Use an alternate `--output` path for a reproduction run.

## Resume point

Design E17 before implementation. Freeze an eligibility and typed adapter
protocol that maps only supported enterprise numeric questions into the exact
E11 input contract. Unsupported or incomplete inputs must become
`NOT_APPLICABLE`; no synthetic skeleton/catalog padding is allowed. Then inject
the verified adapter as the E16 provider and run paired local traffic without
changing the primary response.
