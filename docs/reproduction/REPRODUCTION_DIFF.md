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
