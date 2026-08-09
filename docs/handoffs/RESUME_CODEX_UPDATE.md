# Resume Codex Update

## Project

- Name: `Attempt-of-enterprise-rag-copilot`
- Positioning: Enterprise Knowledge RAG / bounded Agent Copilot
- Branch: `codex/rag-eval-system`
- Evidence/code base SHA: `49131de5f5b48718c72b06854cb424fcd8784a0c`
- Clean-reproduced release candidate SHA: `a3ef9c8`
- Remote-validated release payload SHA: `68523e840a8f03b32d02ac78efd14af9889765ec`
- CI status: `success`, Run `31316231539`, Ubuntu/Windows/container all passed
- Production status: `NOT_CLAIMED`

## Top verified positive results

| Result | Dataset / denominator | Evidence class | Execution SHA | Evidence | Limitation |
|---|---|---|---|---|---|
| Dense Recall@5 `42.75% -> 66.42%`; nDCG@5 `32.15% -> 52.16%`; p95 `151.8 -> 157.4 ms` | WixQA ExpertWritten, 200 questions, 52 multi-article | External public-label fixed retrieval | `234734657fe354a0ecd767022c6f7c22cdc329da` | `docs/enterprise_eval/evidence/wixqa_retrieval_baseline_public_v2.json` | Not blind; not answer accuracy |
| Verified `1.37 GiB` FTS5 index over 511,962 records/9 sources; `231.35 s`, about `1.83 GiB` peak; Recall@5 `60.37%` on 470 document-grounded questions | EnterpriseRAG-Bench full corpus | External public-label fixed lexical retrieval + capacity | `955d86f1ca244bc90025c89806fd786f978b98ff` | `docs/enterprise_eval/evidence/enterprise_rag_bench_bm25_public_v1.json` | Recall is retrieval only; Dense quality not run |
| Guard ASR `4/12 -> 0/12`; exposure `12/12 -> 0/12`; two benign controls preserved; mean scan `1.42 ms` | Pinned garak LatentInjectionReport subset, 12 attack + 2 benign | Combination-disjoint external-probe holdout | `1e7ea0c9fbd037277fc5feaa733d2063d315e63a` | `docs/resume_metrics/evidence/garak_latent_report_holdout_v1.json` | Small subset; not full garak or universal safety |

## Engineering evidence, not headline quality

- Citation verifier now rejects asymmetric English/Chinese negation
  contradictions: execution commit `0848fc0`; focused suite `22 passed`.
- FTS builder now uses one explicit offline writer lock, verified staging, and
  atomic active-pointer replacement: commit `7b1d3b3`.
- Multi-document Agent retrospective dev: completeness `0% -> 22.22%`, but
  precision `44.44% -> 18.52%`; `HOLD_NO_UNCONSUMED_VALIDATION`.
- Dense capacity: 50k BGE-M3 chunks at `36.755/s`, full projection `12.87 h`;
  `FULL_DENSE_NO_GO`, no persistent full index.
- Final local gate after public-CI hardening: `3174 passed / 29 skipped / 3
  warnings`; detached clean reproduction at `a3ef9c8`: 240 source / 216
  canonical/chunks dry-run, `214 passed / 1 skipped`, public audit `1517/0`.
- Public-clone compatibility: Dense evidence publication imports without the
  optional `pyarrow` runtime; committed WixQA evidence is always checked and
  raw-source reconstruction runs only when the official external source exists.

## Do not use

- Do not say "RAG accuracy 60.37%"; it is document Recall@5.
- Do not say "Agent accuracy 99.5%"; answered rate is not correctness.
- Do not claim Agent quality improvement from the retrospective 27-case run.
- Do not claim full Enterprise Dense/RRF/Agent, production SLO, production-ready,
  SOTA, blind WixQA, full garak, or 100% prompt-injection safety.
- Do not headline development-only WixQA Synthetic `97.88%` Recall@5.
