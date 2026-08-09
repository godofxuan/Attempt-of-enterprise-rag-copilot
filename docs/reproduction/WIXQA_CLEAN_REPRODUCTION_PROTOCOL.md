# WixQA Clean Reproduction Protocol

## Objective and boundary

Reproduce, rather than improve, the historical frozen WixQA retrieval evidence.
The run replays public labels and is not a new holdout or an independent
third-party reproduction.

The structured contract is
`docs/reproduction/evidence/WIXQA_CLEAN_REPRODUCTION_PROTOCOL_V1.json`. It was
committed before any result was observed. All quality metrics have absolute
tolerance `0.0`; latency is reported as a machine-specific observation.

## Frozen identities and configuration

- Official Hugging Face revision: `d662dc42479c14e202eccd832f8c4b66a035c4cc`
- Manifest SHA-256: `e40972d70a8c80685b3730733efd90ac82a01fd52a949a0d27e122809bc290dd`
- BGE-M3 SHA-256: `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`
- Chunk size/overlap: 1,800/150 characters, title repeated
- Candidate chunks: 200
- Arms: BM25, Dense, equal RRF with `rrf_k=60`
- Cohorts: Synthetic 6,221; Simulated 200; ExpertWritten 200
- Metrics: Hit@1, Recall@1/3/5, MRR@5, nDCG@5, multi-article
  completeness@5; mean/p50/p95 latency is observational

No parser, model, chunk, candidate, RRF, split, question, or metric change is
allowed after registration.

## Isolated roots

The run uses four new, absent roots below
`.private/final_closeout/wixqa_clean_v1/`: `source`, `indexes`,
`embedding_cache`, and `eval_runs`. `--require-clean-roots` fails before writing
if any root already exists. Historical source, index, cache, and private run
files are comparison references only and are not inputs.

## Registered command

```powershell
.\.venv\Scripts\python.exe -m scripts.reproduce_wixqa_retrieval `
  --run-prefix wixqa-clean-v1 `
  --source-root .private\final_closeout\wixqa_clean_v1\source `
  --index-root .private\final_closeout\wixqa_clean_v1\indexes `
  --embedding-cache .private\final_closeout\wixqa_clean_v1\embedding_cache `
  --output-root .private\final_closeout\wixqa_clean_v1\eval_runs `
  --public-output .private\final_closeout\wixqa_clean_v1\candidate_public.json `
  --require-clean-roots
```

The candidate is then compared without tuning:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_wixqa_clean_reproduction `
  --historical docs\enterprise_eval\evidence\wixqa_retrieval_baseline_public_v2.json `
  --candidate .private\final_closeout\wixqa_clean_v1\candidate_public.json `
  --contract docs\reproduction\evidence\WIXQA_CLEAN_REPRODUCTION_PROTOCOL_V1.json `
  --output docs\reproduction\evidence\wixqa_clean_reproduction_public_v1.json
```

Any identity or quality mismatch yields `REPRODUCTION_GAP`. The tolerance must
not be changed after seeing results.
