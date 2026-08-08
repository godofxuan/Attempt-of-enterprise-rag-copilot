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
| WixQA Synthetic | DEVELOPMENT; 6,221-case B0/B1/B2 baseline consumed at `2347346` | failure analysis and candidate development only |
| WixQA Simulated | VALIDATION; 200-case baseline observed at `2347346` | no longer an untouched candidate holdout |
| WixQA ExpertWritten | FIXED_CONSUMED; 200-case B0/B1/B2 baseline observed once at `2347346` | reporting and preregistered missing baseline arms only; never tune |
| EnterpriseRAG-Bench official questions | FIXED_CONSUMED; public labels and `qst_0413` anomaly inspected before B0 | fixed baseline/reporting only; no parameter or candidate selection |
| HERB official tasks | UNTOUCHED | remain untouched until license/resource qualification passes |

The legacy `DEVELOPMENT_CONSUMED` phrase is retained to describe old records; new
experiments must use only the five formal statuses plus `PIPELINE_DEBUG`.
Moving a cohort forward is append-only. It never moves from consumed back to
untouched.
