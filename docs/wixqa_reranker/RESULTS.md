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

