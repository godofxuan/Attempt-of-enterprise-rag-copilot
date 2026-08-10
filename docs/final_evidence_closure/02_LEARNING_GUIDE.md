# Final Evidence Closure: Learning Guide

This guide explains what the final closure proves and how to discuss it in an
interview without overstating the evidence.

## 1. Why freeze a baseline first?

A baseline is the control group for engineering work. Record the exact SHA,
environment, command and raw result before editing. Otherwise a later green
run cannot prove which change helped. Here the failed full suite is evidence,
not an embarrassment: it exposed a real Windows concurrency defect.

## 2. What is a file descriptor?

`os.open()` returns a process-local integer that refers to an opened kernel
file object. The path and descriptor are different identities: a path may be
replaced after opening. That is why the code compares `fstat(descriptor)` with
`lstat(path)` before trusting a lock file.

## 3. Why validate links and inode/file identity?

A lock path that is a symlink, reparse point or multi-link file can redirect a
privileged write. The code requires a regular, single-link file and verifies
that the opened descriptor still matches the path. This is a security boundary,
not merely defensive style.

## 4. Why did writing before locking fail?

All four processes executed `if size == 0: write()` concurrently. The lock was
acquired later, so it could not protect that branch. Correct ordering is:
open and validate, acquire exclusive lock, initialize protected state, operate,
unlock, close.

## 5. Why not just retry `PermissionError`?

A retry would reduce observed failures while preserving the invalid protocol.
It could also hide a genuine unsafe ACL or path replacement. Moving the write
inside the lock removes the race by construction; repetition then validates
the hypothesis.

## 6. Directory lock versus OS file lock

A directory lock depends on application cleanup. Hard termination skips
cleanup and creates a stale lock. An OS file lock is attached to an open kernel
handle and is released automatically when the process exits. The file may
remain, but stale bytes are not a held lock.

## 7. Why is PID-based stale detection weaker?

PIDs are reused. A stale owner record might name a PID now belonging to an
unrelated process. Process-start timestamps and host identity help, but the OS
lock already provides the lifecycle guarantee directly and cross-platform.

## 8. What does resumable SQLite prove?

With `commit_interval=1`, each observed checkpoint is a committed transaction.
After killing the writer, restart reads `processed_documents`, continues from
that row, verifies `PRAGMA integrity_check`, hashes the final artifact and only
then activates it. It proves bounded restart recovery for this protocol.

## 9. Atomicity is not durability

Atomic replacement means readers see old or new, not half of each. Durability
means the new directory entry survives power loss. File fsync plus POSIX parent
directory fsync strengthens durability, but the Windows power-loss path was not
simulated. Therefore the report says process-crash atomicity `VERIFIED_LIMITED`
and power loss `NOT_RUN`.

## 10. Why clean stale temp files under a lock?

Without the publication lock, one process can delete another live process's
temp file. Cleanup also validates that each candidate is a normal one-link file
with the exact owned naming pattern, preventing broad or redirected deletion.

## 11. What does target identity add to CI?

Tests answer “does this tree pass?” Target identity answers “is this the tree we
intended to certify?” Verifier v2 checks the exact branch and optionally the
exact SHA. A detached or wrong branch fails even if every test is green.

## 12. Timeout versus deadline

A timeout usually limits one call. A deadline is an absolute end time shared
across steps. This Agent takes the minimum of the request timeout and global
deadline, but it can only observe expiry before or after synchronous code. That
is cooperative cancellation, not forced interruption.

## 13. Retrieval Recall@5

For each question, count how many gold documents appear in the first five
retrieved documents, divided by the number of gold documents. Average over
questions. A score of `0.6111` means about 61.11% of required support documents
were found in top five on average; it is not answer accuracy.

## 14. Citation precision and recall

Citation precision asks what fraction of cited documents are gold support.
Citation recall asks what fraction of gold support documents were cited. The
60-case retrospective subset measured `0.4333` precision and `0.3556` recall.
Both are too low for a positive quality claim.

## 15. Multi-document citation completeness

A case is complete only when every required support document is cited. The 20
multi-document cases scored `0/20`. Later stage attribution localized first
loss to Top-20 retrieval for 7 cases, Top-5 selection for 10, and extractive
response selection for 3. The Controller did search once, but it returned
`answer/completed` in all 20 according to a one-aspect Ledger contract. This is
therefore a mixed retrieval and representation failure, not a generic claim
that orchestration alone failed. See `docs/multidoc_attribution/03_LEARNING_GUIDE.md`.

## 16. Why answer correctness is `NOT_RUN`

The immutable prior WixQA run stored document IDs and metrics but not the system
answer text. You cannot reconstruct semantic correctness from citation IDs or
answered rate. Token overlap would reward verbosity and copying, so it was not
used as a fake accuracy metric. Twelve cases require two independent humans.

## 17. Why not aggregate all security datasets?

The custom synthetic and garak runs use different fixtures, model identities
and histories. Adding their numerators creates a denominator that never existed
in one experiment. The requested 60/30 blind holdout is therefore `NOT_RUN`;
the valid narrow 12-attack garak claim remains separate.

## 18. How negative results improve the project

RRF, a generic cross-encoder, typed numeric planning and the current Agent route
were rejected because measured quality or latency failed gates. This shows
industrial judgment: the default system changes only when a candidate produces
reproducible benefit. “Implemented then disabled with evidence” is stronger
than listing another framework with no causal result.

## Interview answer template

> I began with a clean exact-SHA baseline and reproduced a Windows-only
> concurrency failure. The lock byte was initialized before exclusion, so I
> moved initialization under the OS lock and changed the FTS stale directory
> lock to a kernel-managed file lock. I verified 30 hard-kill resumptions and 12
> active-pointer crash stages with hashes and integrity checks. On quality, the
> 60-case WixQA subset showed no Recall@5 gain and poor citation completeness,
> so I rejected the Agent route instead of claiming improvement. The safe
> resume claims remain narrow external retrieval and injection-defense metrics.
