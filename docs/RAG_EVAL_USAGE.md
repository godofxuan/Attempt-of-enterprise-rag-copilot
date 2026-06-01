# RAG evaluation usage

Copy these files into the root of `Attempt-of-enterprise-rag-copilot` after copying `enterprise_rag_golden_set_v1/data/raw_docs` to `data/raw_docs` and `enterprise_rag_golden_set_v1/data/eval` to `data/eval`.

## Commands

```bash
# 1. Optional: repair shortened evidence strings.
python -m scripts.patch_evidence_exact

# 2. Build indexes from the new 15 documents.
python -m scripts.build_indexes

# 3. Retrieval smoke test on dev.
python -m scripts.eval_retrieval_v2 --split dev --top-k 5

# 4. Retrieval final test.
python -m scripts.eval_retrieval_v2 --split test --top-k 5

# 5. Ablation: BM25 only vs dense only vs hybrid RRF.
python -m scripts.eval_ablation_v2 --split test --top-k 5

# 6. Fusion ablation: BM25, dense, concat union, weighted score fusion, RRF.
python -m scripts.eval_fusion_ablation --split test --top-k 5
python -m scripts.eval_fusion_ablation --split test --top-k 5 --alpha 0.3
python -m scripts.eval_fusion_ablation --split test --top-k 5 --rrf-k 60

# 7. Answer eval; start small because it calls the chat model.
python -m scripts.eval_answer_v1 --split test --limit 10
python -m scripts.eval_answer_v1 --split test
python -m scripts.eval_answer_v1 --split adversarial
```

## Notes

- Retrieval metrics skip `answerable=false` by default.
- Generated outputs are saved under `data/eval_outputs/`.
- Retrieval details are saved as JSONL files for per-question error analysis.
- Answer eval also writes `answer_{split}_error_analysis.csv`.
- `weighted_score_fusion` is an experimental baseline because dense and BM25 scores are normalized per query.
- Commit raw docs, eval JSON files, scripts, tests, and README results.
- Do not commit `data/indexes/`, `data/app.db`, or generated eval output files unless you intentionally want result snapshots.
