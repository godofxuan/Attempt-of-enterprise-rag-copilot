# FinQA Gate E15: Local Capacity Envelope and Scaling Ablation

## Decision

`E15_LOCAL_CAPACITY_ENVELOPE_SUPPORTED_SHADOW_REMAINS_DEFAULT_OFF`

E15 measures the E14 worker Pool under a pre-registered local scaling matrix.
It does not promote the E11 challenger, change the E8 primary result, consume a
new quality cohort, or establish a production SLO.

## Question and design

E14 showed that one `2 worker / 4 caller` configuration was bounded and stable.
It could not show whether extra workers increased throughput, where caller
concurrency stopped helping, or how memory grew. E15 freezes these controls
before implementation:

| Control | Frozen value |
| --- | --- |
| Worker processes | `1, 2, 4` |
| Caller concurrency | `1, 4, 8` |
| Repetitions per configuration | `3` |
| Total trials | `27` |
| Workload | same 117 prepared E13-selected requests in every trial |
| Queue capacity | `8` |
| Admission timeout | `0.5 s` |
| Response deadline | `2.0 s` |
| Shutdown grace | `20.0 s` |
| Pool lifecycle | fresh process Pool per trial, reused within trial |
| Timed boundary | Pool observations only; setup and preparation excluded |

Trial order is counterbalanced: ascending, reversed, then ascending rotated
left by three configurations. This reduces, but does not eliminate, systematic
warm-cache, thermal, and scheduler bias.

## Frozen evidence chain

```text
E15 protocol SHA-256
f201ecd767299a249fb3702489c395341f7c02a4500026d5aa419c6109ec1285

source E14 protocol SHA-256
c92c4e99a189620a70a5600433f1bc0e3e21e5338dd21bbbc7da3ec5bcf5272b

source E14 public evidence SHA-256
98371c664d10bfafe21e57fd5a3104a12427fd9b91b1096b2a8285ec7af5008f
```

The E14 evidence transitively binds the E13 official-train revision,
deterministic selection, label projection, E8 primary, E11 worker protocol,
and bounded Pool runtime. The internal cohort remains consumed and unaccessed;
the frozen test remains untouched.

## Code map

### Protocol

`app/external_datasets/finqa_shadow_capacity_protocol_v1.py`

Strict frozen Pydantic models reject matrix, comparison, output-boundary, or
unknown-field drift. The JSON protocol lives at
`docs/external_datasets/evidence/finqa_shadow_capacity_protocol_v1.json`.

### Capacity runner and aggregation

`app/external_datasets/finqa_shadow_capacity_v1.py`

- `prepare_finqa_shadow_capacity_workload_v1()` selects and prepares once.
- `capacity_trial_schedule_v1()` produces the exact 27-row order.
- `run_finqa_shadow_capacity_trial_v1()` starts one fresh E14 Pool, starts the
  timer after process startup, submits the fixed workload, closes the Pool,
  and checks residual dispatcher/PID counts.
- `aggregate_finqa_shadow_capacity_trials_v1()` validates exact row order,
  computes per-configuration medians/spreads, scaling comparisons, and a
  deterministic local recommendation.
- `evaluate_finqa_shadow_capacity_gates_v1()` evaluates the frozen gates.

### Audit

`scripts/audit_finqa_shadow_capacity_v1.py` verifies upstream hashes, executes
the real 27-trial experiment, prints one line per completed trial, and writes
canonical aggregate evidence. A different existing output is never
overwritten.

## Pre-registered comparisons

The protocol did not search all pairs after seeing the results. It froze two
comparisons in advance:

| Comparison | Minimum speedup | Minimum efficiency | Observed speedup | Observed efficiency |
| --- | ---: | ---: | ---: | ---: |
| `1 -> 2 workers @ 4 callers` | `1.25x` | `0.625` | `2.075x` | `1.038` |
| `1 -> 4 workers @ 8 callers` | `1.75x` | `0.4375` | `3.441x` | `0.860` |

Efficiency is `speedup / worker ratio`. The observed first value is slightly
above one. It must not be interpreted as a super-linear algorithmic guarantee;
short-task scheduling, cache state, and host noise can produce this local
measurement.

## Real local result

| Config | Median throughput req/s | Relative spread | Median E2E p95 ms | Maximum RSS upper MiB |
| --- | ---: | ---: | ---: | ---: |
| `w1-c1` | `163.374` | `1.57%` | `12.824` | `87.11` |
| `w1-c4` | `158.300` | `6.11%` | `35.822` | `87.18` |
| `w1-c8` | `160.752` | `5.45%` | `65.210` | `87.23` |
| `w2-c1` | `165.896` | `0.98%` | `12.662` | `173.10` |
| `w2-c4` | `328.517` | `3.99%` | `20.626` | `172.95` |
| `w2-c8` | `320.426` | `8.37%` | `33.729` | `172.89` |
| `w4-c1` | `161.350` | `5.40%` | `12.944` | `344.38` |
| `w4-c4` | `631.169` | `9.16%` | `14.802` | `344.47` |
| `w4-c8` | `553.185` | `3.49%` | `24.153` | `344.27` |

Across 3,159 request observations, all 3,159 completed. Backpressure,
deadline, worker-error, restart, late-discard, and residual-process counts were
zero. The maximum trial p95 was `69.598 ms`; maximum four-worker RSS upper
bound was `361,205,760 bytes`. All 22 gates passed.

The deterministic local recommendation is `w4-c4`: it has the highest median
throughput among failure-free configurations under the frozen latency and RSS
bounds. `w4-c8` is slower, showing that caller concurrency above executable
worker parallelism adds queueing and scheduling cost for this workload.

## Measurement semantics

The numerator is the number of returned E11 Shadow observations. The timer
starts only after the process Pool has started and the workload has already
been parsed, guarded, converted to a typed catalog, and passed through the E8
primary selector. Therefore `631.169 req/s` means local post-primary Shadow
observation throughput. It is not API QPS, document-ingestion throughput,
retrieval throughput, answer-generation throughput, or complete RAG QPS.

The RSS number sums the maximum observed RSS for each child slot. It is a
conservative child-pool upper bound, not whole-service peak memory and not a
simultaneous sampled total.

## Problems and decisions

### E14 protocol could not represent one worker

E14 correctly constrained its own accepted Pool contract to at least two
workers. Weakening that historical validator would invalidate E14 evidence.
E15 therefore introduced a new protocol schema while reusing the immutable E14
runtime implementation.

### Setup could distort scaling

Starting 1, 2, and 4 Windows `spawn` workers has different cost. Mixing startup
into each short trial would mostly benchmark process creation. E15 excludes
startup from the observation timer, uses a fresh Pool for isolation, and
states explicitly that cold-start latency is not measured.

### Trial order could favor later configurations

Running all small configurations first and all large configurations last could
confound worker count with cache or host state. The exact counterbalanced order
is protocol-bound and the aggregator rejects missing or reordered rows.

### Quiet preparation period

The audit emits progress after the one-time preparation has completed, so the
first visible trial line can be delayed. The run took about 100 seconds on the
accepted Windows host and then printed all trial summaries. This was CPU/local
data processing, not an Ollama call or a stuck background process.

### Formatting tools unavailable

The virtual environment contains neither Ruff nor Black. No unrecorded package
was installed. Verification uses repository CI's actual contracts: compileall,
focused and full pytest, dependency consistency, and public-repository audit.

## Public evidence

```text
docs/external_datasets/evidence/finqa_shadow_capacity_public_v1.json
SHA-256 5e299683c2fd6fa0ad520fc2264ccc06b68dfe214e0c16b34b065f28e9bfc82f
```

The evidence persists only trial/configuration aggregates. It excludes request
text, values, case/company/descriptor/candidate/evidence/source IDs,
provenance, ranking scores, per-request latency/outcome, and worker assignment.

## Local verification

```text
E15 focused tests             10 passed
external-dataset regression   446 passed
full repository regression    2959 passed / 29 skipped / 3 warnings
compileall                    PASS
pip check                     CLEAN
frozen evaluation hash        UNCHANGED
quality-review packet         VERIFIED / NOT_RUN
expanded corpus quality       PASS
public repository audit       1315 candidates / 0 findings
```

The three warnings are pre-existing SWIG deprecation warnings. Remote
exact-commit GitHub Actions evidence is pending at this local closeout point.

## Non-claims and next gate

- No answer quality, planner realism, or retrieval improvement.
- No end-to-end RAG QPS, production traffic, capacity plan, or SLO.
- No cold-start, autoscaling, distributed scheduling, or durable queue claim.
- No serving promotion; E8 remains champion and E11 remains default-off.

The next admissible step is service-level dark integration with default-off
sampling, aggregate telemetry, explicit runtime budgets, and rollback. It must
not call the local capacity result a production deployment.
