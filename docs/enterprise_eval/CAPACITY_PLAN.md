# Enterprise Evaluation Capacity Plan

## Measured local envelope

Pre-flight observations on `2026-08-09`:

- Repository/data drive: `D:`
- Free space: `68.93 GiB`
- GPU: NVIDIA GeForce RTX 5060
- Reported GPU memory: `8151 MiB`
- Existing local embedding service: Ollama/BGE-M3 is supported, but model
  availability and digest must be captured per live run.

No new benchmark data may be cached on `C:`. The root is:

`<repository>/.private/external/<dataset>`

## Acquisition gates

| Benchmark | Data risk | Initial action | Formal-run gate |
|---|---|---|---|
| WixQA | Low; thousands of articles and hundreds/thousands of QA rows | Acquire full official assets | File hashes, counts, schema, and fresh-cache smoke pass |
| EnterpriseRAG-Bench | High; >500k heterogeneous documents plus indexes | Metadata/size inspection first | Raw + canonical + index + 20% headroom fit on `D:`; bounded build time; resumable index; full corpus used |
| HERB | Medium/high; 39k artifacts plus model execution | License/use review and archive-size inspection | Data terms accepted, all required artifacts fit, bounded Agent run budget defined |
| DocLayNet | Very high; official assets are tens of GiB | Do not download in E0-E3 | Optional deterministic subset method and storage headroom approved in E8 |

## EnterpriseRAG-Bench planning assumptions

The official repository states slightly over 500,000 documents. Before any
download, the adapter must obtain official archive metadata and calculate:

1. compressed raw bytes;
2. expanded raw bytes;
3. canonical JSONL bytes;
4. estimated chunk count from a deterministic sample;
5. dense vector bytes = `chunks * dimensions * bytes_per_component` plus index
   overhead;
6. lexical index bytes;
7. temporary build/checkpoint space;
8. at least 20% free-space reserve after build.

If the full formal corpus does not fit, the project may run a deterministic
`PIPELINE_DEBUG` subset but must not report a formal benchmark score or claim a
500k-document evaluation.

## E2 measured qualification

Official Hugging Face revision:
`69916e31c68aa5963c00248fd7f0bc12d04fd235`.

Measured/official facts on `2026-08-09`:

- questions: 500 rows, 408,737 bytes, locally verified SHA-256
  `e25066f4eff3843dd0f3df0d1348113471e072e75007ffe390a0aa83f2a80af2`;
- documents: 511,962 rows and 1,409,893,131 bytes, locally verified SHA-256
  `6b0747bf160af9427b12101537d53056ac592ada9831c1a98ae01fa50a8d2a9f`;
- host RAM: 31.62 GiB total, approximately 16.95 GiB free during audit;
- `D:` free space: approximately 68.9 GiB before a full corpus download.

The streaming profiler scanned every row without using question labels. With
the frozen flat `1,800` character / `150` overlap control it measured:

| Item | Measured or deterministic estimate |
|---|---:|
| Documents / unique source IDs | 511,962 / 511,958 |
| Flat chunks | 1,702,370 (3.325188/document) |
| One 1,024-d float32 vector matrix | 6.49 GiB |
| Embedding cache + FAISS vector copy | 12.99 GiB |
| Python BM25 token objects, fixed 2% hash sample extrapolation | 36.60 GiB |
| Capacity-profiler peak working set | 1.68 GiB |
| Embedding time at measured 41.5 chunks/second | 11.39 hours |

The profiler also found 15 empty titles, one empty body, and four reused source
IDs whose records differ. The adapter preserves these records using a hash-bound
internal ID and records empty-field fallbacks in metadata. One reused ID is the
duplicated gold ID in `qst_0413`.

This changes the decision from `CORPUS_NOT_ACQUIRED` to
`CORPUS_VERIFIED_INDEX_CAPACITY_BLOCKED`. Disk capacity is sufficient, and
streaming parsing is proven, but the existing builder is not safe because its
Python BM25 representation alone exceeds total host RAM. A formal quality score
requires a disk-backed/sharded lexical index, memory-mapped or sharded dense
vectors, resumable embedding checkpoints, and a measured full-build peak below
the local memory envelope. No 500k-document quality claim is allowed yet.

Two attempted Git metadata checkouts were stopped before corpus acquisition:
one ordinary checkout risked fetching all blobs, and one partial clone's checkout
triggered promisor fetches. The official Hugging Face question parquet and HEAD
metadata were used instead. These attempts created no formal dataset artifact or
score.

The first full profiler attempt stopped after exposing an official empty-title
record that violated the adapter's overly strict raw schema. The raw contract was
corrected to preserve official empty fields, normalized fallbacks became explicit,
and a second pass exposed the missing Windows RSS dependency. The final pass used
the native Windows process-memory API and completed with non-zero peak RSS. These
are data-contract and observability corrections, not discarded runs.


## Runtime controls

- Download and indexing are resumable and content-addressed.
- Every stage writes to a temporary target and atomically activates only after
  count/hash validation.
- Batch size and concurrency are bounded by observed GPU/RAM behavior.
- Evaluation checkpoints are hash-chained and can resume without re-consuming
  completed labels.
- Model name, digest, embedding dimension, seed, hardware, commands, index build
  time, query latency, and artifact hashes are recorded.
