# Retrieval Strategy Bake-off v1 Engineering Journal

## P0-P1: Audit and Dataset Ledger

- Baseline revision: `9a2489a04113fc2f6577e94bc3e3fbdcdb08f7f4` on `main`.
- Existing historical evidence was found for guarded raw-chunk BGE reranking
  and for the stopped adaptive-retry reproducibility gate.
- The WixQA flat index persists chunks, BM25 tokens, and a FAISS BGE index. It
  does not persist article embeddings. The diversity selector therefore
  reconstructs only candidate chunks from FAISS and never re-embeds corpus
  content.
- Dataset usage is explicitly consumed, retrospective 200-question WixQA
  ExpertWritten retrieval evaluation. Question text and gold IDs stay private;
  public evidence exposes only hashes and aggregates.

## P2-P6: Deterministic Harness

- Added a pure offline selector with a frozen `alpha=0.75` and deterministic
  tie breaking by article ID.
- Added a strategy runner that refuses to overwrite a run, verifies the source
  manifest and index identity, records actual Git state, and writes private
  details separately from public aggregate evidence.
- S0, S1, and S2 are implemented but no metric claim is made until their runs
  complete and the resulting JSON evidence is reviewed against this protocol.

## P3-P8: Deterministic Results and Historical Reranker Import

- S0 ran at `b158a69` with a clean worktree. S1 and S2 ran at `a296d32` with
  clean worktrees and the same corpus/index/question hashes. A first S1 export
  was retained as an audit record, then superseded by the clean-worktree run;
  its rankings and metrics were identical.
- S1 lowered Recall@5 by 0.50pp, nDCG@5 by 0.24pp, and MRR@5 by 0.15pp. S2
  produced exactly the same quality metrics as S1 and was slightly slower.
  Both are rejected rather than tuned on the consumed cohort.
- Existing guarded raw-chunk BGE reranking is imported as S3 evidence only. It
  was measured against a Dense baseline, not this new hybrid S0 baseline, so it
  cannot be used to claim a direct S0-to-S3 delta. Its source evidence SHA-256
  is `0dac98555d39e212e00a6d56dc3b1e4adff17e87738612033f7e4ea24fec93b9`.
