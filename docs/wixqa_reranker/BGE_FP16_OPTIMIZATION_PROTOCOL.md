# WixQA BGE FP16 Optimization Protocol

## Purpose

The registered FP32 BGE experiment established a quality gain but failed the
latency gate. This protocol tests a runtime-only optimization of the best
quality arm: load the same exact model weights in FP16 and score all ten
candidates in one GPU batch.

## Known inputs before freeze

- Best FP32 arm: Top-10, no dense-head protection.
- FP32 Recall@5: 0.6491666666666667.
- FP32 nDCG@5: 0.5024650994019478.
- Same-run dense Recall@5: 0.6141666666666667.
- Same-run dense nDCG@5: 0.47779195278017633.
- FP32 p95: 624.6695 ms; same-run dense p95: 53.9348 ms.
- A two-case FP16 wiring smoke completed without OOM or invalid scores. It is
  excluded from quality evidence.

## Frozen candidate

- Same `BAAI/bge-reranker-v2-m3` revision and weight SHA-256 as BGE V2.
- Top-10 candidate pool; no dense-head protection.
- CUDA device, FP16 weights, batch size 10.
- Same ordered 200-case simulated cohort and same Dense candidate generator.

## Gate

The optimized arm must satisfy all of:

- Recall@5 >= 0.6475, preserving FP32 quality within 0.167pp;
- nDCG@5 >= 0.5000, preserving FP32 quality within 0.247pp;
- Recall@5 delta versus same-run Dense >= 0;
- nDCG@5 delta versus same-run Dense >= 0.02;
- p95 end-to-end latency multiplier versus same-run Dense <= 5.0.

This is a post-quality runtime optimization, not an independent quality test.
Passing permits a retrospective ExpertWritten confirmation only. It does not
establish blind generalization or authorize an unconditional CPU deployment.

