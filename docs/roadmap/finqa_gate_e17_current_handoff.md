# FinQA Gate E17 Current Handoff

## Authoritative state

- Decision: `E17_TYPED_ADAPTER_MECHANISM_PASSED_NOT_SERVICE_ENABLED`
- Protocol SHA-256: `d8e3433a2449ff7649b535eba416ced3a2a378b1871a640b2ad0a71508c0ea4d`
- Public evidence SHA-256: `3ad830e8ad4bad7b14e6979906e20f06f1e1487defdb48f979edee009915b4af`
- E17 frozen gates: `24/24`
- Real isolated E11 observations: `2/2`, both `MATCH`
- Ineligible worker calls: `0/5`
- Adapter model calls: `0`
- E16 background composition: `ADMITTED -> MATCH`
- Controlled residual service workers/typed contexts: `0/0`
- Related regression: `52 passed`
- Full repository: `3000 passed / 29 skipped / 3 known warnings`
- Public audit: `1339 candidates / 0 findings`
- Enterprise primary: unchanged
- E11 service status: `SHADOW_DEFAULT_OFF`
- Internal cohort: `CONSUMED_NOT_ACCESSED`
- Frozen test: `UNTOUCHED`

## Completed

1. Frozen online-only provenance and prohibited-quality-field protocol.
2. Self-hashing strict typed context.
3. Exact eligible/not-applicable resolution state machine.
4. Capacity-bounded, TTL, consume-once request-ID resolver.
5. Duplicate request-ID rejection without overwrite.
6. E8 primary computation inside the adapter.
7. Exact E11 worker outcome mapping to E16 provider outcomes.
8. Fixed safe error codes and aggregate-only metrics.
9. E16 background-service composition without editing E16 v1 files.
10. Two real persistent `spawn` worker observations and clean close.
11. Fault injection for binding, deadline, resolver, worker, capacity and TTL.

## Frozen implementation

The public E17 evidence binds these files. Do not edit them and overwrite v1
evidence. Use a new version for behavior changes:

```text
app/external_datasets/finqa_service_adapter_protocol_v1.py
app/external_datasets/finqa_service_adapter_v1.py
scripts/audit_finqa_service_adapter_v1.py
```

## Claim boundary

E17 proves an adapter mechanism for an already complete online typed context.
It does not implement online skeleton generation, enterprise evidence-to-catalog
construction, service-route registration, production traffic, quality or an
SLO. The two real worker observations are mechanism probes, not a quality set.

## Next stage

E18 should freeze and implement the missing service data-flow seam:

```text
authorized Guard-admitted retrieval result
  -> numeric candidate extraction
  -> safe catalog
  -> online value-free skeleton plan
  -> typed eligibility resolution
  -> bounded resolver registration
  -> E16 admission
  -> explicit discard when not admitted
```

Requirements:

- no gold/oracle program or quality labels;
- no re-retrieval without exact tenant/ACL context;
- provider/resolver/isolated worker owned by service lifespan;
- primary response and feedback receipt remain byte-identical;
- default remains `OFF`;
- internal cohort remains consumed and frozen test untouched;
- use a versioned E18 implementation instead of changing E17-v1 bound files.

Recommended model: **5.6 Sol / Extra High**.
