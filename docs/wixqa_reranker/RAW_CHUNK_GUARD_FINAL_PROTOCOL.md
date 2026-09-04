# WixQA Safe Raw-Chunk Reranking Final Protocol

## Status

This protocol was frozen before the final result artifact was generated. It
closes WixQA reranker selection; no additional candidate depths, reranker
models, embedding models, chunking settings, or Guard tuning are permitted by
this protocol.

The evaluation replays the already-consumed 200-question WixQA ExpertWritten
cohort. It is a retrospective retrieval evaluation, not blind validation,
answer-quality evaluation, or a production latency SLA.

## Fixed Inputs

- Dataset manifest: `data_manifests/WIXQA_OFFICIAL_RAW_MANIFEST.json`.
- Dense retrieval: `bge-m3`, FAISS `IndexFlatIP` over L2-normalized vectors.
- Chunking: 1,800 body characters with a 150-character overlap; article title
  is prepended to every chunk.
- Candidate export: one raw dense Top-200 candidate artifact, generated once.
- Reranker: `BAAI/bge-reranker-v2-m3` revision
  `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.
- Reranker runtime: CUDA FP16, batch size 16, `model.eval()`, inference mode,
  tokenizer truncation at 512 tokens.
- Seed: `20260904`.

The final artifact records the Git SHA, manifest and index hashes, candidate
artifact hash, embedding identity, reranker weight hash, environment, and
commands actually used.

## Security and Candidate Semantics

For every question, the exported first 50 raw dense chunks are fixed before
any arm executes. Top-20 is exactly the first 20 rows of that same ordered
sequence. No arm may retrieve replacement candidates.

Guard-on arms execute:

```text
raw dense chunks -> RetrievedContentGuard over full chunk text -> ADMIT only
-> cross-encoder over full chunk text with tokenizer truncation -> descending
score -> first occurrence per article -> at most five articles
```

Guard-off arms use the identical raw candidates and scorer, but the Guard runs
only as a shadow diagnostic. It must not alter the candidate set or ranking.
There is no Dense backfill in any raw-chunk arm. A Guard-on arm with fewer than
five admitted unique articles returns a short evidence set.

Tie breaking is descending reranker score, then original dense raw-chunk rank,
then chunk ID. Quarantined chunks must never be scored.

## Frozen Arms

| Arm | Input | Guard | Rerank depth | Dense backfill |
|---|---|---|---:|---|
| A0_DENSE_BASELINE | Dense article ranking | N/A | N/A | N/A |
| A1_RAW20_GUARD_OFF | Frozen raw prefix | Shadow only | 20 | No |
| A2_RAW20_GUARD_ON | Frozen raw prefix | Enforced | 20 | No |
| A3_RAW50_GUARD_OFF | Frozen raw prefix | Shadow only | 50 | No |
| A4_RAW50_GUARD_ON | Frozen raw prefix | Enforced | 50 | No |

Each rerank quality pass runs twice. Rankings must match exactly or a third
run is required and the variation is reported. Each arm records three latency
passes; the headline p95 is the median of the three run-level p95 values.

## Metrics and Diagnostics

Every arm records macro article Hit@1, Recall@5, nDCG@5, MRR@5, and complete
multi-article coverage at five. The artifact separately records candidate
generation, Guard, reranking, deduplication, and total latency summaries.

Guard diagnostics include input, admitted, quarantined, and scored counts;
affected questions; rule ID histogram; gold-article-associated quarantines;
and short safe result counts. The hard invariant is:

```text
input chunks = admitted chunks + quarantined chunks
scored quarantined chunks = 0
```

## Promotion Rule

Guard-off arms are diagnostic ceilings only and are ineligible for runtime
selection. The global runtime default remains the current fast retrieval path.

Guarded Raw Top-50 is selected as the optional GPU quality profile only if it
improves at least one of Recall@5, nDCG@5, MRR@5, or multi-article completeness
relative to Guarded Raw Top-20; has no quality regression greater than 0.5pp
in Recall@5, nDCG@5, or MRR@5; preserves every Guard invariant; has total p95
at most 650 ms on the local RTX 5060; and has p95 at most three times Top-20.
Otherwise Guarded Raw Top-20 remains the optional GPU quality profile.

If an OFF-to-ON gap exceeds 1pp for Recall@5 or nDCG@5, the result must carry
`GUARD_FALSE_POSITIVE_REVIEW_REQUIRED`. This protocol does not allow changing
Guard rules to recover a benchmark result.

## Claim Boundary

The final documentation may report the paired, consumed retrospective
retrieval replay and its security diagnostics. It must not call Recall@5
answer accuracy, a blind test, independent validation, a production SLA, or a
safe runtime result when it comes from a Guard-off arm.
