# Resume-safe Claims

This file is an allowlist, not a suggestion to use every sentence.

## Currently safe with exact qualifiers

1. Built a versioned enterprise RAG evaluation system covering retrieval, answer execution, citations, ACL leakage, and indirect prompt-injection regression, with immutable evidence hashes and exact Git revisions.
2. On a deterministic 100-case sample from the public FinQA test split using local Qwen3-8B and BGE-M3, measured 44% strict execution accuracy, 93.5% evidence recall, 79.4% citation precision, and 78.3% citation recall. This must say `100-case sample`; it must not say full FinQA accuracy or SOTA.
3. On a 36-pair custom synthetic indirect-injection suite, reduced user-visible attack success from 12.5% (3/24) with Guard OFF to 0% (0/24) with Guard ON, with 0/32 benign quarantines. This must say `custom synthetic` and must not be described as an external benchmark.
4. Established a company-disjoint 101-case FinanceBench page-localization baseline: Document Recall@5 95.0%, but exact Page Hit@5 only 30.7%, identifying page localization rather than company-document recall as the main retrieval bottleneck. This is a diagnosis, not an improvement claim.

5. On a frozen 12-attack combination-disjoint subset of NVIDIA garak's `LatentInjectionReport` probe using local Qwen3-8B, reduced ASR from 4/12 (33.3%) Guard OFF to 0/12 Guard ON and model context exposure from 12/12 to 0/12, with 1.42 ms mean Guard latency. This must say `one probe subset` and `12 attacks`.

Supporting reliability evidence, not an external quality metric: 30/30 FTS
hard-process-termination trials resumed without corruption, unrecoverable stale
locks or manual intervention; 12/12 active-pointer process-exit trials resolved
to a verified old or new snapshot. Always add that power-loss testing was
`NOT_RUN`.
6. On a preregistered, company-disjoint fixed 96-question subset of the external UDA-QA FinHybrid benchmark, BGE-M3 Dense retrieval reached 74.0% Page Hit@5, 61.3% nDCG@5, and 222.9 ms p95 latency when retrieving pages within the known financial report. This must say `within the known report`; it is not document discovery or answer accuracy.
7. As additional non-blind stress evidence, on 48 recombined attacks from one pinned NVIDIA garak retrieved-report probe, the unchanged current Guard reduced ASR from 12/48 to 0/48 and prevented attack context from reaching the model in 48/48 cases; benign quarantine was 0/4 and mean Guard scan was 1.88 ms. This must say `recombined stress fixture`, `one probe`, and `not a new blind holdout`; the 12-attack combination-disjoint result remains the primary resume claim.

## Not yet safe

- No FinanceBench `baseline to improved` claim exists yet.
- No full-garak or probe-family-disjoint security claim exists.
- The cross-encoder is a development negative result, not a quality improvement.
- No full FinQA test-set result exists.
- No production reliability, SOTA, cross-domain, or cross-model generalization claim exists.
- Synthetic 100% results must never be presented without the word `synthetic`.
- The UDA 96-case test is consumed and cannot be retuned or presented as hidden/blind.

## Promotion rule

A new resume number may enter the allowlist only after its row exists in `metrics.csv`, its protocol and decision rule were frozen before final evaluation, its artifacts have hashes, and `RAG_RESUME_METRICS.md` documents limitations.
