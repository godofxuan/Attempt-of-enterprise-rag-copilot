# Adaptive Retrieval V3 Dataset Ledger

This ledger records what the repository evidence establishes at V3 G0. A label
of `UNKNOWN` is intentionally not upgraded to fresh validation without a
history and artifact audit.

| Dataset / cohort | N | Task / gold labels | Used in S3? | Used in S4? | Used in S5? | Used for tuning? | V3 status | V3 use |
|---|---:|---|---|---|---|---|---|---|
| WixQA Synthetic | 6,221 | Support-article QA; gold article IDs and answers | No repository S3 evidence | No | No | Historical development use exists | CONSUMED_DEVELOPMENT | Not a V3 confirmation set. |
| WixQA Simulated | 200 | Support-article QA; gold article IDs and answers | Yes, historical BGE reranker evidence | No | No | Historical profile selection | CONSUMED_DEVELOPMENT | Not a V3 confirmation set. |
| WixQA ExpertWritten | 200 | Support-article QA; gold article IDs and answers | Yes, historical BGE evidence | Yes, S0-S4 bake-off | Yes, 20-case/17-failure adaptive diagnostic | V3 may use for diagnosis only; no label-driven prompt tuning | CONSUMED_DEVELOPMENT | G1-G6 retrospective analysis only. |
| WixQA ExpertWritten multi-document subset | 20 / 17 failures | Multiple gold article IDs; retrieval completeness | No | Indirectly via S4 whole cohort | Yes | Old addendum prompt is frozen; no V3 tuning | CONSUMED_DEVELOPMENT | Regression and historical mechanism comparison only. |
| FinanceBench | Repository evidence contains page-retrieval experiments | Finance-document/page labels; separate harness | No | No | No | Existing dev/retrospective experiments | UNKNOWN | Not selected until per-question consumption is audited. |
| FinQA | Repository evidence contains table/numeric experiments | Numeric answer/program labels; different task/harness | No | No | No | Existing development/calibration work | CONSUMED_DEVELOPMENT | Not a direct V3 retrieval comparison. |
| EnterpriseRAG-Bench | Repository evidence contains index-capacity evidence | Corpus/indexing benchmark; V3 question-label suitability unverified | No | No | No | Not applicable | UNKNOWN | Not selected until a compatible QA protocol exists. |
| UDA finance page evaluation | Repository evidence contains company-disjoint page localization | Page labels; specialized known-report route | No | No | No | Existing R4/R5 selections | CONSUMED_DEVELOPMENT | Not a direct V3 comparison without a separate protocol. |

## G0 Fresh-validation Conclusion

No currently verified V3-compatible fresh confirmation cohort is available.
The immediately available WixQA variants have historical usage. G7 therefore
must not claim fresh validation until a candidate cohort passes a per-question
history/label-consumption audit and is frozen before V3 results are viewed.
