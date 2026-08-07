# FinQA E19 Current Handoff

## Current Decision

`E19_VERSIONED_SERVICE_WIRING_PASSED_DEFAULT_OFF_NOT_PROMOTED`

## Completed

- Added strict E19 protocol and predecessor hash binding.
- Added versioned `app.main_v2:app` FastAPI entrypoint.
- Added lifecycle-owned E19 service assembly and lazy Agent runner.
- Wired E18 typed observation at the post-primary ControllerState boundary.
- Removed the legacy generic route offer from the versioned path.
- Added aggregate-only allowlisted metrics.
- Covered default OFF, paired API equivalence, exactly-once offer, provider
  failure, startup failure, real queue backpressure, cleanup, and idempotent
  shutdown.
- Added reproducible public audit and immutable evidence.

## Frozen Evidence

- Protocol: `docs/external_datasets/evidence/finqa_service_wiring_protocol_v2.json`
- Public result: `docs/external_datasets/evidence/finqa_service_wiring_public_v2.json`
- Reproducer: `python -m scripts.audit_finqa_service_wiring_v2`

## Explicit Non-Promotion

The Docker command remains `app.main:app`. Run E19 explicitly with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main_v2:app --host 127.0.0.1 --port 8000
```

Do not change the Docker default based only on E19 mechanism evidence. A future
promotion gate needs container readiness/rollback, resource envelope, sustained
load, restart, and representative workload evidence.
