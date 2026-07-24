# Expanded corpus v2 public evidence

This package is a compact, public-safe projection of the local corpus
expansion acceptance run. It does not contain generated enterprise documents,
raw model responses, credentials, or local filesystem paths.

## Scope

- Profile: `expanded`
- Source documents: 240
- Canonical documents after duplicate governance: 216
- Policies / versions / atomic facts: 20 / 40 / 104
- Active facts: 52
- Active-fact supporting/evaluation coverage: 100% / 100%
- Departments: 12
- Embedding model: local `bge-m3`, 1024 dimensions
- Frozen evaluation cases: 48 dev + 56 test

## Files

- `quality.json`: deterministic corpus breadth and quality gates.
- `manifest.json`: exact code, facts, profile, corpus, index, dataset, and
  evaluation hash bindings.
- `index_manifest.json`: immutable local index build manifest.
- `retrieval_dev_summary.json`: live BGE-M3 retrieval result on dev.
- `retrieval_test_summary.json`: live BGE-M3 retrieval result on frozen test.
- `checksums.sha256`: SHA-256 integrity checks for package content.
- `verify.py`: dependency-free integrity and semantic verifier.

## Verify

From the repository root:

```bash
python data/v2/public/corpus_expansion_v2/verify.py
```

Expected output:

```json
{"profile_id": "expanded", "verified": true}
```

The verifier rejects unknown/missing fields, changed release values, broken
cross-artifact bindings, and checksum mismatches. Its frozen manifest binds the
evidence to implementation commit
`184913e5e504b150d3959ae541cc808544ac379e`.

The live retrieval manifests captured commit
`e657beaf7d184409b2d7574c974733cbd7233f4e` with a dirty worktree because the
corpus expansion was still under review. Commit `184913e` is the reviewed,
post-run implementation snapshot and preserves the accepted generated corpus,
index, and dataset hashes. This package therefore does not claim that the live
run originated from a clean checkout of `184913e`.

Checksums are not a third-party signature and do not independently prove that
the local run occurred. Git object integrity, the checked-in generator, exact
hash bindings, tests, CI gate, and frozen evaluation summaries together form
the reproducible evidence chain.
