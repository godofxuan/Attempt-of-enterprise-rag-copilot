# Resume-safe Claims

This file is an allowlist, not a suggestion to use every sentence.

## Currently safe with exact qualifiers

1. Built a versioned enterprise RAG evaluation system covering retrieval, answer execution, citations, ACL leakage, and indirect prompt-injection regression, with immutable evidence hashes and exact Git revisions.
2. On a deterministic 100-case sample from the public FinQA test split using local Qwen3-8B and BGE-M3, measured 44% strict execution accuracy, 93.5% evidence recall, 79.4% citation precision, and 78.3% citation recall. This must say `100-case sample`; it must not say full FinQA accuracy or SOTA.
3. On a 36-pair custom synthetic indirect-injection suite, reduced user-visible attack success from 12.5% (3/24) with Guard OFF to 0% (0/24) with Guard ON, with 0/32 benign quarantines. This must say `custom synthetic` and must not be described as an external benchmark.
4. Established a company-disjoint 101-case FinanceBench page-localization baseline: Document Recall@5 95.0%, but exact Page Hit@5 only 30.7%, identifying page localization rather than company-document recall as the main retrieval bottleneck. This is a diagnosis, not an improvement claim.

## Not yet safe

- No FinanceBench `baseline to improved` claim exists yet.
- No external prompt-injection benchmark claim exists yet.
- No cross-encoder quality/latency claim exists yet.
- No full FinQA test-set result exists.
- No production reliability, SOTA, cross-domain, or cross-model generalization claim exists.
- Synthetic 100% results must never be presented without the word `synthetic`.

## Promotion rule

A new resume number may enter the allowlist only after its row exists in `metrics.csv`, its protocol and decision rule were frozen before final evaluation, its artifacts have hashes, and `RAG_RESUME_METRICS.md` documents limitations.
