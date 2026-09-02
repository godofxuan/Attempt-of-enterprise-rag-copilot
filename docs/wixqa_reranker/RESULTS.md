# WixQA Article Reranker Results

## Decision

`VALIDATION_REJECTED_EXPERTWRITTEN_FORBIDDEN`

The pinned generic MS MARCO Cross-Encoder did not improve the 200-case WixQA
simulated validation cohort. All three registered configurations reduced both
article Recall@5 and nDCG@5, and all exceeded the frozen 5x p95 latency budget.
The consumed ExpertWritten cohort was therefore not rerun.

| Configuration | Recall@5 delta | nDCG@5 delta | p95 / Dense | Decision |
|---|---:|---:|---:|---|
| Top-10, head 0 | -2.83pp | -3.14pp | 5.90x | reject |
| Top-10, head 1 | -1.83pp | -1.29pp | 6.60x | reject |
| Top-20, head 1 | -2.25pp | -1.67pp | 12.28x | reject |

Top-10 reranking increased multi-article completeness from `14.81%` to
`33.33%`, but that isolated gain did not compensate for lower aggregate recall,
ranking quality, and much higher tail latency. It is diagnostic evidence that
the model changes evidence coverage rather than a promotion result.

## Candidate ceiling diagnosis

The same 200 validation questions were evaluated without a reranker to measure
how much relevant evidence was already available above the final Top-5 cutoff:

| Dense cutoff | Recall | Multi-article complete recall |
|---|---:|---:|
| Top-5 | 61.42% | 14.81% |
| Top-10 | 72.00% | 48.15% |
| Top-20 | 84.58% | 62.96% |

This establishes that candidate generation leaves meaningful rerankable headroom.
The registered failure is therefore more consistent with model/domain mismatch
and single-chunk article representation than with an empty candidate pool.

## Stronger-model CPU stop decision

An exploratory `BAAI/bge-reranker-v2-m3` smoke used the exact public revision
`953dc6f...` from the D-drive cache. The host has an RTX 5060, but the project
PyTorch build is CPU-only, so the CUDA attempt failed before evaluation with
`Torch not compiled with CUDA enabled`. A two-case CPU smoke then measured
reranker p95 `6616.06 ms` against Dense `55.34 ms`, roughly `119.6x`.

Two cases cannot establish quality. They are sufficient to reject a full
CPU run under the frozen latency objective. The project environment was not
replaced with a CUDA PyTorch build solely to obtain a more favorable experiment;
that would require a separate dependency, reproducibility, and deployment-cost
decision.

That CPU decision remains valid for CPU-only deployment. A later user-provided
model lead justified a separately frozen GPU experiment rather than changing
the original protocol after seeing its result.

## BGE GPU follow-up

An isolated D-drive CUDA 12.8 PyTorch runtime was created without changing the
project's default virtual environment. The full registered BGE arms used exact
revision `953dc6f...` on an RTX 5060:

| Configuration | Recall@5 | nDCG@5 | p95 | Outcome |
|---|---:|---:|---:|---|
| Dense | 61.42% | 47.78% | 39.98-53.93 ms | baseline |
| BGE Top-10, head 0, FP32 | 64.92% | 50.25% | 624.67 ms | quality pass, latency fail |
| BGE Top-10, head 1, FP32 | 65.42% | 49.51% | 616.57 ms | nDCG and latency fail |
| BGE Top-20, head 1, FP32 | 63.17% | 48.37% | 1228.94 ms | reject |
| BGE Top-10, head 0, FP16 batch 10 | 64.92% | 50.25% | 133.04 ms | optimization gate pass |

FP16 batching preserved the FP32 ranking metrics exactly while cutting BGE p95
by about 78.7%. Against its same-run Dense arm, validation Recall@5 improved
3.50pp and nDCG@5 improved 2.47pp at a 3.33x retrieval-stage p95.

The permitted retrospective ExpertWritten run produced:

| Metric | Dense | BGE reranker | Delta | Paired bootstrap 95% CI |
|---|---:|---:|---:|---:|
| Recall@5 | 66.42% | 68.58% | +2.17pp | [-2.25pp, +6.58pp] |
| nDCG@5 | 52.16% | 54.09% | +1.93pp | [-2.12pp, +6.08pp] |
| MRR@5 | 49.61% | 52.22% | +2.61pp | [-2.26pp, +7.57pp] |

ExpertWritten p95 increased from `40.74 ms` to `135.92 ms`, an absolute
increase of about `95.18 ms`. All point estimates are positive, but all paired
95% intervals cross zero. This is promising retrospective evidence, not a
statistically conclusive or blind-generalization claim. The configuration is
therefore retained as an experimental GPU quality mode rather than made the
unconditional default.

## What was implemented

- Dense candidates now retain the best matching chunk text and score per
  article.
- The existing retrieved-content Guard runs before Cross-Encoder scoring.
- The reranker is restricted to a fixed Top-10/20 candidate window.
- Dense-head preservation and deterministic candidate completion prevent the
  reranker from adding or silently dropping articles.
- Runs bind the dataset, index, embedding, reranker revision, model weights,
  Git revision, complete latency, Guard counts, and private artifact hashes.

## Interpretation

The negative result does not show that reranking is useless. It shows that a
generic MS MARCO passage reranker applied to one Dense-selected WixQA chunk per
article is not Pareto-efficient on this protocol. A stronger or domain-matched
model should only be attempted after candidate-ceiling and failure analysis;
it must use a new frozen protocol and may not reuse ExpertWritten as a fresh
holdout.
