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
