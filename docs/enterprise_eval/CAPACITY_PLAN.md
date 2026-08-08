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
- documents: 511,962 rows and an exact remote content length of
  1,409,893,131 bytes; not downloaded and no local SHA-256 yet;
- host RAM: 31.62 GiB total, approximately 16.95 GiB free during audit;
- `D:` free space: approximately 68.9 GiB before a full corpus download.

Conservative vector-only scenarios for 1,024-dimensional float32 BGE-M3:

| Average chunks/document | Chunk count | One vector matrix | Cache + FAISS vectors |
|---:|---:|---:|---:|
| 1 | 511,962 | 1.95 GiB | 3.91 GiB |
| 2 | 1,023,924 | 3.91 GiB | 7.81 GiB |
| 3 | 1,535,886 | 5.86 GiB | 11.72 GiB |

Disk is probably sufficient after reserving 20%, but the current in-memory
builder is not yet qualified: it simultaneously materializes documents, chunks,
BM25 Python token objects, the embedding matrix, and FAISS. With only 16.95 GiB
free during audit, the 2-3 chunk scenarios risk memory exhaustion. Formal E2 is
therefore `CAPACITY_BLOCKED` until a streaming sample measures actual chunk/token
distribution and the builder proves bounded peak RSS. The 1.41 GB raw corpus is
not itself the limiting factor.

Two attempted Git metadata checkouts were stopped before corpus acquisition:
one ordinary checkout risked fetching all blobs, and one partial clone's checkout
triggered promisor fetches. The official Hugging Face question parquet and HEAD
metadata were used instead. These attempts created no formal dataset artifact or
score.


## Runtime controls

- Download and indexing are resumable and content-addressed.
- Every stage writes to a temporary target and atomically activates only after
  count/hash validation.
- Batch size and concurrency are bounded by observed GPU/RAM behavior.
- Evaluation checkpoints are hash-chained and can resume without re-consuming
  completed labels.
- Model name, digest, embedding dimension, seed, hardware, commands, index build
  time, query latency, and artifact hashes are recorded.
