# Gate E16: Default-Off Service Dark Integration

## Decision

`E16_MECHANISM_GATE_PASSED_DARK_OBSERVATION_REMAINS_DEFAULT_OFF`

E16 integrates a bounded dark-observation owner into the real FastAPI service
lifecycle and `POST /agent/v2/chat` route. It proves primary-path isolation,
default-off behavior, aggregate-only telemetry and controlled shutdown with
local synthetic traffic. It does not run the E11 FinQA challenger against
enterprise questions and does not establish production traffic, quality or an
SLO.

## Why E16 was needed

E12-E15 progressively proved an offline FinQA Shadow coordinator, hard worker
termination, a bounded worker Pool and a local capacity envelope. None of
those gates owned the web-service lifecycle or observed requests through the
actual API route. A benchmark runner that never participates in startup,
shutdown, backpressure or operator telemetry is not yet an operational service
integration.

The first E16 architecture audit also found a contract mismatch:

```text
enterprise API input             E11 FinQA Shadow input
-----------------------------    ---------------------------------
question: free text              question
authenticated user context       typed program skeleton
optional top_k                   safe descriptor catalog
                                 immutable E8 primary selection
```

The project cannot honestly call E11 from `POST /agent/v2/chat` without first
building and validating the missing typed-input adapter. E16 therefore adds a
generic, injectable service owner. The FinQA adapter remains explicitly
`NOT_IMPLEMENTED_CONTRACT_MISMATCH_RECORDED`.

## Frozen protocol

The protocol was written and tested before the service implementation:

```text
protocol
docs/external_datasets/evidence/dark_observation_service_protocol_v1.json

protocol SHA-256
56ea7b40e7ec045e30fdedc30d3188475bd181e9321bacbc4e357fe0202037c0

source E15 protocol SHA-256
f201ecd767299a249fb3702489c395341f7c02a4500026d5aa419c6109ec1285

source E15 public evidence SHA-256
5e299683c2fd6fa0ad520fc2264ccc06b68dfe214e0c16b34b065f28e9bfc82f
```

Frozen audit profile:

| Control | Value |
| --- | ---: |
| Paired API requests | `24` |
| Enabled local workers | `2` |
| Waiting queue capacity | `4` |
| Local audit sample rate | `10,000 / 10,000` |
| Observation deadline | `100 ms` from admission |
| Shutdown grace | `2,000 ms` |
| Maximum offer p95 | `10 ms` |
| Allowed production default | `OFF / 0` |

The protocol rejects post-hoc changes to this profile, unknown fields and data
boundary drift through frozen Pydantic models.

## Runtime flow

```text
authenticated request
  -> readiness and identity checks
  -> primary Agent V2 completes
  -> safe trace and feedback receipt complete
  -> immutable primary response object exists
  -> best-effort dark offer
       -> OFF? return DISABLED
       -> unavailable/closed? return without throwing
       -> keyed HMAC sampling
       -> bounded put_nowait
       -> worker executes under independent deadline
       -> fixed aggregate outcome only
  -> return the already-built primary response
```

The primary request never waits for Shadow completion. The route catches any
unexpected owner exception as an additional containment boundary. Shadow is
not a readiness dependency and its startup or shutdown failure cannot make the
primary service unavailable.

## Code map

### Configuration

`app/config.py` adds:

- `dark_observation_mode`, default `OFF`;
- `dark_observation_sample_basis_points`, default `0`;
- worker count, queue capacity, observation deadline and shutdown grace.

Validation rejects ambiguous states: `OFF` with nonzero sampling and
`LOCAL_TEST_ONLY` with zero sampling are invalid.

### Protocol model

`app/runtime/dark_observation_protocol_v1.py` defines strict, frozen models for
the runtime contract, data boundary, audit profile and public-output boundary.
It verifies the exact protocol bytes and E15 source hashes.

### Service owner

`app/runtime/dark_observation.py` implements:

- `DarkObservationConfig`: bounded local configuration;
- `DarkObservationRequest`: immutable ephemeral provider input;
- `DarkObservationService.start()`: lifespan-owned daemon workers;
- `offer()`: constant-bounded checks, keyed sampling and `put_nowait`;
- `_worker_loop()` and `_run_one()`: deadline and error isolation;
- `close()`: stop admission, cancel waiting work and bounded worker join;
- `snapshot()`: aggregate counters, high-water marks and latency summaries;
- `safe_dark_observation_snapshot()`: safe operator fallback.

The service uses `time.perf_counter()` because the accepted Windows host
reports `15.625 ms` resolution for `time.monotonic()` but `100 ns` nominal
resolution for `perf_counter()`.

### Container and API integration

`app/runtime/resources.py` makes the dark owner an explicit
`ServiceContainer` resource. The normal builder creates an OFF owner and no
provider.

`app/main.py`:

1. starts and closes the owner inside FastAPI lifespan;
2. offers only after the primary response and feedback receipt exist;
3. sends only the minimal ephemeral fields;
4. exposes a safe aggregate under `dark_observation` in operator metrics.

### Audit and tests

`scripts/audit_dark_observation_service_v1.py` sends 24 identical request IDs
and questions through an OFF service and an enabled local-test service. It
compares status, exact response bytes and `X-Feedback-Receipt`, then injects
provider failure, deadline overrun, queue saturation and post-close admission.

Tests live in:

- `tests/runtime/test_dark_observation.py`;
- `tests/runtime/test_dark_observation_protocol_v1.py`;
- `tests/runtime/test_dark_observation_evidence_v1.py`;
- `tests/api_v2/test_dark_observation_api.py`;
- the lifespan regression in `tests/api_v2/test_health.py`.

## Data boundary

The provider may receive these fields only in process memory:

```text
request_id
question
primary_mode
primary_stop_reason
```

It does not receive principal, subject, tenant, groups, roles, answer text,
claims, citations, sources, trace or feedback receipt. Metrics retain no
request rows and no raw provider errors. Provider results are reduced to the
fixed allowlist `MATCH`, `DIFFERENT` or `NOT_APPLICABLE`; runtime failures are
reduced to aggregate counters.

## Local mechanism result

| Observation | Result |
| --- | ---: |
| OFF provider calls | `0` |
| OFF offers reduced to disabled | `24 / 24` |
| Enabled provider calls | `24 / 24` |
| Primary response mismatches | `0` |
| Model calls | `0` |
| Offer latency p50 / p95 / max | `0.017 / 0.024 / 0.033 ms` |
| Execution latency p50 / p95 / max | `0.004 / 0.009 / 0.014 ms` |
| Enabled workers after shutdown | `0` |
| Frozen gates | `17 / 17` |

The endpoint metric snapshot is intentionally captured before lifespan
shutdown, so it reports two live workers. Separate post-shutdown fields report
zero workers. This phase label prevents a running-state count from being
misread as a residual-worker failure.

## Fault injection

| Failure | Observed behavior | Primary effect |
| --- | --- | --- |
| Provider raises | `provider_error_total=1`, raw error discarded | none |
| Provider returns after deadline | `deadline_exceeded_total=1`, result discarded | none |
| One active + one waiting + third offer | third returns `BACKPRESSURE` immediately | none |
| Owner already closed | offer returns `CLOSED` | none |
| Dark startup and close raise | liveness and primary resource close still work | none |

The queue accounting check observed `2 admitted == 2 terminal`. Every accepted
item must end in completed, provider error, deadline exceeded or shutdown
cancelled. Silent disappearance fails the gate.

## Problems found and corrected

### E16-I01: a direct E11 route connection would be false integration

The API lacks the typed skeleton, descriptor catalog and E8 selection required
by E11. The solution was a generic provider boundary plus an explicit E17
adapter gap, not fabricated placeholder FinQA objects.

### E16-I02: one API test guessed the old trace shape

The first test expected the hand-written primary trace, but existing middleware
legitimately adds `request_id`. The test was strengthened to compare complete
OFF and failing-ON response bytes and feedback receipts.

### E16-I03: Windows timing initially printed zero

`time.monotonic()` maps to `GetTickCount64()` at `15.625 ms` resolution on this
host. Sub-millisecond offers were rounded to zero. Switching the service clock
to `time.perf_counter()` produced useful measurements without changing the
frozen `10 ms` gate.

### E16-I04: lifecycle phase was ambiguous in evidence

The pre-shutdown metric correctly showed two active service workers while the
post-shutdown gate showed zero residual workers. The evidence now labels the
snapshot phase and publishes separate post-shutdown aggregate counts.

### E16-I05: public audit rejected fake credential-shaped literals

The first audit helper used literal sampling material and literal bearer test
headers. They were not real credentials, but the repository audit correctly
reported a credential-style assignment. The helper now derives deterministic
test material from public domains and constructs test headers at runtime. The
scanner was not weakened: it moved from `1324 / 1` to `1324 / 0`.

### E16-I06: historical identity evidence detected source drift

The first full suite reached `2975 passed / 29 skipped` and failed one exact
trusted-identity recomputation. Field-level diffing showed all 20 behavior
cases were unchanged; only `app/main.py`, `app/runtime/resources.py` and the
derived contract ID differed because E16 intentionally changed those files.
The old v2 public result was not overwritten. The evaluator now accepts its
historical 11-file provenance while current evaluation emits v3 and also binds
`app/config.py` plus `app/runtime/dark_observation.py`. New evidence
`identity_matrix_result_e16.json` passed 20/20 cases, 14 denied cases with zero
side effects and zero credential leaks. The second full suite passed.

## Local verification

```text
E16 focused                         28 passed
API/runtime regression              177 passed
security regression                 245 passed / 6 skipped
external-dataset regression         446 passed
full repository regression          2977 passed / 29 skipped / 3 warnings
compileall                          PASS
pip check                           CLEAN
frozen evaluation hash              EXACT
quality-review packet               VERIFIED / NOT_RUN
expanded corpus quality             PASS
public repository audit             1328 candidates / 0 findings
```

The warnings are the existing SWIG deprecation warnings. Current trusted-
identity evidence is `trusted-identity-evaluation-v3`, contract
`trusted-identity-contract-e21503b0947a5608`, SHA-256
`4b967b62241c6cace088b5d99bf8df151e33c52bb4ce6a316ce983f9fc8d8e3e`.

## Public evidence

```text
docs/external_datasets/evidence/dark_observation_service_public_v1.json
SHA-256 1c997f2431f64b4d3fd158eb7bdf3e90ee4865c920f301612b6b8b1ec9f579f0
```

The evidence binds exact implementation hashes. Those files are immutable for
this E16 evidence version; behavior changes require E16-v2 or a later gate.

## Honest claims

E16 supports this statement:

> Implemented a default-off, bounded service dark-observation path with keyed
> sampling, independent deadlines, aggregate-only telemetry and failure-
> isolated lifecycle; 24 paired local API requests had zero response or
> feedback-receipt mismatches and all 17 pre-registered mechanism gates passed.

It does not support claims about production traffic, answer accuracy,
retrieval improvement, FinQA serving, hard cancellation of arbitrary Python
threads, distributed queues, autoscaling, availability or an SLO.

## Next gate

E17 should define an explicit typed eligibility and adapter contract. It must
either derive a safe FinQA-compatible request from an eligible enterprise
question or return `NOT_APPLICABLE`; it must never synthesize missing typed
inputs merely to force challenger execution. Only after that contract passes
can a real E11 adapter be evaluated through the E16 service owner.
