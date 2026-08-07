# RAG Resume Metrics

## Three safest numbers

### 1. External retrieved-content injection defense

Safe wording:

> On a frozen 12-attack combination-disjoint subset of NVIDIA garak's
> `LatentInjectionReport` probe with local Qwen3-8B, reduced attack success from
> 33.3% (4/12) with Guard OFF to 0% (0/12) with Guard ON; blocked model exposure
> from 12/12 to 0/12 with 1.42 ms mean deterministic Guard latency.

Required qualifiers: one probe subset, 12 attacks, combination-disjoint, local
Qwen3-8B. Do not call this full garak accuracy.

### 2. External FinQA end-to-end evaluation

Safe wording:

> Built a deterministic answer/citation evaluator and measured 44% strict
> execution accuracy, 93.5% evidence recall, 79.4% citation precision, and 78.3%
> citation recall on a fixed 100-case sample from the public FinQA test split.

Required qualifiers: fixed 100-case sample, not full 1,147-case FinQA, not SOTA,
local Qwen3-8B/BGE-M3.

### 3. FinanceBench bottleneck diagnosis

Safe wording:

> Established a company-disjoint 101-case FinanceBench baseline with 95.0%
> Document Recall@5 but 30.7% Page Hit@5, then used a typed 49-case development
> failure analysis to identify page ranking and multi-page localization as the
> dominant retrieval bottlenecks.

This is a diagnosis and evaluation-system claim, not a quality improvement.

## Optional engineering bullet

> Implemented evidence-hashed experiment manifests, fixed model/dataset
> revisions, Guard-only paired evaluation, deterministic ranking metrics, and
> negative-result gates that prevented a 4.63x-p95 cross-encoder configuration
> from being promoted without nDCG gain.

The 4.63x comparison is development-only and should be described that way.

## Numbers forbidden on a resume

- `53.06% adaptive retrieval`: hindsight oracle union, not an executable policy.
- `46.94% Cross-Encoder vs 30.69% baseline`: values come from different splits.
- `0% benign FPR`: the external holdout denominator is only 2; say `0/2`.
- `100% security`: only one retrieved-report probe subset was tested.
- `100% RAG accuracy`: the perfect enterprise-corpus result is synthetic.
- `52% FinQA accuracy`: this is oracle-evidence strict accuracy, not end-to-end.
- Full FinQA, full FinanceBench blind-test, SOTA, production reliability, or
  cross-model generalization claims.
- Claim-level unsupported-claim rate, citation coverage, refusal precision, or
  refusal recall: these were not measured in the frozen end-to-end artifact.

## Evidence chain

- FinanceBench baseline: `BASELINE.md`, ranking artifact SHA-256
  `99617386a2d8728356db2821c8a7a05bc4f10a1c289cfd56b6809c761c321593`.
- FinQA: `docs/external_datasets/evidence/finqa_test_holdout_v1.json`, SHA-256
  `525c93a2f9437a5880fbed68e536fb351414ca0c50c8736951aa0474b744bb56`.
- garak holdout: `evidence/garak_latent_report_holdout_v1.json` and fixture
  SHA-256 `babd8bd8e52f3b8d63bffcb526de426af550ad1f791eaddb7431d0a6b314643c`.
