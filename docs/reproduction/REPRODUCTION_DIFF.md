# WixQA Reproduction Difference Record

## Attempt 1

- Registered protocol commit: `e08d134`
- Run prefix: `wixqa-clean-v1`
- Result: stopped before indexing
- Error: official `wixqa_synthetic/test.jsonl` byte count did not match the
  historical Windows manifest
- Historical bytes: 6,222,585
- Official direct-download bytes: 6,216,364
- Difference: 6,221 bytes for 6,221 records

The same one-byte-per-record difference exists for Simulated and ExpertWritten.
Byte inspection proved that historical question files use CRLF while direct
official files use LF. The corpus file is byte-identical. Parsing every question
row and serializing canonical JSON produced identical row streams and identical
derived question IDs for all three cohorts.

This was not treated as a quality failure, ignored hash, or reason to alter
retrieval parameters. Attempt 1 remains a failed transport-identity replay.

## Corrective protocol

The historical manifest remains unchanged because it binds historical evidence.
`WIXQA_OFFICIAL_RAW_MANIFEST.json` separately binds official direct-download LF
bytes. `WIXQA_SOURCE_TRANSPORT_EQUIVALENCE_V1.json` proves canonical row
equivalence. `WIXQA_CLEAN_RETRIEVAL_PROTOCOL_V2.json` changes only the manifest
transport identity; all questions, corpus content, model, chunking, candidate
count, RRF configuration, metrics, and quality tolerance remain frozen.

Attempt 2 must use four new roots and must be committed before quality results
are observed. If quality differs at tolerance zero, the final state is
`REPRODUCTION_GAP`; no parameter tuning is permitted.

## Attempt 2

- Registered transport-corrected protocol commit: `4d07d6a`
- Run prefix: `wixqa-clean-v2`
- Source: direct official LF files at WixQA commit `d662dc4`
- Source, index, embedding cache, and eval roots: newly absent before execution
- Historical private artifacts used as input: `false`
- Fresh index: 6,221 articles, 11,975 chunks, 1024 dimensions
- Fresh embedding cache: all 11,975 chunk embeddings computed
- Quality tolerance: `0.0`
- Quality differences: `0`
- Result: `VERIFIED`

All seven frozen quality metrics for all three retrieval arms and all three
cohorts exactly match historical public v2 evidence. ExpertWritten Dense remains
66.4167% Recall@5 and 52.1583% nDCG@5. Candidate latency is reported as a new
machine-specific observation, not an exact-reproduction requirement: Dense p95
was 153.559 ms versus the historical 157.406 ms.

This is a clean local regression replay of already consumed fixed public labels,
not an independent third-party reproduction and not a new blind holdout.
