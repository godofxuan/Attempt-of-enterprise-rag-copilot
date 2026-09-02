# WixQA Article Multi-Chunk Reranker Protocol

Status: frozen before implementation and model execution on 2026-09-02.

## Hypothesis

The existing WixQA reranker represents each retrieved article with only its
highest-ranked dense chunk. A relevant article can therefore be ranked using a
non-answer-bearing chunk even when its second dense chunk contains the evidence.
Retaining two chunks per article before cross-encoder scoring may improve final
article Recall@5, nDCG@5, and MRR@5.

## Fixed candidate construction

1. Retrieve the top 200 BGE-M3 chunks.
2. Rank articles by the first occurrence of each `article_id`.
3. Select the first N articles, where N is 10, 20, or 50.
4. Continue scanning the same top-200 chunk list and retain at most the first
   two chunks for each selected article.
5. Score each query/chunk pair independently with the pinned
   `BAAI/bge-reranker-v2-m3` snapshot.
6. Define an article's reranker score as the maximum admitted chunk score.
7. Break equal article scores by original dense article rank.
8. Reorder the selected article prefix and preserve the remaining dense order.

Chunks are never concatenated. This prevents the second chunk from being lost
to the reranker's 1,200-character per-candidate boundary.

## Fixed execution configuration

- Dataset: WixQA `simulated`, 200 cases, configuration-selection only.
- Source/index identity: existing pinned public WixQA manifest and BGE-M3 index.
- Candidate chunks: 200.
- Arms:
  - top 10 articles, one chunk/article (same-run control);
  - top 10 articles, two chunks/article;
  - top 20 articles, two chunks/article;
  - top 50 articles, two chunks/article.
- Reranker: `BAAI/bge-reranker-v2-m3` revision
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
- Device/dtype: CUDA FP16.
- Batch size: 10.
- Dense head preservation: 0.
- Final ranking depth: 5 articles.

## Metrics and decision

Report Recall@5, nDCG@5, MRR@5, multi-article completeness@5, mean/p50/p95
latency, scored chunks/query, and quarantined chunks. The primary comparison is
against the same-run one-chunk Top-10 control.

An arm is an experimental quality candidate only when Recall@5 does not decline
and nDCG@5 improves by at least 0.5 percentage points. Latency is reported as a
Pareto cost; no arm becomes the production default from this retrospective
configuration-selection experiment.

The consumed ExpertWritten cohort must not be used to choose N or aggregation.
It may only receive one retrospective confirmation run after an arm is selected,
and such a result cannot be described as a fresh holdout or statistical proof.
