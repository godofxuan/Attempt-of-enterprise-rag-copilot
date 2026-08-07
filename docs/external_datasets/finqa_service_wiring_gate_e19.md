# FinQA Gate E19: Versioned Service Wiring

## Decision

`E19_VERSIONED_SERVICE_WIRING_PASSED_DEFAULT_OFF_NOT_PROMOTED`

E19 closes the service-wiring gap left by E18. The versioned FastAPI entrypoint
is runnable as `app.main_v2:app`, and its real `/agent/v2/chat` route now passes
the Controller's Guard-admitted evidence through the E18 typed-context builder
after the primary answer has been built. The standard Docker entrypoint remains
`app.main:app`; E19 is therefore integrated and testable, but not promoted as
the production default.

## Why A Versioned Assembly Was Required

E16 froze source hashes for `app/main.py`, `app/config.py`, and
`app/runtime/resources.py`. Editing those files would make the historical E16
evidence irreproducible. E19 therefore adds a new assembly rather than silently
rewriting the old one:

- `app/main_v2.py` owns the versioned API route and lifespan.
- `app/runtime/finqa_service_v2.py` owns construction, startup, shutdown, the
  wrapped Agent runner, and safe telemetry.
- `app/runtime/finqa_service_protocol_v2.py` freezes the E19 invariants.

This is a migration pattern: preserve the proved old entrypoint, build a new
entrypoint with stronger contracts, compare both, then promote in a separate
decision after operational evidence exists.

## Runtime Data Flow

```text
authenticated request
  -> V2AgentRunner
  -> controller retrieval and RetrievedContentGuard admission
  -> primary AnswerResponse is built
  -> FinQATypedObservationResponseBuilderV1
  -> bounded typed-context preparation from admitted evidence only
  -> register-before-offer consume-once resolver
  -> default-OFF dark observation service
  -> isolated FinQA worker only in LOCAL_TEST_ONLY
  -> the original primary response returns unchanged
```

There is no second retrieval and no planner-model call. The legacy generic
`service.dark_observation.offer(...)` route call is absent, preventing one
request from being observed twice.

## Lifecycle And Failure Semantics

`FinQAServiceRuntimeV2` owns the complete lifecycle:

1. Start base resources.
2. In `LOCAL_TEST_ONLY`, start the isolated worker and fail startup if it cannot
   start.
3. Start the typed coordinator and dark service.
4. On shutdown, close the coordinator first, then base resources.

Startup, close, and snapshot operations are idempotent or fail closed. The TTL
derived from the observation deadline is clamped to the resolver's supported
range. Queue admission stays bounded; when one request is active and one is
queued, the next request is rejected from observation without changing its
primary API response.

## Safe Observability

`safe_finqa_service_snapshot_v2()` exposes only fixed-schema aggregates. Counter
names use explicit allowlists, numeric values must be finite and non-negative,
and unknown status values become `UNAVAILABLE`. Questions, retrieved text,
tenant IDs, subject IDs, request IDs, exceptions, skeletons, and catalogs are
not retained in this public metric surface.

## Reproducible Evidence

Run:

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_finqa_service_wiring_v2
.\.venv\Scripts\python.exe -m pytest tests\runtime\test_finqa_service_protocol_v2.py tests\runtime\test_finqa_service_evidence_v2.py tests\api_v2\test_finqa_service_wiring_v2.py -q
```

The deterministic audit records:

- 8 OFF/LOCAL_TEST_ONLY API pairs;
- 0 response-byte mismatches;
- 0 feedback-receipt mismatches;
- OFF worker starts/calls of 0/0;
- enabled starts/offers/completions of 1/8/8;
- provider failure isolated behind HTTP 200 primary behavior;
- one bounded backpressure rejection and zero residual contexts after close;
- fail-closed startup and one worker close;
- zero legacy generic offers, secondary retrieval calls, planner model calls,
  and public content findings.

Final local repository verification passed `3035` tests with `29` skips and
the three existing FAISS SWIG deprecation warnings. The staged public repository
audit scanned `1362` candidate files and reported `0` findings. Two additional
Windows pytest cleanup notices concerned access to disposable C-drive temp
directories after tests completed; they did not change the successful exit code
or leave E19 runtime workers/contexts.

Protocol SHA-256:
`ec21d0a894e2a00d37a2c4aae8a48cd8cd1b8c0c19c4672503643bc3a924d67f`.

Public evidence SHA-256:
`1616e1f509e61c8e65c90dba076d11ae40e20f96448be757774c4a28ed31de39`.

## Problems Found During E19

1. The first API test fixture used `mode="answered"` without claims and
   citations. `AnswerResponse` correctly rejected this invalid state. The test
   was repaired to use a valid `not_found` primary response; production code was
   not weakened.
2. The first version imported private helpers from `app.main`, which also
   constructed the legacy module-level app. E19 copied the two small boundary
   helpers into `main_v2.py` to keep one unambiguous assembly per entrypoint.
3. Resolver TTL originally followed the configured deadline without an upper
   clamp. It is now bounded to 60 seconds, matching the resolver contract.
4. Aggregate telemetry originally accepted any syntactically safe counter key.
   It now uses semantic allowlists so private text cannot become a metric label.
5. Startup failures originally looked like `NEW`. The lifecycle now records
   `FAILED`, which makes operational diagnosis explicit.

## Non-Claims And Next Decision

E19 does not establish answer accuracy, retrieval quality, arbitrary financial
program coverage, production traffic, availability, an SLO, autoscaling, or
durable distributed queueing. Promotion of `app.main_v2:app` to the Docker
default must be a separate gate with container readiness, rollback, resource,
and representative workload evidence.
