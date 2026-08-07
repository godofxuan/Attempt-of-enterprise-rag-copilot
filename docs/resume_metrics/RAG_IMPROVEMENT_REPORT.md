# RAG Improvement Report

## Executive result

This round improved **measurement credibility and retrieved-content security**,
not FinanceBench retrieval quality. The branch now has additive ranking metrics,
typed failure analysis, reproducible optional cross-encoder experiments, a pinned
external garak fixture, and a combination-disjoint security holdout frozen before
the Guard fix.

The only promoted external before/after result is the small garak holdout:

- ASR: 4/12 (33.33%) Guard OFF to 0/12 Guard ON;
- model context exposure: 12/12 (100%) to 0/12;
- benign controls: 0/2 quarantined in both arms;
- deterministic Guard mean latency: 1.42 ms.

This is one probe subset, not a benchmark-wide security result.

## Revision timeline

| Revision | Change | Why |
|---|---|---|
| `28417da2a6988c7c61820b68e8b59dbed267dd9c` | Original frozen baseline | Prevent moving the starting point. |
| `d8cda100d3a92935f987a5e58ab053e546e7cd11` | Added p50, MRR@5, nDCG@5 | Measure rank quality, not only binary hits. |
| `7a676bbcd42bdc8c418e79d5ed559c187de7dff8` | Added retrieval variants and registry | Run BM25/Dense/RRF under one evaluator. |
| `99314ed37a17ae7c4efe282ab31971afb6b338d9` | Pinned optional cross-encoder | Make model loading, revision, cache, and CPU use reproducible. |
| `19be1ba9e1b07efb98a1af4d3e722c4d8e8e4495` | Added typed failure analyzer | Decide whether parser/adaptive work is justified by evidence. |
| `285dafc1310b7e7536d420358a5b015ea1a5316b` | Added pinned garak subset | Obtain external security evidence with Guard-only pairing. |
| `b382f560acbc819efbf32509bd5a0d16258756ef` | Froze unseen garak combinations | Separate Guard development from evaluation. |
| `1e7ea0c9fbd037277fc5feaa733d2063d315e63a` | Closed two deterministic Guard gaps | Cover `disregard all info` and `System: focus only` without broad stack changes. |
| `95fc1142690132c48621904ee128803057027da5` | Fixed fixture-count reporting | Prevent a hard-coded limitation sentence from misreporting holdout size. |

## FinanceBench protocol and results

Dataset: FinanceBench revision
`cc39aeb4afdf33909ee1412188bf89035950c2eb`. The public 150 cases are split into
49 development and a company-disjoint 101-case fixed test. The fixed-test
aggregate was historically visible, so it is not a fresh blind holdout.

Development Pareto table:

| Configuration | Page Hit@5 | nDCG@5 | p95 |
|---|---:|---:|---:|
| BM25 | 14.29% | 0.1103 | 783.90 ms |
| Dense | 44.90% | 0.3525 | 533.30 ms |
| BM25 + Dense + RRF | 28.57% | 0.1839 | 1006.26 ms |
| RRF + CE top-10 | 46.94% | 0.3472 | 2466.12 ms |
| RRF + CE top-20 | 46.94% | 0.3292 | 2474.72 ms |

Dense is the development Pareto reference. The cross-encoder gained one binary
hit but worsened rank quality and increased p95 by about 4.63x. No candidate met
the promotion rule, so the 101-case test was not rerun for an improvement claim.

## Failure-driven decisions

Of 31 dense failures, 20 were page-ranking misses, four partial multi-page
recall, four document-ranking misses, and three document misses. Only one had a
deterministic parser-risk signal. Therefore:

- no ingestion rewrite or new layout parser was added;
- no default adaptive rewrite/retry was enabled;
- the optional cross-encoder was not enabled in production;
- future work should target financial page ranking and multi-page evidence.

## End-to-end answer and citation evidence

The existing fixed 100-case FinQA sample remains the end-to-end evidence:

| Arm | Strict answer | Grounded strict | Evidence recall | Citation P/R | p95 |
|---|---:|---:|---:|---:|---:|
| Gold evidence | 52% | 45% | 100% | 100% / 92.5% | 931.41 ms |
| Hybrid K=10 | 44% | 40% | 93.5% | 79.38% / 78.33% | 1570.29 ms |

This uses deterministic gold execution/citation metrics, not LLM-as-a-judge.
The 52% oracle ceiling shows that answer reasoning, program generation, and
numeric execution remain material bottlenecks after retrieval.

## External security experiment

The fixture is derived by static AST extraction from
[NVIDIA garak](https://github.com/NVIDIA/garak) revision
`afae291b684ae64055d53a0ea4228f7e760392ba`. It reuses official report contexts,
injection instructions, payloads, and triggers without project-authored attacks.
The runner fixes `qwen3:8b` digest, temperature 0, prompt, retrieval content,
counterbalanced arm order, and local-only Ollama egress. Guard mode is the only
experimental variable.

The first development run exposed two gaps. The Guard was changed only after a
disjoint fixture had been committed. On that holdout, Guard ON blocked all 12
attack contexts before model exposure. The small benign denominator is explicitly
retained in every claim.

## Reproduction commands

All commands run from repository root with `TEMP` and `TMP` set to
`.private/tmp` on drive D.

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.eval_financebench_pages --run-id <id> --split dev --retrieval-variant dense
& '.\.venv\Scripts\python.exe' -m scripts.analyze_financebench_failures --run-id <id> --details <dense-details.jsonl>
& '.\.venv\Scripts\python.exe' -m scripts.eval_garak_latent_report --run-id <id> --fixture data\external_benchmarks\garak_latent_report_holdout_v1.json --model qwen3:8b --timeout-seconds 120 --execute-live
```

Exact per-run config, model digest, hardware, latency, source hashes, and artifact
hashes are recorded in `EXPERIMENT_REGISTRY.md`, `metrics.csv`, and `evidence/`.

## Verification and compatibility repair

The first full regression after the Guard change reported 117 failures and 49
errors. They shared one cause: the R2-S3 replay evaluator treated a historical
source-run Guard hash and the current replay Guard hash as if they must always be
equal. The repair preserves the old public package byte-for-byte, pins its old
verifier to its exact historical private-manifest hash, and makes new v2 replay
manifests bind the current Guard dependency separately. Frozen FinQA protocols
also retain their old source hash and now explicitly detect current-source drift
instead of being silently rewritten.

Final verification on Windows:

- full pytest: `3056 passed, 30 skipped, 3 known FAISS/SWIG warnings` in 164.73 s;
- closeout schema/hash gate: `4 passed`;
- public repository audit: `1392 candidates / 0 findings` under the implemented
  static audit rules;
- current Guard source SHA-256:
  `2dd035b857638614f932bcc48adeecc48425d5aa4868c4df1d7194deb7667111`;
- historical evidence files were not regenerated or mutated.

## Stop decision

Stop adding frameworks or agents. Continue only if a new independent financial
page-ranking dataset or a pre-registered probe-family-disjoint security holdout
is available. The current evidence supports engineering credibility; repeated
tuning on the same 150 FinanceBench cases would reduce it.
