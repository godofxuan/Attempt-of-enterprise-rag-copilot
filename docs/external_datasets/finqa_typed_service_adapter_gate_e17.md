# Gate E17: Online Typed Eligibility and FinQA Service Adapter

## Decision

`E17_TYPED_ADAPTER_MECHANISM_PASSED_NOT_SERVICE_ENABLED`

E17 closes the type boundary between the generic E16 dark-observation owner
and the existing E8/E11 FinQA descriptor comparison. It adds a strict online
context contract, fail-closed eligibility, a bounded consume-once cross-thread
resolver, E8 primary computation inside the adapter, and exact E11 worker
outcome mapping.

It does not generate an online typed skeleton, retrieve enterprise evidence,
enable the service route, promote E11, or measure answer quality.

## Why this gate was necessary

E16 deliberately stopped at a generic provider interface:

```text
DarkObservationRequest
  request_id
  question
  primary_mode
  primary_stop_reason
```

The verified E11 worker requires:

```text
question
SemanticProgramSkeletonV2
RetrievableSafeDescriptorCatalogV3
FinQAPrimaryDescriptorDecisionV1 from E8
```

Earlier E13-E15 replay code obtained the skeleton from FinQA's gold program
structure. That is valid for a disclosed operational replay, but it is not an
online service input. Reusing it in the service adapter would be target
leakage. E17 therefore permits only `ONLINE_RULES` or `ONLINE_MODEL` skeleton
origins and `RETRIEVED_ADMITTED_EVIDENCE` catalog origin. Gold answer, gold
program and target-label fields are prohibited by the frozen protocol.

## Frozen protocol

```text
protocol
docs/external_datasets/evidence/finqa_service_adapter_protocol_v1.json

protocol SHA-256
d8e3433a2449ff7649b535eba416ced3a2a378b1871a640b2ad0a71508c0ea4d

public evidence
docs/external_datasets/evidence/finqa_service_adapter_public_v1.json

public evidence SHA-256
3ad830e8ad4bad7b14e6979906e20f06f1e1487defdb48f979edee009915b4af
```

The protocol binds the exact E16 service protocol/evidence and E13 isolated
worker protocol/evidence. It freezes six eligibility reasons, exact outcome
mapping, zero model calls inside the adapter, no worker call for ineligible
inputs, aggregate-only public output, consumed internal cohort and untouched
frozen test.

## Runtime design

```text
request execution thread
  -> an upstream online component resolves eligibility
  -> optional complete typed context
       question
       value-free skeleton
       safe descriptor catalog
       online-only provenance enums
       exact context SHA-256
  -> bounded ephemeral resolver.register(request_id, resolution)

E16 dark worker thread
  -> resolver.resolve(request_id) performs atomic pop
  -> NOT_APPLICABLE? return without E8/E11 call
  -> verify exact request question binding
  -> compute E8 primary inside adapter
  -> verify E8 made zero model calls
  -> call verified isolated E11 worker
  -> MATCH      -> E16 MATCH
  -> DIVERGED   -> E16 DIFFERENT
  -> failure    -> fixed safe provider error
```

The adapter never accepts an externally supplied primary decision. Computing
E8 inside the adapter prevents a caller from pairing E11 with a stale or
different primary result.

## Code map

### Protocol model

`app/external_datasets/finqa_service_adapter_protocol_v1.py` defines strict,
frozen Pydantic models for:

- allowed online origins and prohibited quality fields;
- eligibility reasons and no-worker conditions;
- E11-to-E16 outcome mapping;
- the frozen audit matrix;
- aggregate-only public output.

### Typed context and eligibility

`app/external_datasets/finqa_service_adapter_v1.py` defines
`FinQATypedServiceContextV1`. Its binding covers exact canonical bytes of:

```python
{
    "question": question,
    "skeleton": skeleton.model_dump(mode="json"),
    "catalog": catalog.model_dump(mode="json"),
}
```

The context schema cannot represent a gold origin. Pydantic rejects unknown
fields and a changed binding hash. `FinQATypedServiceResolutionV1` enforces:

```text
ELIGIBLE       <=> TYPED_CONTEXT_COMPLETE and context is present
NOT_APPLICABLE <=> one frozen abstention reason and no context
```

This prevents ambiguous rows such as `ELIGIBLE` with a missing catalog or
`NOT_APPLICABLE` while silently carrying a typed context.

### Ephemeral resolver

`FinQAEphemeralContextResolverV1` bridges the request thread and E16 worker
thread. It provides:

- fixed capacity from 1 to 4096;
- TTL from 10 ms to 60 seconds;
- duplicate request-ID rejection without overwrite;
- atomic consume-once `pop`;
- explicit discard for non-admitted E16 offers;
- shutdown clearing;
- aggregate counters only.

The resolver stores request context only in memory until it is consumed,
discarded, expired or closed. Its snapshot contains no IDs, questions,
descriptors or raw errors.

### Provider adapter

`FinQATypedServiceAdapterV1.observe()` performs these checks in order:

1. reject an already expired E16 deadline;
2. resolve one eligibility result;
3. return `NOT_APPLICABLE` before any primary/worker call when ineligible;
4. compare the context question with the E16 request question;
5. compute the E8 v5 primary on the exact question/skeleton/catalog;
6. reject any unexpected primary model call;
7. call the isolated E11 worker;
8. map only terminal `MATCH` or `DIVERGED` outcomes;
9. reduce all failures to fixed codes and aggregate counts.

The adapter has an explicit `close()` because the E13 worker owns a child
process. E17 tests and audit close it. The normal FastAPI container does not yet
own this provider lifecycle; that is an E18 admission requirement.

## Local evidence

| Check | Result |
| --- | ---: |
| Frozen eligibility reasons covered | `6 / 6` |
| Ineligible requests | `5` |
| Worker calls for ineligible requests | `0` |
| Synthetic exact outcome mappings | `2 / 2` |
| Real isolated E11 observations | `2 / 2` terminal |
| Real E11 outcomes | `2 MATCH / 0 DIFFERENT` |
| Real worker exit code | `0` |
| E16 background composition | `ADMITTED -> MATCH` |
| Residual E16 threads | `0` |
| Residual typed contexts | `0` |
| Adapter model calls | `0` |
| Frozen gate checks | `24 / 24` |
| Focused E17 tests | `23 passed` |
| E12/E13/E16 related regression | `52 passed` |
| Full repository | `3000 passed / 29 skipped / 3 known warnings` |
| Public repository audit | `1339 candidates / 0 findings` |

The real-worker aggregate latency was approximately `3.581 ms` for the warm
observation and `732.317 ms` maximum for the first observation including
Windows `spawn` startup. With only two observations, these are mechanism
measurements, not percentiles suitable for an SLO.

Dependency consistency, full compileall, frozen evaluation hash verification,
quality-review packet verification, expanded-corpus quality and the public
repository audit also passed. The quality-review packet remains honestly
`NOT_RUN`; E17 did not manufacture human labels.

## Fault injection

| Fault | Safe result | Worker calls before rejection |
| --- | --- | ---: |
| Context question differs from E16 request | `input_binding_mismatch` | `0` |
| Deadline expired before resolution | `deadline_expired` | `0` |
| Resolver raises with internal detail | `resolver_error` | `0` |
| Worker raises with internal detail | `worker_error` | `1` |
| Deadline is NaN or infinite | `invalid_deadline` | `0` |
| Adapter is already closed | `adapter_closed` | `0` |
| Duplicate request ID | `duplicate_request_id` | n/a |
| Resolver at capacity | `capacity_exceeded` | n/a |
| Context consumed twice | second resolve abstains | n/a |
| Context expires | resolve abstains | n/a |

No raw exception, question or request ID enters the adapter/public snapshots.

## Problems found and corrected

### E17-I01: offline replay helper contained gold program structure

The first architecture inspection found that E13 preparation calls
`build_oracle_semantic_program_v2(question, case.qa.program, ...)`. Reusing that
function would make the service adapter look complete while depending on a
field unavailable at inference time. The implementation instead accepts only
an explicitly online-origin typed context and records online planning as a
separate missing capability.

### E17-I02: E16's minimal provider request cannot carry evidence safely

E16 intentionally excludes sources and identity from its provider fields. An
adapter cannot safely re-retrieve by question because it lacks tenant and ACL
context. E17 therefore introduces an ephemeral request-ID resolver for already
authorized typed context. The service route is not edited in this gate.

### E17-I03: zero-valued counters appeared without real events

The first resolver tests showed `expired_total: 0` and
`shutdown_discarded_total: 0` because `Counter += 0` creates a visible key.
The implementation now creates those keys only when events occur, preserving
clear metric semantics.

### E17-I04: process startup dominates the first observation

The first real observation took about 735 ms while the warm observation took
about 3.5 ms. E17 keeps execution asynchronous and default-off and does not
claim a latency SLO. E18 must retain lifecycle-owned persistent worker startup
outside the primary request.

### E17-I05: a resolver could spoof the adapter error type

The first implementation re-raised `FinQAServiceAdapterErrorV1` from a
resolver. An untrusted resolver could place request content in its `code` and
control the outward error text. The adapter now treats every resolver exception
as `resolver_error`, validates the exact resolution class, rejects non-finite
deadlines and rejects calls after close before resolution.

## Claim boundary

E17 proves that a complete, explicitly online typed context can be safely
adapted to the existing E8/E11 shadow machinery. It does not prove that the
enterprise service can yet produce that context, that all financial questions
are supported, that E11 improves answers, or that any production traffic was
observed.

## Next admissible gate

E18 should add a versioned service data-flow seam without editing the frozen
E17 v1 implementation in place:

1. retain ACL and Guard-admitted evidence from the primary request;
2. build `RetrievableSafeDescriptorCatalogV3` from only that evidence;
3. run a bounded online value-free skeleton planner or deterministic rule path;
4. classify failures into the frozen abstention reasons;
5. register the resolution before E16 admission and discard it when admission
   is disabled, sampled out, unavailable, backpressured or closed;
6. make resolver and isolated provider lifecycle-owned resources;
7. remain `OFF` by default and compare exact primary responses before/after;
8. use new visible synthetic or unlabeled traffic only, never the consumed
   internal cohort or frozen test.

Recommended model: **5.6 Sol / Extra High** because this change crosses ACL,
Guard, retrieval, planner, request lifecycle and process ownership boundaries.
