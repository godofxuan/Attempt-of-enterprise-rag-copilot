# FinQA Gate E6 Current Handoff

## Completed

- E6-v1 global-shortlist diagnosis.
- E6-v2 full Guard-admitted operand pool and per-role Top-8 matrix.
- Source-bound controlled-constant Decimal compiler.
- Five-step/eight-role semantic program contract.
- Capability fallback routing and role-exact candidate parser.
- Write-once E6-v2 v1-v4 audit lineage and authoritative v4 selector.
- E6-v3 bounded `role_query` / `expected_period` schema.
- E6-v3 role-conditioned compatibility implementation.
- Recomputable E6-v3 offline upper-bound public evidence.

## Current decisions

```text
E6-v2: INPUT_GATE_FAILED
E6-v3 offline upper bound: UPPER_BOUND_INPUT_GATE_PASSED
typed serving route: DISABLED
internal validation: NOT_RUN
frozen test: UNTOUCHED
```

Authoritative E6-v2 v4:

```text
source recall       100.00%
role recall@4        67.48%
role recall@8        83.74%
complete case@8      77.59%
route accuracy      100.00%
edge reduction       73.44%
```

E6-v3 gold-descriptor upper bound:

```text
role recall@4        98.37%
role recall@8        99.19%
complete case@8      98.28%
edge reduction       73.63%
model calls               0
```

## Next allowed gate

Freeze a real-model planner experiment. The planner may read the user question
and approved structural demonstrations, but not gold program, answer, case ID,
gold evidence IDs or candidate IDs while creating role queries.

Required paired outputs:

- role-query schema validity;
- explicit-period accuracy;
- generated-query candidate recall@4/@8;
- complete binding rate;
- strict and grounded final-answer accuracy;
- B0 fixes and correct-to-wrong regressions;
- model-call and latency cost;
- zero identity/provenance mutation.

Do not consume internal validation or frozen test until the generated-query
development gate passes.

## Primary files

```text
app/external_datasets/finqa_controlled_program.py
app/external_datasets/finqa_semantic_program_v2.py
app/external_datasets/finqa_role_compatibility_v2.py
app/external_datasets/finqa_semantic_program_v3.py
app/external_datasets/finqa_role_compatibility_v3.py
scripts/audit_finqa_role_compatibility_v2.py
scripts/diagnose_finqa_role_compatibility_v2.py
scripts/diagnose_finqa_role_compatibility_v3_upper_bound.py
docs/external_datasets/finqa_role_compatibility_gate_e6.md
docs/learning/27_FINQA_GATE_E6_ROLE_COMPATIBILITY.md
```
