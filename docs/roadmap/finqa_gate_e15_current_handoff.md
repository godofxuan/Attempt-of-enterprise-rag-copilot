# FinQA Gate E15 Current Handoff

## Authoritative state

- Decision: `E15_LOCAL_CAPACITY_ENVELOPE_SUPPORTED_SHADOW_REMAINS_DEFAULT_OFF`
- Protocol SHA: `f201ecd767299a249fb3702489c395341f7c02a4500026d5aa419c6109ec1285`
- Public evidence SHA: `5e299683c2fd6fa0ad520fc2264ccc06b68dfe214e0c16b34b065f28e9bfc82f`
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- Challenger: `finqa_top4_boundary_ranker_v1`
- Challenger mode: `SHADOW_DEFAULT_OFF`
- Internal cohort: `CONSUMED_NOT_ACCESSED`
- Frozen test: `UNTOUCHED`
- Production traffic: `NOT_RUN`

## Completed

1. Frozen E15 protocol bound to exact E14 protocol and evidence hashes.
2. Fixed matrix of 1/2/4 workers by 1/4/8 callers, three repetitions each.
3. One-time preparation of the same 117 E13-selected requests.
4. Fresh process Pool for each trial with setup excluded from observation time.
5. Counterbalanced ascending/reversed/rotated 27-row schedule.
6. Exact schedule validation, median/spread aggregation and pre-registered
   speedup/efficiency comparisons.
7. Per-trial child-process cleanup and aggregate-only public evidence.

## Accepted result

```text
selected / prepared                128 / 117
trials / configurations            27 / 9
attempted / completed              3,159 / 3,159
errors / deadlines / restarts      0 / 0 / 0
maximum trial p95                  69.598 ms
maximum four-worker RSS upper      361,205,760 bytes
1->2 workers @4 callers speedup    2.075x; efficiency 1.038
1->4 workers @8 callers speedup    3.441x; efficiency 0.860
local recommendation               4 workers / 4 callers
recommended median throughput      631.169 observations/s
gate checks                        22 / 22
focused tests                      10 passed
external-dataset tests             446 passed
full repository                    2959 passed / 29 skipped
public repository audit            1315 candidates / 0 findings
```

These numbers cover local post-primary unlabeled Shadow observations. They are
not answer accuracy, full RAG QPS, cold-start latency, production capacity, or
an SLO.

## Immutable implementation files

The public evidence binds these files. Any behavior change requires E15-v2 or
later evidence rather than overwriting E15-v1:

```text
app/external_datasets/finqa_shadow_capacity_protocol_v1.py
app/external_datasets/finqa_shadow_capacity_v1.py
scripts/audit_finqa_shadow_capacity_v1.py
```

E13/E14 immutable files remain unchanged.

## Local closeout

- Compileall and dependency consistency passed.
- External regression passed 446 tests.
- Full regression passed 2959 tests with 29 skips and 3 known warnings.
- Frozen evaluation hash remained unchanged.
- Quality-review packet remains verified and honestly labeled `NOT_RUN`.
- Expanded corpus quality passed all checks.
- Public audit reported 1315 candidates and zero findings.

Exact commit and remote GitHub Actions evidence remain pending.

## Known limits

- One Windows host, three short repetitions, no sustained soak or confidence
  interval.
- Pool startup and data preparation excluded; no cold-start result.
- RSS is a child-slot peak sum, not whole-service simultaneous RSS.
- No API, complete RAG, production traffic, autoscaling, durable queue, or
  distributed telemetry.
- Gold program structure still bypasses planner realism.
- No new quality labels; E11 promotion remains unauthorized.

## Next action

After exact-commit CI passes, design E16 service dark integration. Keep Shadow
default-off; add bounded sampling, request-budget isolation, aggregate service
telemetry, startup/shutdown ownership, and rollback. Do not reinterpret the
local capacity result as a production SLO.

Recommended model: **5.6 Sol / Extra High**, because service integration adds
cross-request lifecycle, latency-budget and rollback invariants around an
already measured but serving-disabled subsystem.
