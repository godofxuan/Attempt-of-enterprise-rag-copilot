# R2-S1 V5 Counterbalanced Arm-Order Design

## Status and scope

This design applies only to future local development and new live paired runs.
The frozen formal run `r2-s1-d7-test-20260718-01` remains an observational,
fixed OFF-then-ON run. V5 must not rerun, overwrite, migrate, or rewrite that
run or its public evidence package.

V5 changes measurement order, not the Guard. It does not modify the frozen
dataset, fixture labels, detector rules, detector thresholds, retrieval
budgets, model settings, or security metrics.

## Problem

The v1 live runner always executes Guard OFF before Guard ON for every case.
If model or process state changes with time, the measured difference may
contain an order effect in addition to the Guard effect. The v1 manifest and
per-case evidence also do not record execution order, so a reviewer cannot
audit that possible confounder from artifacts.

## Considered approaches

### 1. Independent hash parity

Use one bit of `sha256(case_id)` to choose OFF-then-ON or ON-then-OFF.

- Advantage: each assignment depends only on one case ID.
- Disadvantage: a finite suite may be materially imbalanced; 36 cases are not
  guaranteed to split 18/18.

### 2. Stable hash-rank alternation (selected)

Hash every case ID, sort by `(case_hash, case_id)`, and alternate the arm order
by zero-based hash rank.

- Even rank: OFF then ON.
- Odd rank: ON then OFF.
- Advantage: deterministic across machines and input iteration order, with an
  exact 50/50 split for even case counts and at most one-case difference for
  odd counts.
- Trade-off: assignment is stable for a fixed cohort; adding or removing cases
  may change ranks. The manifest therefore records the full cohort plan.

### 3. Run both AB and BA for every case

Execute OFF/ON and ON/OFF replicas for every case.

- Advantage: estimates order effects within each case.
- Disadvantage: doubles the already paired model work from two to four arms per
  case and requires a larger statistical and artifact schema change.

Approach 2 is the smallest protocol change that directly addresses the V5
review finding.

## Protocol contract

A new content-free `CounterbalancedArmOrderPlan` owns the future protocol:

- schema version and protocol ID;
- SHA-256 as the case-hash algorithm;
- hash-rank alternation as the allocation method;
- total case count and both order counts;
- one assignment per case containing `case_id`, `case_hash`, `hash_rank`, and
  `arm_order`.

The model is strict, frozen, and self-validating. Validation recomputes every
hash and rank, rejects duplicate or missing case IDs, verifies the parity rule,
and verifies the summary counts. A plan cannot merely claim to be balanced.

The plan builder accepts case IDs in any order and emits one canonical plan
sorted by `case_id`. The same fixed cohort therefore produces byte-equivalent
plan data on repeated runs.

## Runtime data flow

`evaluate_live_paired()` keeps its current no-plan path as the historical v1
compatibility behavior. When a counterbalanced plan is supplied:

1. Validate that the plan case set exactly equals the dataset case set.
2. For each dataset case, read that case's two-mode execution order.
3. Call `_evaluate_live_case()` in the assigned order.
4. Store each returned result in an OFF or ON lookup.
5. Reconstruct the existing OFF and ON result tuples in dataset order.
6. Reuse the existing pair-consistency, summaries, and security metrics.
7. Return `LivePairedResultV2`, which adds the immutable arm-order plan.

Separating execution order from result presentation is intentional. Existing
metric code compares aligned OFF and ON tuples; changing their storage order
would create unrelated compatibility risk.

## Artifact versioning

Historical classes remain strict v1 parsers:

- `LivePairedResult`
- `LiveSecurityRunManifest`
- v1 `per_case.jsonl` rows with exactly `security` and `live`

Future runs use additive v2 classes:

- `LivePairedResultV2`
- `LiveSecurityRunManifestV2`
- manifest mode `local_live_paired_counterbalanced`
- full `arm_order` plan in the manifest

The v2 writer keeps the same seven content artifacts, so immutability,
checksums, and content-free scanning remain unchanged. Its `per_case.jsonl`
rows are written as adjacent case pairs in actual execution order and add:

```json
{
  "arm_execution": {
    "protocol_id": "stable_case_hash_rank_counterbalanced_v1",
    "case_hash": "<sha256>",
    "hash_rank": 0,
    "arm_order": "off_then_on",
    "arm_position": 1
  },
  "security": {},
  "live": {}
}
```

The second row repeats the assignment with `arm_position: 2`. The row's live
and security `guard_mode` must equal the mode implied by the order and
position. Stage validation checks the manifest plan, pair adjacency, positions,
mode sequence, hashes, and artifact checksums.

The formal v1 public exporter remains pinned to the historical manifest hash
and v1 source schema. V5 does not migrate the public package.

## CLI behavior

New invocations of `scripts.eval_indirect_injection_live` build the stable
counterbalanced plan after frozen-data validation and before model evaluation.
There is no user switch that silently restores fixed OFF-first execution.
The canonical command remains sufficient because the exact protocol ID and
full assignments are stored in the manifest.

The CLI explicitly rejects the frozen formal run ID, even if a different output
directory is supplied. This converts the "do not rerun D7" instruction into an
enforced invariant rather than relying only on an existing directory.

## Error handling

The run fails before model work when:

- case IDs are empty or duplicated;
- a plan hash, rank, parity assignment, or summary count is inconsistent;
- the plan and dataset case sets differ;
- a v1 manifest is paired with a v2 result, or the reverse;
- a v2 manifest plan differs from the v2 result plan;
- per-case evidence order or arm position contradicts the manifest;
- the requested run ID equals the frozen formal D7 run ID.

No fallback chooses an order at runtime. Failing closed keeps provenance
explainable.

## Test strategy

RED tests must prove:

1. 36 case IDs produce exactly 18 OFF-then-ON and 18 ON-then-OFF assignments.
2. Reordering input case IDs does not change the canonical plan.
3. Odd case counts differ by at most one.
4. Duplicate IDs and tampered hashes/ranks/orders/counts are rejected.
5. The runner's actual call sequence follows each assignment while OFF/ON
   result tuples remain aligned by dataset order.
6. The no-plan path still serializes the exact v1 result shape.
7. A v2 manifest contains the full plan and v2 per-case rows contain auditable
   order and position evidence.
8. Tampered per-case order evidence is rejected.
9. The CLI defaults to v2 counterbalancing and refuses the formal D7 run ID.
10. The historical formal v1 manifest still parses and its SHA-256 remains
    unchanged.

After focused tests, run the security/evaluation/retrieval regressions, the full
repository suite, compileall, pip check, diff check, frozen hash verification,
both public-package verifier modes, and the public repository audit.

## Non-goals and claims

V5 reduces one known order confounder; it does not prove that all temporal,
cache, model-state, or carry-over effects are absent. It does not estimate a
causal Guard effect across models or unseen attacks. The correct historical
claim remains: D7 was one fixed OFF-first observational run. The correct future
claim is: new v2 runs use a deterministic cohort-counterbalanced order whose
assignments are recorded and validated.
