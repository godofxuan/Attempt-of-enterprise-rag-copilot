# Final Safe Raw-Chunk Reranking Results

## Decision

`WIXQA_RERANKER_TUNING_CLOSED`

The optional GPU quality profile is `GUARDED_RAW_CHUNK_TOP20`. The fast
retrieval path remains the global runtime default. Guarded Top-50 improves
retrieval quality, but failed the protocol's RTX 5060 total-p95 gate.

This is a consumed, retrospective WixQA ExpertWritten retrieval replay. It is
not blind validation, answer accuracy, a production SLA, or a reason to remove
the retrieved-content Guard.

## Experiment Identity

| Field | Value |
|---|---|
| Protocol commit | `0c8d5e0f0ab5121f41f9f79fb861f54e67d28d62` |
| Evaluation commit | `57df9845a198b37ce262001c2d4d08a31378dc2b` |
| Manifest SHA-256 | `d325412340c110d3f76b832080c702978643d517e296c97bba1abc088ec65b1f` |
| Index manifest SHA-256 | `e6b5f2a9e6e91e47f3601c015d4309742abbacd3c30343814ed60ca5da038ad9` |
| Frozen candidate SHA-256 | `73d5f994b6553e823914ccc98c247e1c953bfa81c2c90a1a97b67db26595f136` |
| Embedding | `bge-m3`, digest `790764...2146bab` |
| Reranker | `BAAI/bge-reranker-v2-m3@953dc6f...` |
| Reranker weights SHA-256 | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` |
| Environment | RTX 5060, CUDA 12.8, PyTorch `2.11.0+cu128`, FP16, batch 16, max length 512 |
| Public evidence SHA-256 | `a879ca0f825f1780c75a104285a8f870f20ca3aa2e45f874555ebdbb87346b80` |

The official LF WixQA source contains 6,221 articles and the replay contains
200 questions with 258 gold article labels. Candidate generation happened once
before any arm; every Top-20 input is the first 20 items of the same frozen
Top-50 prefix. Raw candidate text and per-question rankings remain private.

## Audit Finding

`WixQARawChunkReranker` performs the intended order: full-text Guard scan,
ADMIT-only scoring, descending cross-encoder score, then article deduplication.
The historical evaluator was not suitable for the final comparison because it
backfilled Dense article IDs and used a 1,200-character pre-truncation. The
final evaluator has neither behavior: it has no Dense backfill and sends full
Guard-admitted text to the tokenizer, which truncates at 512 tokens.

## Paired Five-Arm Results

| Arm | Hit@1 | Recall@5 | nDCG@5 | MRR@5 | Complete@5 | Quarantined chunks | Short result sets | Total p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A0 Dense baseline | 35.00% | 66.42% | 52.16% | 49.61% | 16/52 (30.77%) | N/A | 0 | 44.41 ms |
| A1 Raw Top-20, Guard OFF | 45.00% | 72.75% | 59.56% | 58.17% | 18/52 (34.62%) | Shadow: 35 | 0 | 280.83 ms |
| A2 Raw Top-20, Guard ON | 44.50% | 72.50% | 59.35% | 57.92% | 17/52 (32.69%) | 35 | 0 | 296.48 ms |
| A3 Raw Top-50, Guard OFF | 44.50% | 74.75% | 60.31% | 58.57% | 19/52 (36.54%) | Shadow: 123 | 0 | 642.51 ms |
| A4 Raw Top-50, Guard ON | 44.00% | 74.50% | 60.09% | 58.32% | 18/52 (34.62%) | 123 | 0 | 677.93 ms |

Quality rankings were identical in two independent runs. Total latency is the
median of three run-level p95 values, calculated per question as candidate
generation plus enforced Guard plus reranker plus post-rerank deduplication.
Model loading is excluded.

## Guard Impact

Top-20 Guard ON versus OFF costs `0.25pp` Recall@5 and `0.21pp` nDCG@5. Top-50
costs `0.25pp` Recall@5 and `0.22pp` nDCG@5. Neither gap exceeds the frozen
`1pp` false-positive-review threshold.

The Top-20 candidate prefixes contained 35 quarantined chunks across 22
questions; four quarantined chunks belonged to gold articles. Top-50 contained
123 quarantined chunks across 61 questions; eight belonged to gold articles.
In both Guard-on arms, `scored_quarantined_chunks = 0` and no unscanned Dense
backfill occurred.

## Top-20 Versus Top-50

Top-50 raises safe Recall@5 from `72.50%` to `74.50%`, nDCG@5 from `59.35%` to
`60.09%`, and complete multi-article coverage from `17/52` to `18/52`. It also
raises total p95 from `296.48 ms` to `677.93 ms`. This exceeds the predeclared
`650 ms` limit, so Top-50 is a stronger offline safe retrieval point, not the
interactive GPU profile.

Top-20 stage p95 is candidate generation `44.41 ms`, Guard `18.30 ms`,
reranker `238.95 ms`, and dedup `0.04 ms`. Top-50 is candidate generation
`44.41 ms`, Guard `44.47 ms`, reranker `596.50 ms`, and dedup `0.07 ms`.

## Resume Boundary

Safe detailed wording:

> On a consumed 200-question WixQA ExpertWritten retrieval replay with frozen
> raw candidates, a Guard-before-rerank BGE profile improved Recall@5 from
> 66.42% to 72.50%, nDCG@5 from 52.16% to 59.35%, and MRR@5 from 49.61% to
> 57.92%; the local total p95 was 296.48 ms.

Do not claim `74.75%` or `75.00%` as a safe runtime result: those are Guard-off
diagnostic ceilings. Do not call any of these values answer accuracy, blind
validation, independent validation, or a production SLA.

## Fresh Validation

`NOT_RUN`. The WixQA ExpertWritten labels were already consumed before this
closure. A future fresh human-authored, label-frozen evaluation may compare the
fast default with the selected Guarded Top-20 profile once; it is outside this
closed reranker phase.

See the [frozen protocol](RAW_CHUNK_GUARD_FINAL_PROTOCOL.md) and the
[sanitized aggregate evidence](raw_chunk_guard_final_evidence.json).
