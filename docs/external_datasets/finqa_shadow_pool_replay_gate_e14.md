# FinQA Gate E14: Bounded Shadow Worker Pool Replay

## Decision

`E14_BOUNDED_POOL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF`

E14 adds bounded local concurrency around the E13 isolated shadow worker. It
does not promote the E11 challenger, consume a new quality cohort, or change
the E8 primary decision.

## Why this gate exists

E13 proved that one persistent `spawn` worker could execute a verified E11
observation with hard process timeout and restart. It did not prove what
happens when several callers arrive together. An unbounded thread or process
per request would turn traffic bursts into memory growth and failure
amplification.

E14 therefore tests five operational questions:

1. Is the number of child processes fixed?
2. Is waiting work bounded by an explicit queue capacity?
3. Does overload fail fast without changing the primary result?
4. Does a caller deadline prevent late shadow work from replacing a response?
5. Can every process and dispatcher be reclaimed on shutdown?

## Frozen evidence chain

The protocol was frozen before the Pool implementation:

```text
protocol
docs/external_datasets/evidence/finqa_shadow_pool_replay_protocol_v1.json

protocol SHA-256
c92c4e99a189620a70a5600433f1bc0e3e21e5338dd21bbbc7da3ec5bcf5272b

source E13 protocol SHA-256
4604572c065d69d8d79f7287cfb206143c01e1ea11c4a6ec85c0bea4ee845f97

source E13 public evidence SHA-256
b933f83dff1307828309222c276ea0a5d70372324cdd7822c79dd41b463106d3
```

The source E13 protocol still binds the official FinQA train revision, exact
split hash, deterministic 128-case selection, prohibited quality fields, and
verified E11 evidence. E14 reuses that selection without accessing the
consumed internal cohort or frozen test split.

## Runtime topology

```text
four caller threads
        |
        v
admission lock + FIFO queue (capacity four)
        |                         |
        v                         v
dispatcher 0                  dispatcher 1
        |                         |
        v                         v
E13 spawn worker 0            E13 spawn worker 1
single in-flight              single in-flight
```

The Pool is an in-memory operational boundary. It is not a durable queue or a
distributed scheduler.

## Configuration

| Control | Frozen value | Meaning |
| --- | ---: | --- |
| Worker processes | `2` | At most two E11 observations execute concurrently |
| FIFO wait capacity | `4` | At most four admitted requests wait for a slot |
| Nominal callers | `4` | Load replay submits through four caller threads |
| Admission timeout | `0.25 s` | A full queue rejects the newest request after a bounded wait |
| Response deadline | `2.0 s` | Caller stops waiting and late shadow output is discarded |
| Shutdown grace | `20.0 s` | Dispatchers must finish before workers are closed |
| Overload policy | `reject_newest` | Existing admitted work keeps its queue position |

## Code map

### Protocol schema

`app/external_datasets/finqa_shadow_pool_protocol_v1.py`

- Uses strict, frozen Pydantic models.
- Rejects unknown fields, NaN values, and invalid capacities.
- Prevents nominal caller concurrency from exceeding workers plus queue slots.
- Freezes public aggregate groups and prohibited content.

### Pool runtime

`app/external_datasets/finqa_shadow_pool_v1.py`

- `FinQABoundedShadowWorkerPoolV1` owns the queue, dispatcher threads, and E13
  workers.
- `start()` eagerly verifies both child workers before accepting work.
- `observe()` performs bounded admission and waits only until the response
  deadline.
- `_dispatch()` gives each dispatcher one fixed worker, preserving E13's
  single-in-flight invariant.
- `metrics()` returns counters and high-water marks without request content.
- `close()` stops admission, drains waiting work, joins dispatchers, and closes
  child workers.

The state check and queue admission happen under the same lock. This prevents
the following race:

```text
caller sees RUNNING
close inserts STOP sentinels
caller enqueues behind STOP
no dispatcher remains to consume the request
```

### Concurrent replay

`app/external_datasets/finqa_shadow_pool_replay_v1.py`

- Reuses E13 label projection, case selection, Guard admission, typed skeleton,
  catalog construction, and E8 primary selection.
- Prepares requests before the timed Pool observation phase.
- Uses four caller threads against two child workers.
- Aggregates outcomes, queue wait, end-to-end latency, queue and active-worker
  high-water marks, restarts, and an RSS upper bound.
- Does not serialize case IDs, questions, descriptors, worker assignments, or
  per-request rows.

### Audit entry point

`scripts/audit_finqa_shadow_pool_replay_v1.py`

The audit verifies the E13 evidence chain, executes the real replay, runs seven
fault probes, evaluates 21 gate checks, and writes one immutable public
aggregate file.

## Deadline semantics

E14 has a response deadline, while E13 has a process execution timeout. They
solve different problems.

- E14 deadline: the caller stops waiting; a later Shadow result is discarded.
- E13 timeout: a non-responsive child process is terminated and restarted.

E14 does not claim that Python can safely kill an executing dispatcher thread
at the exact response deadline. The bounded E13 worker remains responsible for
containing the underlying process.

## Fault injection

| Probe | Required behavior | Result |
| --- | --- | --- |
| Queue saturation | Queue high-water mark never exceeds capacity | PASS |
| Overload | Newest request is rejected and E8 primary is unchanged | PASS |
| Queued deadline | Expired waiting request never reaches a Worker | PASS |
| Late completion | Executed late result is counted then discarded | PASS |
| Slot fault | One `WORKER_CRASH` does not prevent peer `MATCH` | PASS |
| Closed Pool | New work returns `POOL_CLOSED` | PASS |
| Resource cleanup | No dispatcher or child PID remains after close | PASS |

## Accepted local result

```text
selected / prepared                    128 / 117
attempted / admitted / completed       117 / 117 / 117
MATCH / DIVERGED                       74 / 43
backpressure / deadline / pool errors  0 / 0 / 0
worker restarts                        0
active worker high-water mark          2 / 2
queue high-water mark                  2 / 4
p50 / p95 / max queue wait             7.086 / 13.354 / 19.247 ms
p50 / p95 / max end-to-end             14.768 / 26.439 / 32.919 ms
timed observation throughput           243.251 requests/s
maximum individual worker peak RSS     90,230,784 bytes
two-worker RSS upper bound              180,293,632 bytes
model calls                            0
fault probes                           7 / 7
all gate checks                        21 / 21
```

The throughput timer covers only Pool observations after preparation and E8
primary decisions. It is not end-to-end RAG throughput.

## Verification

```text
E14 focused tests             12 passed
external-dataset regression   436 passed
full repository regression    2949 passed / 29 skipped / 3 warnings
compileall                    PASS
pip check                     CLEAN
public repository audit       1304 candidates / 0 findings
residual E14 Python processes 0
```

The three warnings are pre-existing SWIG deprecation warnings.

## Problems found and resolved

### Invalid test catalog digest

The first Pool test used a placeholder catalog hash. The existing catalog
validator rejected it before Pool execution. The fixture was corrected to use
the same canonical JSON and SHA-256 procedure as production code. The validator
was not weakened.

### Admission versus shutdown race

Initial review found that state inspection and queue insertion were separate.
`close()` could theoretically insert stop sentinels between them. Admission is
now performed while holding the state lock, giving shutdown and admission a
deterministic order.

### Concurrent shutdown deadlock

Final review found that two simultaneous `close()` calls could each enqueue a
full set of stop sentinels. After dispatchers consumed the first set and
exited, the second caller could block on a full queue with no remaining
consumer. Shutdown now has one owner; concurrent callers wait on the same
bounded completion event and receive the owner's result. A dedicated test
verifies two simultaneous close calls complete with an empty queue.

### Evidence regeneration after source cleanup

The first successful replay was treated as provisional. Unused imports and an
unclear hash expression were cleaned up, the provisional evidence was removed,
all focused tests were rerun, and the final evidence was generated from the
clean implementation. The final evidence binds the final source hashes.

## Public evidence

```text
docs/external_datasets/evidence/finqa_shadow_pool_replay_public_v1.json
SHA-256 98371c664d10bfafe21e57fd5a3104a12427fd9b91b1096b2a8285ec7af5008f
```

## Non-claims

- No answer-accuracy, retrieval-quality, or planner-realism improvement.
- No production availability or capacity-planning claim.
- No durable queue, distributed scheduler, network sandbox, CPU quota, or
  cgroup.
- No claim that executing work is killed exactly at the response deadline.
- No E11 serving promotion. E8 remains champion and Shadow remains default-off.

## Next evidence gap

E14 proves bounded concurrency but does not measure scaling efficiency. A new
versioned gate should compare the same prepared workload across 1, 2, and 4
workers, repeat trials, report confidence-aware throughput and latency, and
identify the memory/throughput saturation point before any capacity claim.
