# Resume Metrics Baseline

Status: frozen on 2026-08-07.

## Revision anchors

- Ranking-producing revision: `28417da2a6988c7c61820b68e8b59dbed267dd9c`
- Additive metric-calculator revision: `d8cda100d3a92935f987a5e58ab053e546e7cd11`
- Branch: `codex/rag-eval-system`
- The metric change adds p50, Page MRR@5, and Page nDCG@5. It does not change retrieval order.

## Environment

- OS: Windows 11 Pro `10.0.26200`
- CPU: AMD Ryzen 5 7500F, 6 cores / 12 logical processors
- GPU: NVIDIA RTX 5060, 8151 MiB, driver 610.88
- Embedding: Ollama `bge-m3`, digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`
- Answer model where applicable: Ollama `qwen3:8b`, digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`
- Experiment temporary files must use `.private/tmp` on drive D.

## FinanceBench page-retrieval baseline

Dataset revision: `cc39aeb4afdf33909ee1412188bf89035950c2eb` from the public FinanceBench repository. The public release contains 150 annotated cases; this project uses 49 development cases and a company-disjoint 101-case fixed test split. The fixed test has been evaluated before, so it is externally sourced and company-disjoint, but it is not a newly unseen blind holdout.

Command:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_financebench_pages --run-id resume-baseline-financebench-test-28417da --split test --candidate-k 20 --max-chunks-per-doc 2 --include-parent --page-drilldown --drilldown-max-documents 1 --drilldown-chunks-per-doc 5 --drilldown-mode dense --drilldown-merge-mode quota --execute-frozen-test
```

Results over 101 cases:

| Metric | Baseline |
|---|---:|
| Document Recall@5 | 0.9505 |
| Page Hit@1 | 0.1287 |
| Page Hit@3 | 0.2871 |
| Page Hit@5 | 0.3069 |
| Page MRR@5 | 0.1980 |
| Page nDCG@5 | 0.2135 |
| Macro Page Recall@5 | 0.2772 |
| Complete Page Recall@5 | 0.2475 |
| Mean latency | 1043.38 ms |
| p50 latency | 918.52 ms |
| p95 latency | 1417.10 ms |

The p50, MRR, and nDCG values were deterministically derived from the unchanged baseline `details.jsonl` by the additive calculator revision. Ranking evidence SHA-256: `99617386a2d8728356db2821c8a7a05bc4f10a1c289cfd56b6809c761c321593`.

## FinQA answer/citation baseline

This is one fixed 100-case sample from the 1,147-case FinQA test split, not the full test set.

| Arm | Strict execution | Grounded strict | Evidence recall | Citation precision | Citation recall | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| Gold evidence | 0.52 | 0.45 | 1.000 | 1.000 | 0.925 | 931.41 ms |
| Hybrid retrieval K=10 | 0.44 | 0.40 | 0.935 | 0.7938 | 0.7833 | 1570.29 ms |

Evidence: `docs/external_datasets/evidence/finqa_test_holdout_v1.json`, SHA-256 `525c93a2f9437a5880fbed68e536fb351414ca0c50c8736951aa0474b744bb56`.

## Synthetic enterprise corpus baseline

The generated corpus has 240 documents, 20 policies, 40 policy versions, 12 departments, 15 ACL groups, and 56 fixed test cases. The live retrieval run passed 56/56; Hit@1/3/5 and MRR were 1.0 on the 39 retrieval-scored cases. This validates regression behavior only and is not evidence of external-domain generalization.

Evidence SHA-256: `db817c18d8a8d12b60698b38acaffcb215b392989db3958066b7def590b439aa`.

## Security paired baseline

The custom indirect-injection suite has 36 Guard OFF/ON pairs and 72 rows. On 24 attack cases, user-visible attack success changed from 3/24 (12.5%) to 0/24 (0%); model-context exposure changed from 7/24 (29.17%) to 0/24. Benign quarantine was 0/32. Only 15/28 labeled attack units reached the Guard, and all 15 were quarantined. These are synthetic project-specific results, not an external security benchmark.

Evidence SHA-256: `da30f6fcb3ac24947000437aee67542351f47ca207deb647ee8414fa2cf42c35`.

## Baseline interpretation

The strongest current external signal is the FinQA fixed-sample end-to-end evaluation. FinanceBench shows that document retrieval is already high while exact page localization is the dominant weakness. Synthetic and security suites establish regression and safety evidence but cannot support broad external claims.
