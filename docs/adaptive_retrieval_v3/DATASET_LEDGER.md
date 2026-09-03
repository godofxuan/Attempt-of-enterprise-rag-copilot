# Adaptive Retrieval V3 Dataset Ledger

This ledger records what the repository evidence establishes at V3 G0. A label
of `UNKNOWN` is intentionally not upgraded to fresh validation without a
history and artifact audit.

| Dataset / cohort | N | Labels | S3 / S4 / S5 / G1 use | Prompt, router, or threshold tuning | V3 status | V3 use |
|---|---:|---|---|---|---|---|
| WixQA Synthetic | 6,221 | Gold article IDs and answers | No repository S3/S4/S5/G1 use | Historical development use exists | CONSUMED_DEVELOPMENT | Not a V3 confirmation set. |
| WixQA Simulated | 200 | Gold article IDs and answers | S3 historical BGE reranker; no S4/S5/G1 | Historical profile selection | CONSUMED_DEVELOPMENT | Not a V3 confirmation set. |
| WixQA ExpertWritten | 200 | Gold article IDs and answers | S3 BGE, S0-S4 bake-off, S5 20-case diagnostic, G1 assessor | V3: no label-driven prompt, router, or threshold tuning; it is still consumed by all historical decisions | CONSUMED_DEVELOPMENT | F1-F6 retrospective analysis only. |
| WixQA ExpertWritten multi-document subset | 20 / 17 failures | Multiple gold article IDs; completeness | No S3; indirect S4 whole-cohort exposure; S5 | Old addendum prompt frozen; no V3 tuning | CONSUMED_DEVELOPMENT | Regression and historical mechanism comparison only. |
| FinanceBench | Repository contains page-retrieval experiments | Finance document/page labels | No V3 mechanism use established | Existing dev/retrospective experiments; per-question history incomplete | UNKNOWN | Not selected until a per-question consumption audit. |
| FinQA | Numeric answer/program labels | No V3 mechanism use | Existing development/calibration work | CONSUMED_DEVELOPMENT | Different table/numeric task; not direct V3 retrieval comparison. |
| EnterpriseRAG-Bench | Corpus/indexing benchmark; V3 QA suitability unverified | No V3 mechanism use | No compatible question-label protocol established | UNKNOWN | Not selected until protocol and history are audited. |
| UDA finance page evaluation | Page labels; known-report route | No V3 mechanism use | R4/R5 candidate selection and confirmation already consumed labels | CONSUMED_DEVELOPMENT | Not a direct V3 comparison without a separate protocol. |

## G0 Fresh-validation Conclusion

No currently verified V3-compatible fresh confirmation cohort is available.
The immediately available WixQA variants have historical usage. G7 therefore
must not claim fresh validation until a candidate cohort passes a per-question
history/label-consumption audit and is frozen before V3 results are viewed.
