# EnterpriseRAG FTS Activation Contract

## Declared operating model

The EnterpriseRAG FTS5 builder is a `SINGLE_WRITER_OFFLINE_BUILDER` with
`ATOMIC_ACTIVATION`. It is not a distributed indexing service and does not
support two builders sharing one output root.

## Build and activation sequence

1. Validate the bounded `run_id` before creating paths.
2. Atomically create `.single-writer-build.lock` at the index root. A second
   builder fails before opening the staging SQLite database.
3. Build or resume `versions/.<run_id>.building/index.sqlite3` only when corpus,
   dataset-manifest, and expected-count metadata match.
4. Mark the SQLite build complete and close the writer.
5. Write the manifest and verify artifact byte count, SHA-256, SQLite integrity,
   row counts, and ordered-record hash.
6. Move the verified staging directory to `versions/<run_id>` with `os.replace`.
7. Write a temporary active pointer and atomically replace `active.json`.
8. Release the single-writer lock in `finally`.

## Failure behavior

- A normal exception or injected interruption releases the build lock and leaves
  committed staging rows available for a metadata-bound resume.
- An interrupted build does not create the final version and does not change the
  active pointer.
- A verification failure leaves the candidate in staging and does not change the
  active pointer.
- A concurrent builder fails fast; it never shares the staging SQLite file.
- A hard process or machine crash can leave the lock directory as an explicit
  stale-owner signal. Operators must establish that the recorded PID is no
  longer running before removing it; automatic lock stealing is intentionally
  not implemented.
- A failure after version publication but before active-pointer replacement can
  leave a valid inactive version. Readers continue using the old active pointer.

## Tests

`tests/external_datasets/test_enterprise_rag_bench_fts.py` covers committed
resume, metadata mismatch, interruption, verification failure, concurrent
builder rejection, path traversal, index verification, and active loading.

This contract is sufficient for the current local/offline benchmark builder. It
does not claim distributed locking, online concurrent indexing, or a production
multi-writer service.
