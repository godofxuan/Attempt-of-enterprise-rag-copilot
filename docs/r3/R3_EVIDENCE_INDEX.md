# R3 Evidence Index

## Reading order

1. [Accepted baseline](R3_BASELINE.md)
2. [Execution and promotion rules](R3_EXECUTION_PLAN.md)
3. [Unused-company cohort](R3_UDA_COHORT.md)
4. [Answer and citation experiment](R3_ANSWER_EVAL.md)
5. [Security stress experiment](R3_SECURITY_EVAL.md)
6. [Final decision](R3_FINAL_REPORT.md)
7. [Engineering journal](R3_ENGINEERING_JOURNAL.md)
8. [Offline demo](R3_DEMO_RUNBOOK.md)

## Public machine-readable evidence

| Artifact | Purpose | Final status |
|---|---|---|
| `evidence/uda_finance_r3_protocol_v1.json` | cohort, split and access-policy freeze | `FROZEN` |
| `evidence/uda_finance_r3_page_protocol_v1.json` | page candidate metrics and promotion gates | `FROZEN` |
| `evidence/uda_finance_r3_page_dev_v1.json` | Dense/page-max development comparison | `OBSERVED_DEVELOPMENT` |
| `evidence/uda_finance_r3_page_validation_v1.json` | one-shot validation decision | `VALIDATION_REJECTED` |
| `evidence/uda_finance_r3_answer_protocol_v1.json` | answer/citation scoring and runtime contract | `FROZEN` |
| `evidence/uda_finance_r3_answer_dev_v1.json` | direct/typed paired development result | `NEGATIVE_DEVELOPMENT` |
| `evidence/garak_latent_report_expanded_v1.json` | Guard OFF/ON expanded stress summary | `OBSERVED_STRESS_NOT_BLIND` |

Public evidence contains aggregate results and immutable bindings only. Raw
licensed documents, labels, detailed model outputs, access markers and local
indexes remain under `.private/` and are excluded from Git.

## Private immutable bindings

| Experiment | Private manifest SHA-256 |
|---|---|
| R3 page validation | `3bce998a2eebc4e508fcd7e25ab7b87d5f014746853fa259ecea3b51b66c89c6` |
| R3 answer campaign | `4f5d7fbfdabd344a9545cad2c5ee0a7e3abb5e396d7692a7e326d00b7e8d6437` |
| Numeric candidate oracle | `25c24907dbe5d006fa96d28c75bfa68a72ccdf547865d320442ca36d1c12403e` |
| Expanded Guard stress | `51bbde877258f3105c73b13d80da93414e7783f2a3f62ec518639299c7b4b57f` |

These hashes allow a local reviewer to verify the exact private run without
publishing raw evaluation material.

## Reproduction

The public, model-free summary is intentionally fast:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.r3_evidence_tour
```

It reads committed evidence and prints decisions. It does not rerun retrieval
or model inference and therefore is suitable for an interview walkthrough.
Live commands and model/runtime requirements are recorded in the experiment
documents and `docs/resume_metrics/EXPERIMENT_REGISTRY.md`.

## Claim boundary

- The UDA page candidate and typed answer candidate are negative results.
- The 48-attack security result is a recombined stress fixture, not a new blind
  external holdout.
- The smaller 12-attack combination-disjoint holdout remains the stronger
  resume security claim.
- Independent double-human answer review remains `NOT_RUN`.
