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

### 2. External WixQA enterprise-support retrieval

Safe wording:

> On WixQA ExpertWritten's 200 authentic anonymized support questions, compared
> BM25, BGE-M3 Dense, and equal-weight RRF; Dense improved Article Recall@5 from
> 42.75% to 66.42% and nDCG@5 from 32.15% to 52.16%, with p95 latency increasing
> from 151.8 ms to 157.4 ms.

Required qualifiers: fixed public-label 200-question cohort, retrieval only,
not answer accuracy, not a hidden/blind holdout.

### 3. Full-corpus heterogeneous enterprise retrieval engineering

Safe wording:

> Replaced an estimated 36.60 GiB in-memory lexical design with a resumable,
> atomically activated SQLite FTS5 index over all 511,962 EnterpriseRAG-Bench
> rows; built a verified 1.37 GiB artifact in 231.35 seconds at about 1.83 GiB
> peak memory and measured a 60.37% document Recall@5 full-corpus B0 baseline.

Required qualifiers: synthetic-company heterogeneous corpus, full lexical B0,
470 document-grounded questions, not answer accuracy; Dense/RRF/Agent remain
`NOT_RUN` on this corpus.

## Optional engineering bullet

> Implemented evidence-hashed experiment manifests, fixed model/dataset
> revisions, Guard-only paired evaluation, deterministic ranking metrics, and
> negative-result gates that prevented a 4.63x-p95 cross-encoder configuration
> from being promoted without nDCG gain.

The 4.63x comparison is development-only and should be described that way.

Additional engineering evidence, not a replacement for the first resume
number: the unchanged current Guard was stress-reproduced on 48 recombined
attacks from the same pinned garak probe, with ASR `12/48 -> 0/48`, context
exposure `48/48 -> 0/48`, benign quarantine `0/4`, and mean Guard scan `1.88
ms`. This must be labeled non-blind recombined stress evidence.

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
- `84.38% UDA`: this is development Hit@5; the fixed-test result is `73.96%`.
- UDA answer accuracy, open-corpus retrieval, hidden/blind holdout, or post-test
  improvement claims.
- R3 page-max or typed-planner improvement claims: both candidates were
  rejected, and neither reached the R3 fixed test.
- WixQA Synthetic `97.88%` as a headline accuracy; it is development Recall@5.
- WixQA Agent answered rate as answer correctness; semantic correctness was not
  measured and the route was rejected.
- EnterpriseRAG-Bench `60.37%` Recall@5 as end-to-end answer accuracy.
- R4 validation nDCG `64.41% -> 72.61%` as a promoted quality gain: the same
  candidate missed the preregistered Hit@5 gate and was rejected before test.

## Evidence chain

- FinanceBench baseline: `BASELINE.md`, ranking artifact SHA-256
  `99617386a2d8728356db2821c8a7a05bc4f10a1c289cfd56b6809c761c321593`.
- FinQA: `docs/external_datasets/evidence/finqa_test_holdout_v1.json`, SHA-256
  `525c93a2f9437a5880fbed68e536fb351414ca0c50c8736951aa0474b744bb56`.
- garak holdout: `evidence/garak_latent_report_holdout_v1.json` and fixture
  SHA-256 `babd8bd8e52f3b8d63bffcb526de426af550ad1f791eaddb7431d0a6b314643c`.
- UDA fixed test: `docs/external_datasets/evidence/uda_finance_test_v1.json`,
  SHA-256 `6b08e213e93ae00c9eb834a388c88460d33356282d112f2f80869e0f04a695d0`.
- WixQA: `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v1.json`,
  execution SHA `234734657fe354a0ecd767022c6f7c22cdc329da`.
- EnterpriseRAG-Bench:
  `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json`,
  execution SHA `955d86f1ca244bc90025c89806fd786f978b98ff`.
- UDA R4 rejected validation:
  `docs/r4/evidence/uda_finance_r4_public_v1.json`, SHA-256
  `730eff46cdb82e56254c3c9bce63baa41bafbd216c4323b4e67bb69bc60fa2e7`.
