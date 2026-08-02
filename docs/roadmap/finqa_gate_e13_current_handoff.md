# FinQA Gate E13 Current Handoff

## Authoritative state

- Decision: `E13_OPERATIONAL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF`
- Protocol SHA: `4604572c065d69d8d79f7287cfb206143c01e1ea11c4a6ec85c0bea4ee845f97`
- Public evidence SHA: `b933f83dff1307828309222c276ea0a5d70372324cdd7822c79dd41b463106d3`
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- Challenger: `finqa_top4_boundary_ranker_v1`
- Challenger mode: `SHADOW_DEFAULT_OFF`
- Input: official FinQA train only, deterministic 128-case selection
- Quality labels: projected out before typed validation
- Typed skeleton: gold program structure only
- Internal cohort: `CONSUMED_NOT_ACCESSED`
- Frozen test: `UNTOUCHED`
- Production traffic: `NOT_RUN`

## Completed

1. Strict protocol binding the E12 evidence chain, train SHA, selected ID set,
   worker budgets, replay gates, fault gates, privacy fields, and non-claims.
2. Persistent Windows-compatible `spawn` worker with typed handshake and one
   in-flight request.
3. Bounded canonical IPC with 1 MiB request and 64 KiB response limits.
4. Hard parent timeout with terminate, join, kill fallback, and clean restart.
5. Crash, malformed response, input mismatch, oversize, and startup failure
   isolation.
6. Train-label projection and runtime-only source-constant derivation from
   retrieved, Guard-admitted numeric candidates.
7. Real 128-case train replay with aggregate-only latency/RSS/divergence output.
8. Separate fault injection and exact implementation/evidence hash tests.

## Accepted result

```text
selected / prepared                128 / 117
preparation rate                   91.41%
completed / attempted              117 / 117
MATCH / DIVERGED                   74 / 43
roles / changed roles              252 / 83
worker errors / timeouts/restarts  0 / 0 / 0
p50 / p95 / max observation        5.659 / 16.443 / 37.682 ms
maximum child peak RSS             91,136,000 bytes
model calls                        0
fault gates                        5 / 5
all gate checks                    16 / 16
E13 focused tests                  16 passed
external-dataset regression        424 passed
full repository regression         2937 passed / 29 skipped / 3 warnings
public repository audit            1291 candidates / 0 findings
compileall / pip check              PASS / CLEAN
```

This is operational evidence. `MATCH/DIVERGED` is not correctness, the timer is
not end-to-end RAG latency, and process peak RSS is not E11 incremental memory.

## Do not edit without versioning

The public evidence binds these files by SHA:

```text
app/external_datasets/finqa_shadow_worker_protocol_v1.py
app/external_datasets/finqa_shadow_worker_v1.py
app/external_datasets/finqa_shadow_replay_v1.py
scripts/audit_finqa_shadow_worker_replay_v1.py
```

Any behavior change requires an E13-v2 or later protocol and a new public
evidence filename. Do not overwrite the E13-v1 protocol or result.

## Known limits

- No OS network sandbox, CPU quota, job object, cgroup, worker pool, durable
  queue, or distributed metrics backend is claimed.
- The replay is sequential and local on one Windows host.
- Gold program structure bypasses planner realism.
- Eleven selected cases failed preparation; they were not silently counted as
  worker successes.
- No answer labels were consumed, so no quality comparison or promotion
  decision can be made.
- The E11 internal cohort cannot be reused and frozen test remains untouched.

## Next action

Exact E13 commit `09aabf5` was pushed, but Actions run `30734063847` failed
after Ubuntu/Windows completed 2934/2958 tests because three test setups
unconditionally required ignored private FinQA train bytes. The protocol and
runtime were not changed. A follow-up splits public protocol tests from the two
private-train integration tests, which now skip only when the private source is
absent. Push the repair and verify its exact-SHA remote CI. Only after that
should a new protocol consider pool/queue/backpressure or
durable aggregate telemetry. Promotion still requires independent quality
evidence and a separate release decision.

Recommended model for worker-pool design, resource accounting, and release
review: **5.6 Sol / Extra High**.
