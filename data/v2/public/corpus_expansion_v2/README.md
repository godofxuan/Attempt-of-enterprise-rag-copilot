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

The checksums detect accidental or unreviewed artifact changes. They are not a
third-party signature and do not independently prove that the local run
occurred. The checked-in generator, facts, profile, tests, CI gate, index
manifest, and frozen evaluation summaries together provide the reproducible
evidence chain.
