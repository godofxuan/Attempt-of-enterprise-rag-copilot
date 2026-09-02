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

## Stronger-model stop decision

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
