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

## Two-chunk article representation follow-up

The first BGE experiment represented each article with only its highest Dense
chunk. The separately frozen multi-chunk protocol scanned the same Top-200
chunks, ranked articles by first occurrence, retained at most two chunks for
each selected article, scored chunks independently, and used the maximum
admitted chunk score as the article score.

| Configuration | Recall@5 | nDCG@5 | MRR@5 | Complete@5 | p95 |
|---|---:|---:|---:|---:|---:|
| Top-10, one chunk control | 64.92% | 50.25% | 47.44% | 33.33% | 480.63 ms |
| Top-10, two chunks | 65.67% | 51.88% | 49.52% | 33.33% | 704.06 ms |
| Top-20, two chunks | 65.17% | 51.15% | 48.87% | 22.22% | 1309.11 ms |
| Top-50, two chunks | 67.83% | 52.42% | 49.68% | 22.22% | 2412.27 ms |

Top-10/two-chunk passed the frozen quality gate and was selected as the
interactive experimental mode. Top-20 was rejected because Top-10/two-chunk
had better quality and lower latency. Top-50 produced the best Recall and nDCG
but its 2.41-second p95 and lower multi-article completeness restrict it to an
offline high-recall diagnostic mode.

The one permitted ExpertWritten retrospective confirmation for the selected
Top-10/two-chunk arm produced:

| Metric | Dense | Two-chunk BGE | Delta | Paired bootstrap 95% CI |
|---|---:|---:|---:|---:|
| Recall@5 | 66.42% | 69.58% | +3.17pp | [-1.25pp, +7.67pp] |
| nDCG@5 | 52.16% | 56.12% | +3.97pp | [-0.07pp, +8.08pp] |
| MRR@5 | 49.61% | 55.11% | +5.50pp | [+0.74pp, +10.46pp] |

Relative to the previous single-chunk BGE point estimate, the two-chunk arm
added `+1.00pp` Recall, `+2.04pp` nDCG, and `+2.89pp` MRR. Multi-article
completeness declined from `34.62%` to `30.77%`, so the result does not support
an "improved every metric" claim. The current run measured p95 `693.73 ms`;
that absolute value must not be compared with the prior day's `135.92 ms`
because host load and Dense p95 also changed materially.

Public aggregate evidence is recorded in
[`article_multi_chunk_evidence.json`](article_multi_chunk_evidence.json).

## What was implemented

- Dense candidates can retain the first two matching chunks for each selected
  article without concatenating or truncating away the second chunk.
- The existing retrieved-content Guard runs before Cross-Encoder scoring.
- The production reranker safety limit is unchanged; the WixQA-only offline
  evaluator supports frozen Top-10/20/50 article windows up to 100 chunks.
- Dense-head preservation and deterministic candidate completion prevent the
  reranker from adding or silently dropping articles.
- Runs bind the dataset, index, embedding, reranker revision, model weights,
  Git revision, complete latency, Guard counts, and private artifact hashes.

## Raw-chunk-first collaborator follow-up

An external collaborator proposed reranking raw Dense chunks before article
deduplication. The collaborator branch was 16 mainline commits behind and
bypassed the current retrieved-content Guard, so it was reviewed in an isolated
worktree rather than merged. Its central candidate-ordering idea was then
reimplemented behind the repository's Guard and evaluated at exact code commit
`ccf90af`.

The selected interactive candidate reranks the first 20 raw chunks, after Guard
admission, with pinned `BAAI/bge-reranker-v2-m3` FP16 on an RTX 5060. Only after
scoring does it retain the best-ranked chunk for each article.

| Cohort | Metric | Dense | Guarded raw-chunk Top-20 | Delta | Paired 95% CI |
|---|---|---:|---:|---:|---:|
| Simulated 200 | Recall@5 | 61.42% | 66.92% | +5.50pp | [+0.25pp, +11.00pp] |
| Simulated 200 | nDCG@5 | 47.78% | 52.54% | +4.76pp | [+0.59pp, +9.03pp] |
| Simulated 200 | MRR@5 | 45.12% | 49.96% | +4.84pp | [+0.19pp, +9.55pp] |
| ExpertWritten 200 | Recall@5 | 66.42% | 70.83% | +4.42pp | [-0.25pp, +9.25pp] |
| ExpertWritten 200 | nDCG@5 | 52.16% | 57.18% | +5.02pp | [+0.73pp, +9.33pp] |
| ExpertWritten 200 | MRR@5 | 49.61% | 55.91% | +6.30pp | [+1.19pp, +11.36pp] |

Simulated p95 increased from `44.17 ms` to `226.16 ms`; ExpertWritten p95
increased from `44.56 ms` to `224.34 ms`. Simulated multi-article completeness
improved from `14.81%` to `29.63%`, but ExpertWritten completeness declined from
`30.77%` to `26.92%`. Therefore the profile is an explicit GPU quality mode,
not an unconditional default and not an "improved every metric" claim.

Top-50 raw chunks reached simulated Recall@5 `68.50%` and nDCG@5 `53.05%`, but
its roughly `572 ms` p95 made Top-20 the better interactive tradeoff. Both
cohorts were already consumed, so this is disclosed hypothesis-driven validation
and retrospective evidence, not a fresh blind test. Public aggregate evidence
is in [`raw_chunk_bge_evidence.json`](raw_chunk_bge_evidence.json).

## Peer Article-Reranker Reproduction

The collaborator's exact branch `feat/wixqa-bge-reranker-v2-m3` at
`79ba431` was reproduced in an isolated worktree instead of being merged. It
retrieves 200 Dense chunks, keeps the first Dense-ranked chunk for each article,
retains 50 articles, reranks article representatives, and returns five articles.
The fixed BGE-M3 index, question IDs, gold labels, final `K=5`, model revision,
and article-level metric function match the Dense baseline.

| Configuration | Recall@5 | nDCG@5 | MRR@5 | Complete@5 | Local reranker p95 |
|---|---:|---:|---:|---:|---:|
| Dense | 66.42% | 52.16% | 49.61% | 30.77% | not separately measured in this reranker pass |
| Article Top-10 | 69.92% | 56.42% | 54.78% | 34.62% | 118.62 ms |
| Article Top-20 | **71.25%** | **56.82%** | **54.50%** | **38.46%** | 240.90 ms |
| Article Top-50 | 71.00% | 56.54% | 54.28% | 38.46% | 596.19 ms |

Top-20 is the best reproduced arm. It improves Recall@5 by `4.83pp` over the
same candidate artifact's Dense result; 28 cases gain recall and 16 regress.
A separate Top-20 repetition produced exactly the same quality metrics. This
does **not** reproduce a `75%` Recall@5 claim under this exact protocol.

The branch remains offline evidence only. It did not run the current
retrieved-content Guard before cross-encoder scoring, so it is neither merged
nor promoted to the runtime. The Guard-integrated raw-chunk experiment above is
the current implementation-aligned BGE profile. Aggregate evidence without
questions, document text, or gold IDs is in
[`peer_branch_article_reproduction_v1.json`](peer_branch_article_reproduction_v1.json).

## Interpretation

The negative result does not show that reranking is useless. It shows that a
generic MS MARCO passage reranker applied to one Dense-selected WixQA chunk per
article is not Pareto-efficient on this protocol. A stronger or domain-matched
model should only be attempted after candidate-ceiling and failure analysis;
it must use a new frozen protocol and may not reuse ExpertWritten as a fresh
holdout.
