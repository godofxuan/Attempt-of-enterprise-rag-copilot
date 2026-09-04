# Safe Raw-Chunk Latency Erratum Protocol

## Scope

This is a measurement correction for the final Safe Raw-Chunk Reranking
closure. It does not reopen WixQA quality tuning.

The previous composite candidate-generation timer covered both raw-chunk FAISS
retrieval and an article-level Dense view needed only to score the historical
Dense baseline. The online raw-chunk GPU profile does not need the article-level
view. Therefore its reconstructed total latency is superseded by this real-path
measurement.

## Frozen Inputs and Outcomes

Nothing in this erratum changes the official LF manifest, index, frozen raw
Top-200 candidate artifact, questions, BGE-M3 embeddings, reranker revision or
weights, FP16, batch size 16, tokenizer max length 512, Guard rules, candidate
depths 20/50, reranking order, article deduplication, quality metrics, or the
recorded quality results.

The quality artifact remains authoritative for ranking quality. The latency run
must reproduce its final Guard-on Top-20 and Top-50 article IDs for every
question, or abort with `LATENCY_RUN_CHANGED_QUALITY_RANKINGS`.

## Measured Path

Each warm-model per-question timer continuously covers:

```text
question -> BGE-M3 query embedding -> raw-chunk FAISS Top-200
-> frozen candidate ID assertion -> Top-20 or Top-50 slice -> full-text Guard
-> ADMIT-only cross-encoder -> post-rerank article dedup -> Top-5
```

No `dense_article_candidates()` call, Dense backfill, candidate replenishment,
or article-level retrieval is permitted. Stage timers nest within one continuous
total timer. The measurement records three complete 200-question passes after a
fixed five-question warm-up; the headline is the median run-level p95. Model
load is excluded.

## Frozen Decision Rule

The existing quality promotion rule has already passed for Top-50. The
unchanged latency rule is:

```text
Top-50 p95 <= 650 ms
and Top-50 p95 <= 3 * Top-20 p95
```

If both conditions pass, `GUARDED_RAW_CHUNK_TOP50` becomes the optional GPU
quality profile. Otherwise `GUARDED_RAW_CHUNK_TOP20` remains selected. The
global default remains the bounded Hybrid RRF path in either outcome. Guard-off
results are diagnostic only.

## Claim Boundary

The output is local offline warm-model latency on a consumed retrospective
retrieval replay. It is not a production SLA, blind validation, or answer
quality result. After this correction, `WIXQA_RERANKER_TUNING_CLOSED` remains
in force.
