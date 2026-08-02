# FinQA Gate E14 Current Handoff

## Authoritative state

- Decision: `E14_BOUNDED_POOL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF`
- Protocol SHA: `c92c4e99a189620a70a5600433f1bc0e3e21e5338dd21bbbc7da3ec5bcf5272b`
- Public evidence SHA: `98371c664d10bfafe21e57fd5a3104a12427fd9b91b1096b2a8285ec7af5008f`
- Serving champion: `finqa_deterministic_descriptor_retriever_v5`
- Challenger: `finqa_top4_boundary_ranker_v1`
- Challenger mode: `SHADOW_DEFAULT_OFF`
- Internal cohort: `CONSUMED_NOT_ACCESSED`
- Frozen test: `UNTOUCHED`
- Production traffic: `NOT_RUN`
- Accepted delivery commit: `3e5ebb813668f01bb88227373062789abe3580eb`
- Remote CI: run `30736504721`, `SUCCESS`, Ubuntu/Windows/Linux container

## Completed

1. Frozen E14 protocol bound to exact E13 protocol and public evidence hashes.
2. Two eager E13 spawn workers behind a four-slot FIFO queue.
3. Bounded admission with `reject_newest` overload behavior.
4. Response deadline with queued cancellation and late-result discard.
5. Per-slot fault isolation and aggregate-only runtime metrics.
6. Admission/close race prevention under one state lock.
7. Single-owner idempotent shutdown with concurrent-close and residual PID
   checks.
8. Real 117-request concurrent replay and seven independent fault probes.
9. Immutable public evidence bound to four implementation file hashes.

## Accepted result

```text
prepared / selected             117 / 128
admitted / attempted            117 / 117
completed                       117 / 117
errors / deadline / restarts    0 / 0 / 0
active workers high-water       2 / 2
queue high-water                2 / 4
queue wait p95                  13.354 ms
end-to-end p95                  26.439 ms
observation throughput          243.251 requests/s
two-worker RSS upper bound      180,293,632 bytes
fault probes                    7 / 7
gate checks                     21 / 21
focused / external tests        12 / 436 passed
full repository                 2949 passed / 29 skipped
public repository audit         1304 candidates / 0 findings
```

These numbers cover local unlabeled Shadow observations after preparation.
They are not answer accuracy, end-to-end RAG throughput, or production SLOs.

## Immutable files

The public evidence binds these files. Any behavior change requires E14-v2 or
later evidence rather than overwriting E14-v1:

```text
app/external_datasets/finqa_shadow_pool_protocol_v1.py
app/external_datasets/finqa_shadow_pool_v1.py
app/external_datasets/finqa_shadow_pool_replay_v1.py
scripts/audit_finqa_shadow_pool_replay_v1.py
```

## Known limits

- No 1/2/4 worker scaling comparison or repeated-trial confidence interval.
- No production traffic, service integration, durable queue, or distributed
  metrics backend.
- Response deadline discards late results but does not kill an executing
  dispatcher thread at that exact instant.
- RSS is the sum of observed per-worker process peaks, not whole-service RSS.
- Gold program structure still bypasses planner realism.
- No new quality labels were consumed, so promotion remains unauthorized.

## Next action

Design E15 Capacity Envelope and Scaling Ablation before adding more runtime
machinery. Reuse one fixed prepared request set; compare 1, 2, and 4 workers
under caller concurrency 1, 4, and 8; repeat trials; report throughput,
queueing, tail latency, rejection rate, restarts, RSS, and scaling efficiency.
Keep E8 primary immutable and E11 default-off.

Delivery is complete: exact implementation commit `3e5ebb8` passed GitHub
Actions run `30736504721` in 9m41s, including the 2/2 Ubuntu/Windows matrix,
the 4m04s Linux container contract, and one artifact.

Recommended model: **5.6 Sol / Extra High**, because the next gate must separate
real scaling from warm-cache, startup, scheduler, and measurement artifacts.
