# FinQA Gate E12 Current Handoff

## Authoritative state

- Decision: `E12_MECHANISM_GATE_PASSED_SHADOW_REMAINS_DEFAULT_OFF`
- Protocol SHA: `20323918a34ca062eb4bfbf015dabd3b21b935bd12028516936c2600e4011ec5`
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- Challenger: `finqa_top4_boundary_ranker_v1`
- Challenger load: `READY`
- Default mode: `OFF`
- Serving route: `DISABLED`
- Production traffic: `NOT_RUN`
- Frozen test: `UNTOUCHED`

## Completed

1. Frozen default-off shadow protocol bound to the complete E8/E11 evidence
   chain.
2. Separate immutable primary decision and post-primary observation APIs.
3. Same-input canonical SHA binding before E8/E11 comparison.
4. Fail-closed artifact/evidence loader.
5. Three-failure, five-observation-cooldown circuit breaker with half-open
   recovery.
6. Privacy-bounded observations and thread-safe aggregate-only metrics.
7. Deterministic real-selector mechanism probe plus default-off, error,
   timeout, circuit recovery, tampering, and concurrency tests.
8. Public evidence bound to exact implementation hashes.

## Verification at gate close

```text
E12 focused tests                  14 passed
external-dataset tests             408 passed
full repository regression         2921 passed / 29 skipped
public repository audit            1278 candidates / 0 findings
public mechanism gate             11/11 passed
default-off challenger calls      0
circuit observations/calls        9/4
model calls                       0
```

The real synthetic mechanism probe produced `MATCH` with an injected audit
clock. It proves wiring only. It is not a latency benchmark or quality result.

The first full-suite attempt used an in-repository pytest basetemp and produced
four path-contract failures. A four-test repro passed after `TEMP/TMP` moved to
a D-drive repository-external directory; no application code was changed. The
subsequent full-suite result above is authoritative.

## Do not edit without versioning

The public E12 evidence binds these files by SHA:

```text
app/external_datasets/finqa_descriptor_shadow_protocol_v1.py
app/external_datasets/finqa_descriptor_shadow_v1.py
scripts/audit_finqa_descriptor_shadow_v1.py
```

Any behavior change must use E12-v2 or a new gate and regenerate a separately
named protocol/evidence chain. Do not overwrite E12-v1 evidence.

## Claim boundary

E12 does not add a production FinQA endpoint, process-isolated worker, hard
thread cancellation, durable metrics backend, real traffic, answer-accuracy
evidence, or serving authorization. E8 still decides every primary result.

## Next stage

E13 may implement an unlabeled operational replay and process-isolation
contract over disclosed train-only inputs. It may measure divergence, latency
buckets, error/circuit behavior, and resource cost. It must not tune E11,
consume the internal cohort again, access frozen test, or promote E11.

Recommended model for E13 protocol, worker isolation, and resource accounting:
**5.6 Sol / Extra High**.
