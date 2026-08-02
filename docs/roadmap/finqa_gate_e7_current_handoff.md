# FinQA Gate E7 Current Handoff

## Completed

- Question-only deterministic role-query planners v1/v2.
- Pinned `qwen3:8b` free-query planner calibration.
- Guarded, value-free safe descriptor catalog v1 and contextual v2.
- Write-once Oracle catalog upper-bound v1/v2 lineage.
- Strict enum-only local descriptor selector and real-model calibration.
- Deterministic retrievers v1/v2, pinned BGE-M3 hybrid v3, and typed structural v4.
- Frozen protocol before every full calibration.
- Failure taxonomy and public implementation-hash verification.

## Current decisions

```text
catalog v2 Oracle capacity: PASSED
all real question-only selectors/retrievers: FAILED
best Recall@4 / complete@8: normalized lexical v2
best Recall@8: typed structural v4
serving route: DISABLED
internal validation: NOT_RUN
frozen test: UNTOUCHED
```

## Best measured development results

```text
v2 Recall@4       70.73%
v2 Recall@8       78.86%
v2 complete@8     75.86%
v2 mean latency    1.25 ms

v4 Recall@4       69.11%
v4 Recall@8       80.49%
v4 complete@8     75.86%
v4 mean latency    2.63 ms
```

Neither result passes the frozen `85% / 95% / 90%` gate.

## Next allowed gate

Create E8 as a data-contract and host-ranking gate, not another weight/model
sweep:

1. freeze descriptor-level and candidate-level metrics separately;
2. add balanced context/table-topic fields with Guard and prompt budgets;
3. prove catalog identity, ordering and no-value leakage;
4. implement descriptor-aware candidate ranking for period/group expansions;
5. compare against frozen v2 and v4 on the same 60 cases;
6. keep internal validation and frozen test untouched until development passes.

## Primary files

```text
app/external_datasets/finqa_safe_descriptor_catalog_v1.py
app/external_datasets/finqa_safe_descriptor_catalog_v2.py
app/external_datasets/finqa_descriptor_selector_v1.py
app/external_datasets/finqa_descriptor_retriever_v1.py
app/external_datasets/finqa_descriptor_retriever_v2.py
app/external_datasets/finqa_descriptor_retriever_v3.py
app/external_datasets/finqa_descriptor_retriever_v4.py
scripts/audit_finqa_descriptor_retriever_v1.py
scripts/audit_finqa_descriptor_retriever_v2.py
scripts/audit_finqa_descriptor_retriever_v3.py
scripts/audit_finqa_descriptor_retriever_v4.py
scripts/diagnose_finqa_descriptor_retriever_v1.py
docs/external_datasets/finqa_descriptor_catalog_gate_e7.md
docs/learning/28_FINQA_GATE_E7_SAFE_DESCRIPTOR_SELECTION.md
```

