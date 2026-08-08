# Experiment Registry

Every result must be registered before it is used in a report or resume claim. A result without a committed protocol, exact revision, immutable artifact hash, and explicit claim scope is `NOT_CLAIMABLE`.

## Claim tiers

| Tier | Meaning | Resume use |
|---|---|---|
| E1 | External dataset, independent or fixed test protocol | Allowed with dataset, sample size, model, and limitations |
| E2 | External dataset development split or previously disclosed fixed test | Allowed only as development/diagnostic evidence |
| S1 | Internal synthetic paired or regression suite | Allowed only when explicitly called synthetic |
| N | Negative, invalid, leaked, or incomplete experiment | Never present as an improvement |

## Registered experiments

### RM-0001 FinanceBench fixed-test baseline

- Status: `OBSERVED`; tier: `E2`
- Ranking Git SHA: `28417da2a6988c7c61820b68e8b59dbed267dd9c`
- Metric Git SHA: `d8cda100d3a92935f987a5e58ab053e546e7cd11`
- Dataset/split: FinanceBench revision `cc39aeb4afdf33909ee1412188bf89035950c2eb`, company-disjoint fixed test, 101 cases
- Model: no answer model; embedding `bge-m3` digest `790764642607...2146bab`; no reranker
- Seed: deterministic/no sampling
- Hardware: Ryzen 5 7500F, RTX 5060 8151 MiB, Windows 11 Pro
- Command: recorded in `BASELINE.md`
- Latency: mean 1043.38 ms, p50 918.52 ms, p95 1417.10 ms
- Result: Page Hit@5 0.3069, MRR@5 0.1980, nDCG@5 0.2135
- Failure: historical test aggregate was already visible; this is not a fresh blind holdout
- Artifact: ranking details SHA-256 `99617386a2d8728356db2821c8a7a05bc4f10a1c289cfd56b6809c761c321593`

### RM-0002 FinQA fixed 100-case answer/citation baseline

- Status: `OBSERVED`; tier: `E1` with fixed-sample qualifier
- Git SHA: protocol revision `35139977635cfb31bc1829b1e11422151a9905d6`
- Dataset/split: FinQA revision `0f16e2867befa6840783e58be38c9efb9229d742`, deterministic 100/1,147 test sample
- Model: `qwen3:8b` digest `500a1f067a9f...b2b8b41`; embedding `bge-m3` digest `790764642607...2146bab`; temperature 0
- Seed: `finqa-test-holdout-v1`
- Hardware: local Ollama environment; the original public evidence does not claim cross-hardware latency portability
- Result: hybrid strict 0.44, grounded strict 0.40, evidence recall 0.935, citation precision 0.7938, citation recall 0.7833
- Failure: 1% generation protocol error; full 1,147-case test was not run
- Artifact SHA-256: `525c93a2f9437a5880fbed68e536fb351414ca0c50c8736951aa0474b744bb56`

### RM-0003 Expanded synthetic corpus regression

- Status: `OBSERVED`; tier: `S1`
- Dataset/split: generated enterprise corpus, fixed 56-case test
- Model: active V2 retrieval with configured embedding; no answer-generation metric
- Seed: bootstrap seed `20260716`
- Result: 56/56 pass; Hit@1/3/5 1.0 on 39 retrieval-scored cases; mean latency 156.82 ms
- Failure: authored corpus and evaluation originate from the same project; external generalization is not measured
- Artifact SHA-256: `db817c18d8a8d12b60698b38acaffcb215b392989db3958066b7def590b439aa`

### RM-0004 Custom Guard OFF/ON paired security baseline

- Status: `OBSERVED`; tier: `S1`
- Dataset/split: 36 custom pairs, 72 rows, 24 attack cases
- Model/config: same retrieval/model per pair; only Guard condition changes
- Result: user-visible ASR 12.5% to 0%; context exposure 29.17% to 0%; benign quarantine 0/32
- Failure: 13/28 labeled attack units did not reach the Guard; suite is not external
- Artifact SHA-256: `da30f6fcb3ac24947000437aee67542351f47ca207deb647ee8414fa2cf42c35`

### RM-INC-0001 Public verifier invocation incident

- Status: `RESOLVED`; tier: `N`
- Symptom: R2-S3 verifier reported `unexpected public artifact set`
- Cause: verifier defaulted to the current directory and was invoked from repository root
- Resolution: pass the package directory explicitly; verification then passed with decision `NO_CURRENT_BYPASS_OBSERVED`
- Lesson: all registry commands must include explicit input/output paths and working directory

## Planned preregistered experiments

| ID | Split used for selection | Frozen evaluation | Decision rule |
|---|---|---|---|
| RM-0100 Retrieval arm comparison | FinanceBench dev only | historically disclosed 101-case fixed test, once per selected arm | select by dev nDCG@5, report test without retuning |
| RM-0110 Cross-encoder top-N | FinanceBench dev only | selected configuration only | retain only if quality gain is stable and latency Pareto is acceptable |
| RM-0120 Parser paired ablation | only typed parser failures | frozen protocol | run only if layout/table failures are a material share |
| RM-0130 End-to-end answer/citation | development calibration | fixed external sample | deterministic metrics first; judge score labeled separately |
| RM-0140 External security subset | adapter development cases only | frozen public attacks | same model/retrieval/seed; Guard is the only changed factor |
| RM-0150 Bounded adaptive retrieval | failure-derived development subset | fixed evaluation | default remains off unless gain exceeds registered cost threshold |

## Completed improvement-round experiments

### RM-0101 / RM-0102 / RM-0103 FinanceBench retrieval arms

- Status: `OBSERVED_DEVELOPMENT`; tier: `E2`
- Git SHA: `7a676bbcd42bdc8c418e79d5ed559c187de7dff8`
- Dataset/split: FinanceBench `cc39aeb4afdf33909ee1412188bf89035950c2eb`, dev, 49 cases
- Model: no answer model; `bge-m3` embedding digest `790764642607...2146bab`; no reranker
- Seed: deterministic/no sampling
- Hardware: Ryzen 5 7500F, RTX 5060, Windows 11; retrieval executed through local Ollama embeddings
- Commands: `python -m scripts.eval_financebench_pages --run-id <arm-id> --split dev --retrieval-variant <bm25|dense|hybrid_rrf> --candidate-k 20 --max-chunks-per-doc 5 --no-include-parent --no-page-drilldown`
- Results: BM25 / Dense / RRF Page Hit@5 = 0.1429 / 0.4490 / 0.2857; nDCG@5 = 0.1103 / 0.3525 / 0.1839; p95 = 783.90 / 533.30 / 1006.26 ms
- Failure: lexical and RRF arms materially underperformed dense; no candidate was promoted to fixed test
- Artifact detail hashes: BM25 `1eeec945b24b726f360275387b95a3475cd05b2eb22df76cce11e31ff481060a`; Dense `c7b316c672e2fe1b1f14006731558051f7a147cbd9ff4df6999dd338b1a383d0`; RRF `c64ea8c69c9bd410338fb89b64d3b019ecbc4fe9a488ac1835dccaba8cde680d`
- Public evidence SHA-256: `b86b1078d2650bbf4db09bd5570425c2c064060a109e4ef292e1827f5ece41b9`

### RM-0111 / RM-0112 FinanceBench cross-encoder

- Status: `NEGATIVE_DEVELOPMENT`; tier: `N`
- Git SHA: `99314ed37a17ae7c4efe282ab31971afb6b338d9`
- Dataset/split: FinanceBench dev, 49 cases
- Embedding: `bge-m3`; reranker: `cross-encoder/ms-marco-MiniLM-L6-v2` revision `c5ee24cb16019beea0893ab7796b1df96625c6b8`, CPU, batch 16
- Seed: deterministic/no sampling; model snapshot pinned and loaded from D-drive cache
- Hardware: Ryzen 5 7500F CPU, Windows 11; observed model process peak RSS about 511.9 MiB
- Commands: `python -m scripts.eval_financebench_pages --run-id <id> --split dev --retrieval-variant hybrid_rrf --candidate-k 20 --max-chunks-per-doc 5 --no-include-parent --page-drilldown --drilldown-max-documents <1|2> --drilldown-chunks-per-doc 10 --drilldown-mode hybrid --drilldown-merge-mode quota --page-reranker cross_encoder --reranker-model cross-encoder/ms-marco-MiniLM-L6-v2 --reranker-model-revision c5ee24cb16019beea0893ab7796b1df96625c6b8 --reranker-device cpu --reranker-batch-size 16`
- Results: top-10 Hit@5 0.4694, nDCG@5 0.3472, p95 2466.12 ms; top-20 Hit@5 0.4694, nDCG@5 0.3292, p95 2474.72 ms; one reranker call/query
- Failure: no nDCG gain over Dense 0.3525; p95 was about 4.63x Dense for top-10; top-20 added no top-5 hit
- Artifact summary hashes: top-10 `e9720db59b5aff5e42c76df1afa9d9cf0fd38aa1c86f58f9739bff7ed1056ad0`; top-20 `53e219de20486af82fa72051a1171103752062cc5e1c9642dc270ed736c629c5`

### RM-0121 FinanceBench typed failure analysis

- Status: `OBSERVED_DEVELOPMENT`; tier: `E2_DIAGNOSTIC`
- Git SHA: `19be1ba9e1b07efb98a1af4d3e722c4d8e8e4495`
- Input: RM-0102 dense details, 49 cases, 31 failures
- Command: `python -m scripts.analyze_financebench_failures --run-id rm0120-dev-dense-failures-19be1ba --details <rm0102-details.jsonl>`
- Result: 20 page-ranking misses, 4 partial multi-page, 4 document-ranking, 3 document-miss; parser-risk 1/31
- Decision: parser ablation not triggered; adaptive retrieval remains off
- Artifact hashes: summary `18016d140e2a19be4fbc0ea96a4c154971095b902fc91c77925afde45115299a`; manifest `0b044d35853eff82f600f10f0158cc8688de01a36ee52adf4e70faca5ccb800d`

### RM-0141 garak development red baseline

- Status: `RED_DEVELOPMENT`; tier: `N`
- Git SHA: `285dafc1310b7e7536d420358a5b015ea1a5316b`
- Dataset: NVIDIA garak revision `afae291b...392ba`, `LatentInjectionReport`, 12 attacks + 4 benign
- Model: `qwen3:8b` digest `500a1f06...b2b8b41`; temperature 0; no embedding/reranker; fixed retrieved content
- Seed/order: deterministic counterbalanced arm order
- Hardware: AMD64 Ryzen 5 7500F, Windows 10.0.26200; local Ollama only
- Command: `python -m scripts.eval_garak_latent_report --run-id rm0140-garak-report-qwen3-285dafc --model qwen3:8b --execute-live`
- Result: ASR remained 2/12 (16.67%) in both Guard arms; context exposure changed 12/12 to 8/12; benign false positives 0/4
- Failure: two external injection instruction forms were not recognized; result used only for Guard development
- Summary SHA-256: `1331e6071cc9371f8ca4096538b2a241d3d55c9a4aca4425b1c8b41e5bf37dae`

### RM-0142 garak repaired development run

- Status: `OBSERVED_DEVELOPMENT`; tier: `E2`
- Git SHA: `1e7ea0c9fbd037277fc5feaa733d2063d315e63a`
- Dataset/model/order/hardware: same as RM-0141
- Command: `python -m scripts.eval_garak_latent_report --run-id rm0150-garak-report-dev-qwen3-1e7ea0c --model qwen3:8b --timeout-seconds 120 --execute-live`
- Result: ASR 2/12 to 0/12; context exposure 12/12 to 0/12; benign false positives 0/4; Guard mean 1.56 ms
- Failure/limit: development data was used to choose the two rule changes; not independent evidence
- Summary SHA-256: `ce0c8db7a384631ffc32344330540d4b591f1ea39f4f7ff7b35eec8d4faede61`

### RM-0143 garak combination-disjoint holdout

- Status: `OBSERVED`; tier: `E1_SMALL_SUBSET`
- Holdout freeze SHA: `b382f560acbc819efbf32509bd5a0d16258756ef`
- Evaluation SHA: `1e7ea0c9fbd037277fc5feaa733d2063d315e63a`
- Guard source SHA-256: `2dd035b857638614f932bcc48adeecc48425d5aa4868c4df1d7194deb7667111`
- Dataset/split: same pinned garak probe; unseen context/payload/trigger combinations; 12 attacks + 2 benign
- Model/config/seed/hardware: same as RM-0142; Guard is the only arm difference
- Command: `python -m scripts.eval_garak_latent_report --run-id rm0160-garak-report-holdout-qwen3-1e7ea0c --fixture data/external_benchmarks/garak_latent_report_holdout_v1.json --model qwen3:8b --timeout-seconds 120 --execute-live`
- Result: ASR 4/12 (33.33%) to 0/12; context exposure 12/12 to 0/12; benign quarantine 0/2; Guard mean 1.42 ms
- Latency: OFF mean/p50/p95 1206.21/1349.64/2038.88 ms; ON 246.99/1.54/1997.79 ms. ON latency includes early quarantines and is not a pure service-latency comparison.
- Failure/limit: one probe, combination-disjoint rather than probe-family-disjoint, only two benign controls
- Private result SHA-256: `1c3faee7284bd4dc6a1d123982a944dcbbef8d8b13154b68da0a4bad34a1670a`
- Public evidence SHA-256: `b2c56883079ef01510986452b61ac43d23e851ce35b6783efbb7094f5ddd21f9`

### RM-0201 / RM-0202 / RM-0203 UDA FinHybrid development arms

- Status: `OBSERVED_DEVELOPMENT`; tier: `E2`
- Protocol freeze SHA: `b539787`; runner SHA: `eb7b7824ad85c4a16ea119e5adeaccb7e86cd502`
- Dataset: UDA-QA FinHybrid, Git revision `fca5237...dc185`, Hugging Face revision `d436710...117b2`, CC-BY-SA-4.0
- Split: 64 questions, eight reports from eight companies; no company overlaps the fixed test
- Retrieval: known-report page localization; BGE-M3 digest `790764...2146bab`; 8,905 chunks; no answer model or reranker
- Hardware: Ryzen 5 7500F, RTX 5060 8151 MiB, Windows 11 Pro 10.0.26200
- Command: `python -m scripts.eval_uda_finance_pages --run-id <id> --split dev --retrieval-arm <bm25|dense|hybrid_rrf> --candidate-k 20 --max-chunks-per-doc 5 --no-include-parent`
- Results BM25 / Dense / RRF: Hit@5 `0.6719 / 0.8438 / 0.7969`; nDCG@5 `0.5317 / 0.6654 / 0.6614`; p95 `123.68 / 235.42 / 297.92 ms`
- Decision: Dense selected by preregistered nDCG@5 before test; RRF's higher MRR did not change the metric after observation
- Public selection evidence SHA-256: `f05acb50aa4a2d11fded62ce8fc72603c263aab7f929ca8577e76d9024ce9d44`

### RM-0204 UDA FinHybrid company-disjoint fixed test

- Status: `OBSERVED_TEST_CONSUMED`; tier: `E1_FIXED_EXTERNAL`
- Selection SHA: `8a1f103e1f941f4cf957e00633069cfe959aa6d0`; evaluation SHA: `b21320274c6c886eb2cf3c33ddf96fc6f4c6f260`
- Split: 96 questions, 12 reports from 12 companies absent from development; deterministic public-label fixed test, not hidden blind review
- Retrieval: Dense page retrieval conditioned on the known report; BGE-M3 digest `790764...2146bab`; candidate-k 20; top-k 5
- Result: Hit@1/3/5 `0.4688 / 0.6771 / 0.7396`; MRR@5 `0.5707`; nDCG@5 `0.6130`; p95 `222.91 ms`
- Failure: 25/96 misses; seven nearest retrieved pages were adjacent and ten were more than ten pages away
- One-shot marker: `COMPLETED`, private result manifest SHA-256 `5c2ea6a24d6ca263cc29fd99fd87ac78736d7d8966b155fbea55e6cc29f72bab`
- Limitation: not document discovery, answer accuracy, a baseline-to-improved comparison, or a hidden holdout; test is consumed and forbidden for tuning
- Public evidence SHA-256: `6b08e213e93ae00c9eb834a388c88460d33356282d112f2f80869e0f04a695d0`

### RM-0301 R3 UDA page-max validation

- Status: `VALIDATION_REJECTED`; tier: `N`
- Protocol/cohort freeze SHA: `0c62dbe`; evaluation SHA: `9c45fbf53dfdcc1d6e41284a1e56944f03e367b5`
- Dataset: UDA FinHybrid, 96 validation questions from 12 companies absent from R3 development and every earlier UDA cohort
- Retrieval: unchanged BGE-M3 Dense chunk baseline versus page-max deduplication; same known report and ACL boundary
- Result: Hit@5 `81.25% -> 82.29%`; nDCG@5 `67.58% -> 68.46%`; p95 `281.16 -> 276.87 ms`
- Decision: failed frozen `+5pp` Hit@5 and `+3pp` nDCG gates; candidate not promoted; R3 fixed test untouched
- Private manifest SHA-256: `3bce998a2eebc4e508fcd7e25ab7b87d5f014746853fa259ecea3b51b66c89c6`

### RM-0302 R3 UDA answer and citation development

- Status: `NEGATIVE_DEVELOPMENT`; tier: `N`
- Protocol SHA: `bfeceffb4d4b89f8b45fcc8b97dd44ac7275746a`; candidate analysis SHA: `5a0b8c709be2a01992395c5037ed3b404e827de2`
- Dataset: 192 development questions from 24 newly selected companies; validation/test answer labels not used
- Model: Qwen3-8B digest `500a1f06...b2b8b41`; unchanged BGE-M3 Dense Top-5 evidence; output budgets 256/128; chat cache reset every six cases
- Result direct/typed: numeric `7.81% / 1.56%`; grounded `7.29% / 1.04%`; unsupported `31.25% / 58.85%`; p95 `8.56 / 3.75 s`
- Oracle diagnosis: only `7/192` cases had a gold-matching value among the first 32 candidates; `190/192` reached the limit
- Decision: typed candidate rejected before validation; fixed test untouched
- Private answer/candidate manifests: `4f5d7fbfdabd344a9545cad2c5ee0a7e3abb5e396d7692a7e326d00b7e8d6437` / `25c24907dbe5d006fa96d28c75bfa68a72ccdf547865d320442ca36d1c12403e`

### RM-0303 expanded garak current-Guard stress reproduction

- Status: `OBSERVED_STRESS`; tier: `E2_STRESS_NOT_BLIND`
- Fixture builder/freeze/evaluation SHAs: `15ee888` / `e22bd7d` / `837616f258463a0f0fa9e9421549902f0ba28426`
- Dataset: one pinned NVIDIA garak `LatentInjectionReport` probe, 48 recombined external attacks + 4 benign controls; not a new blind holdout
- Model: Qwen3-8B digest `500a1f06...b2b8b41`; temperature 0; output 256; local-only egress; counterbalanced arm order
- Result: ASR `12/48 -> 0/48`; context exposure `48/48 -> 0/48`; Guard ON benign quarantine `0/4`; benign utility `4/4`; mean Guard scan `1.88 ms`
- Runtime: 56 model calls + 5 cache resets + 1 identity request = 62 allowed local requests; blocked egress 0
- Limit: larger stress coverage, but less independent than RM-0143; do not replace the combination-disjoint resume claim
- Private result/public summary hashes: `01f9a6b8e3014c0f958300e0cd1ac9174a6806d6c235d90f05641ef425d2132e` / `76e4f795fef0ce8bc76f23c6d59d5a13b37834fd7acba63c5657b876c9759f2e`
