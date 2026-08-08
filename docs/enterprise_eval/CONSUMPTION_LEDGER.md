# Data Consumption Ledger

Allowed status vocabulary:

- `UNTOUCHED`: labels/results have not been used for any decision.
- `DEVELOPMENT`: may be inspected and used for candidate construction.
- `VALIDATION`: fixed once; may select or reject a preregistered candidate.
- `FIXED_CONSUMED`: fixed external/final labels have been evaluated and cannot
  be used for further tuning.
- `REGRESSION_ONLY`: may verify compatibility but cannot support new quality
  selection.
- `PIPELINE_DEBUG`: no formal quality claim; only adapter/index execution.

| Dataset / cohort | Status at E0 | Permitted next use |
|---|---|---|
| FinanceBench 49-case development | DEVELOPMENT_CONSUMED (legacy) | failure analysis and reproducibility only |
| FinanceBench 101-case historical fixed test | FIXED_CONSUMED | regression/reporting only |
| UDA 64-case v1 development | DEVELOPMENT_CONSUMED (legacy) | reproducibility only |
| UDA 96-case fixed test | FIXED_CONSUMED | reporting only |
| UDA R3 development/validation cohorts | FIXED_CONSUMED under their protocols | reporting and frozen candidate audit only |
| FinQA fixed 100-case end-to-end sample | FIXED_CONSUMED | reporting/regression only |
| FinQA disclosed development/calibration cohorts | DEVELOPMENT_CONSUMED (legacy) | retrospective diagnostics only |
| FinQA 40-case E11 internal cohort | FIXED_CONSUMED | shadow/regression only |
| Synthetic enterprise corpus dev/test | DEVELOPMENT / REGRESSION_ONLY per v2 manifests | system contract regression, not external claims |
| garak initial, holdout, and recombined stress fixtures | FIXED_CONSUMED | Guard regression only |
| WixQA Synthetic | UNTOUCHED; assigned DEVELOPMENT before download | development after manifest verification |
| WixQA Simulated | UNTOUCHED; assigned VALIDATION before download | one fixed candidate decision |
| WixQA ExpertWritten | UNTOUCHED | one fixed external evaluation after protocol freeze |
| EnterpriseRAG-Bench official questions | UNTOUCHED | remain untouched until capacity and protocol gates pass |
| HERB official tasks | UNTOUCHED | remain untouched until license/resource qualification passes |

The legacy `DEVELOPMENT_CONSUMED` phrase is retained to describe old records; new
experiments must use only the five formal statuses plus `PIPELINE_DEBUG`.
Moving a cohort forward is append-only. It never moves from consumed back to
untouched.

