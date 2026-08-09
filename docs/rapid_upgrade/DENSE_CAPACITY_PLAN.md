# Enterprise Dense Capacity Qualification

## Entry reason

The fast-track multi-document development ablation is not promotable: it raises
completeness but materially lowers citation precision and there is no unconsumed
validation cohort. EnterpriseRAG-Bench B0 also has a measured semantic retrieval
failure: 80 of 125 semantic questions are zero-recall at top five. This satisfies
the conditional entry rule for a Dense capacity check; it does not authorize a
full build.

## Frozen representation

- corpus: EnterpriseRAG-Bench revision
  `69916e31c68aa5963c00248fd7f0bc12d04fd235`;
- documents: `511,962`;
- flat chunks: `1,702,370`, using `1,800` characters and `150` overlap;
- embedding: existing local BGE-M3 only, pinned by Ollama digest;
- vector shape: 1,024-dimensional `float32`;
- raw matrix: `6,972,907,520` bytes (approximately 6.49 GiB);
- matrix plus a second flat-index copy: approximately 12.99 GiB;
- no reranker, query rewrite, fusion tuning, new model, or vector database.

## Qualification protocol

Run one cumulative, source-order stream at checkpoints `1,000`, `10,000`, and
`50,000` chunks. The timer includes deterministic flat chunk extraction, local
Ollama transport, vector decoding, float32 materialization, and output hashing.
The model startup probe is excluded. Batch size is fixed at 32.

Record elapsed time, chunks/second, input characters, returned vector bytes,
process peak RSS, model identity, dimension, corpus hash, hardware, free disk,
and a SHA-256 digest over every returned vector.

## Pre-registered full-run gate

A full 1,702,370-chunk build is allowed in this rapid sprint only if all are true:

1. every checkpoint completes with zero embedding errors and fixed dimension;
2. 50k throughput is at least 80% of 10k cumulative throughput;
3. projected embedding wall time is at most 8 hours;
4. projected artifacts plus 20% reserve fit on `D:`;
5. a resumable, checksummed, deterministic sharded/mmap builder exists before
   the first full-corpus vector is written;
6. a development-safe quality protocol exists independently of the already
   consumed 470-question fixed regression set.

Failure of any gate produces `FULL_DENSE_NO_GO`. The 1k/10k/50k measurements
remain capacity evidence, not retrieval-quality or production-throughput claims.
