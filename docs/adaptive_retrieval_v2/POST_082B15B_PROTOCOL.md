# Post-082b15b Adaptive Retrieval Protocol

## G0: Reproducibility Closure

- **Hypothesis:** The same local environment, exact request, and fixed per-question seed reproduce the assessor's structured proposal and recovery classification.
- **Cohort:** The 20-case WixQA ExpertWritten multi-document cohort, consumed development data only.
- **Arms:** Two identical diagnostic executions. No serving path is enabled.
- **Primary metric:** Exact equality of request hash, raw-output hash, parsed-proposal hash, and recovery classification for every assessor-evaluated baseline failure.
- **Gate:** All evaluated cases must match in both executions. This proves same-environment repeatability only.
- **Stop condition:** Any mismatch leaves `ADAPTIVE_RETRIEVAL_NOT_YET_JUSTIFIED` in place and blocks later claims.

## G1: Current Failure Attribution

- **Hypothesis:** The earliest-loss taxonomy identifies whether candidate acquisition, Top-5 selection, or later response construction dominates the frozen cohort.
- **Cohort:** Same 20-case consumed development cohort.
- **Primary metric:** Counts by earliest loss stage; no serving changes.
- **Gate:** 20 cases, zero unknown attribution rows, explicit top three failure categories.

## G2: Fair Retrieval-Budget Ablation

- **Hypothesis:** A bounded LLM addendum retry must beat a simple non-LLM same-budget retrieval baseline under the same final evidence budget of five documents to justify further work.
- **Cohort:** The 17 baseline failures from the consumed development cohort.
- **Arms:** `OFF5`, `DEPTH10`, `DEPTH20_RERANK5`, and seeded `ADAPTIVE_RETRY`; a same-query second chance is omitted because the current ranker is deterministic for the same query and index.
- **Primary metric:** Multi-document all-gold evidence completeness after a fixed final budget of five documents.
- **Continuation gate:** Adaptive retry has at least two recoveries not recovered by the best simple arm, strictly exceeds that arm on the primary metric, and creates no affected-case answer/citation regression.
- **Stop condition:** If adaptive retry is not better than the best simple arm, output `GLOBAL_ADAPTIVE_STOPPED`. No prompt tuning occurs on this cohort.
