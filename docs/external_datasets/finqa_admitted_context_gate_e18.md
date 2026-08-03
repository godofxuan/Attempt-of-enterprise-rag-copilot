# Gate E18: Guard-Admitted Evidence to Online Typed Context

## Decision

`E18_ADMITTED_CONTEXT_MECHANISM_PASSED_ROUTE_REMAINS_DISABLED`

E18 implements the service data-flow component that E17 deliberately left
missing. It accepts the Agent controller's immutable `AdmittedEvidenceChunk`
objects, extracts bounded numeric candidates, builds a Guard-rescanned safe
descriptor catalog, creates a value-free online rule skeleton, registers the
typed resolution in the E17 consume-once resolver, and cleans the resolution
when E16 does not admit the observation.

The standard FastAPI route is not switched to this component in E18. E16 binds
`app/main.py`, `app/config.py`, `app/runtime/resources.py`, and the dark owner
to exact historical hashes. Silently editing those files would invalidate the
E16 evidence. Versioned route/container wiring is the next gate.

## Frozen Evidence

```text
protocol
docs/external_datasets/evidence/finqa_admitted_context_protocol_v1.json

protocol SHA-256
e1dabbd79901280e6d666a479d9cac15fda4c408ec2dc1412f148a6541491035

public evidence
docs/external_datasets/evidence/finqa_admitted_context_public_v1.json

public evidence SHA-256
82595dc7f0f2c119737a0e620bd1c1b8ce12a9c67d8b8a91335c3b0c1eac2747
```

The protocol binds the exact E17 protocol/evidence and current retrieved-
content Guard source. It freezes zero secondary retrieval, zero planner model
calls, bounded evidence/candidate budgets, duplicate-ID no-overwrite,
non-admitted cleanup, primary response object identity, default OFF, and the
route-disabled claim boundary.

## End-to-End Component Flow

```text
V2AgentRunner / ResponseBuilder receives ControllerState
  -> admitted_evidence_from_state_v1()
       accepts only AdmittedEvidenceChunk
       de-duplicates exact chunk snapshots
       rejects conflicting identities
  -> build_online_rule_skeleton_v1(question)
       seven narrow arithmetic families
       no candidate IDs or numeric values
       zero LLM calls
  -> build_finqa_admitted_context_v1()
       32 evidence / 16,000 characters / 128 candidates maximum
       current Guard rescan of every context
       extract_numeric_candidates_v2()
       operand-only candidates
       build_retrievable_safe_descriptor_catalog_v3()
       FinQATypedServiceContextV1 exact SHA-256 binding
  -> resolver.register(request_id, resolution)
  -> E16 dark_observation.offer(...)
       ADMITTED      keep for consume-once worker pop
       DISABLED      no preparation in default-off path
       SAMPLE_SKIPPED discard immediately
       UNAVAILABLE   discard immediately
       BACKPRESSURE  discard only rejected request
       CLOSED        discard immediately
  -> E17 adapter computes E8 and invokes E11
  -> lifecycle close: E16 service, E17 adapter/worker, resolver
```

No E18 function issues a retrieval query. The accepted content already passed
tenant/region/group ACL filtering and Guard admission in the normal Agent tool
boundary. E18 does not accept a raw `SearchHit`, dictionary, string list,
tenant ID, or principal and therefore cannot reconstruct a wider evidence
view.

## Code Map

### Protocol

`app/external_datasets/finqa_admitted_context_protocol_v1.py`

Strict frozen Pydantic models define input identity, budgets, planning
origins, cleanup matrix, primary isolation, audit thresholds, and explicit
non-claims. Unknown fields and changed literals fail validation.

### Context Builder

`app/external_datasets/finqa_admitted_context_v1.py`

`build_online_rule_skeleton_v1()` maps seven explicit English/Chinese operation
signals to a one-step `SemanticProgramSkeletonV2`:

| Family | Operation | Roles |
| --- | --- | --- |
| `percent_change` | `PERCENT_CHANGE` | `new_value(end)`, `old_value(start)` |
| `ratio` | `RATIO` | `part(target)`, `total(target)` |
| `exact_subtract` | `SUB` | `comparison_left`, `comparison_right` |
| `exact_add` | `ADD` | two `component` roles |
| `exact_multiply` | `MUL` | two `factor` roles |
| `exact_divide` | `DIV` | `value`, `divisor` |
| `average` | `AVERAGE` | two `component` roles |

The skeleton contains operation and semantic roles only. Numeric values remain
inside admitted evidence and extracted candidates; they never enter the
planner input.

`build_finqa_admitted_context_v1()` fails closed with frozen E17 reasons:

- no financial/numeric signal: `NOT_FINANCIAL_NUMERIC`;
- financial/numeric signal but no supported rule skeleton:
  `MISSING_TYPED_SKELETON`;
- no operand candidate/catalog: `MISSING_SAFE_CATALOG`;
- current Guard denies a context: `POLICY_DENIED`;
- duplicate IDs, budget overflow, extractor/catalog validation failure:
  `UNSUPPORTED_TYPED_CONTRACT`.

### Admission Coordinator

`FinQAAdmittedContextCoordinatorV1` owns the resolver, E17 adapter/worker, and
E16 dark owner as one lifecycle unit. Registration happens before asynchronous
offer so the worker cannot win a race and resolve a missing context. Cleanup
happens after every non-`ADMITTED` outcome.

If duplicate registration fails, the coordinator does not call `discard()`.
That detail is required: discarding by the reused ID would delete the first
request's legitimate context and turn no-overwrite into cross-request loss.

### Primary Response Wrapper

`FinQATypedObservationResponseBuilderV1` first asks its delegate to construct
the final `AnswerResponse`. Only then does it attempt E18 observation. Every
observer exception is contained, and the exact same response object is
returned without trace, source, claim, answer, or mode mutation.

The wrapper is an injectable seam, not yet the default FastAPI builder.

## Evidence and Fault Injection

| Check | Result |
| --- | ---: |
| Rule families | `7 / 7` |
| Repeated eligible builds | `112 / 112` |
| Preparation p50 / p95 / max | `0.623 / 0.921 / 1.523 ms` |
| Secondary retrieval calls | `0` |
| Planner/model calls | `0` |
| Enabled E16 admissions/completions | `8 / 8` |
| E17 adapter worker calls | `8` |
| Default-off worker calls | `0` |
| Primary response mismatches | `0` |
| Duplicate overwrite/delete | `0 / 0` |
| Backpressure rejected context discarded | `1 / 1` |
| Residual controlled workers/contexts | `0 / 0` |
| Frozen E18 gates | `22 / 22` |
| Focused E18 tests | `25 passed` |
| E16-E18 related regression | `61 passed` |
| Full repository | `3025 passed / 29 skipped / 3 known warnings` |
| Public repository audit | `1350 candidates / 0 findings` |
| Public evidence findings | `0` |

The timing is a local synthetic CPU mechanism measurement over 112 builds. It
is not a production latency percentile or SLO.

## Problems Found and Corrected

### E18-I01: the authorized evidence existed only inside ControllerState

The public `run_agent_v2_chat()` returns `AnswerResponse`; it does not expose
the strongly typed evidence objects. Re-retrieving inside E16 would be unsafe
because `DarkObservationRequest` intentionally contains no tenant or ACL
identity. E18 therefore consumes `ControllerState.evidence_by_aspect` at the
response-builder boundary and never re-queries retrieval.

### E18-I02: historical E16 files are exact-hash evidence

Directly editing `main.py/resources.py` would make old E16 evidence tests fail
and would erase the meaning of the historical mechanism result. E18 adds an
injectable versioned component and records the normal route as
`DISABLED_PENDING_VERSIONED_WIRING`. The next gate must version the serving
assembly and produce new route-level paired evidence.

### E18-I03: duplicate registration cleanup can delete the wrong request

An initial naive cleanup design could call `discard(request_id)` after every
registration exception. When the exception is `duplicate_request_id`, that
would delete the already registered original. The final coordinator discards
only when its own registration succeeded.

### E18-I04: first test fixtures used obsolete domain fields

The first focused run produced `20 passed / 2 failed`. The E18 behavior had
not failed; the fixture supplied removed `QueryAnalysis.answer_shape` and
`constraints` fields and omitted `original_question`. After aligning with the
current schema, the next run exposed the same issue for obsolete
`BudgetState.started_at_ms` and a missing required `ControllerState.top_k`.
Only test construction changed. Final focused and related runs passed.

### E18-I05: the first audit did not execute its declared backpressure row

The first audit passed 19 gates but only inferred backpressure behavior from
the coordinator code and E16 tests. That was weaker than the frozen cleanup
matrix. A blocking resolver provider and one-slot queue were added to produce
two admitted requests plus one deterministic `BACKPRESSURE` rejection. The
rejected context was removed, both admitted contexts were consumed, and close
left zero residual state.

## Claim Boundary

E18 proves that Guard-admitted Agent evidence can be transformed into an E17
typed context and admitted to E16 without re-retrieval, model planning, response
mutation, or residual context. It does not prove answer accuracy, E11 quality,
arbitrary financial coverage, production traffic, a latency SLO, or that the
standard FastAPI service currently uses this component.
