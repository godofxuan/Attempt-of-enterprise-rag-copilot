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
