# G9 Enterprise Lifecycle Evidence

This directory contains the sanitized public evidence for the G9 lifecycle
scenario.

The source bundle is wholly fictional. Its email identities use the reserved
`example.invalid` domain. The loader verifies canonical JSON, contained paths,
regular-file descriptors, byte budgets, SHA-256 bindings, UTF-8 encoding, and
the fictional identity policy before returning any event.

The end-to-end test exercises:

1. initial ingest, build, and activation;
2. exact event replay after restart while source files are unavailable;
3. one update and one deletion;
4. a pending immutable target snapshot;
5. compare-and-swap activation and stale-activation rejection;
6. active-index deletion-residue checks across documents, parent/indexed
   chunks, BM25/FAISS row mappings, source bindings, and retrieval;
7. rollback and restoration of a fixed-query fingerprint.

`summary.json` contains only stable public invariants. Random secure-staging
asset identities intentionally do not appear in it. Within one accepted state,
exact retry plan and publication identities must match; across fresh isolated
runs, those random-derived identities are not claimed to match.

`checksums.sha256` binds the public summary to the exact canonical manifest and
fictional source files used by the test. CI recomputes every listed digest.

The embedding backend used by this fixture is deterministic test code. This
proves lifecycle correctness and reproducibility, not retrieval quality,
latency, throughput, or production-model performance.

Verify the source bundle without Ollama, a network connection, or JWT setup:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_enterprise_bundle
```

Run the complete scenario:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\lifecycle\test_enterprise_e2e.py -q
```
