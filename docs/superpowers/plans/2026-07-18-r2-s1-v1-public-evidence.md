# R2-S1 V1 Redacted Public Evidence Implementation Plan

Date: 2026-07-18

Status: approved for implementation; V2-V5 remain out of scope.

## Goal

Export the frozen D7 live run `r2-s1-d7-test-20260718-01` into a tracked,
content-free evidence package that a reviewer can copy to a clean directory and
verify with Python's standard library alone.

The source manifest SHA-256 is pinned to:

```text
5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

## Non-goals and frozen boundaries

- Do not modify the frozen security dataset, fixture manifest, or freeze manifest.
- Do not modify Guard rules, keywords, thresholds, budgets, or detector version.
- Do not rerun or overwrite the formal D7 run.
- Do not publish prompts, retrieved text, model output, canary values, nonces,
  local paths, environment variables, credentials, or endpoint details.
- Do not begin V2 scan-provenance, V3 socket, V4 metric-semantic, or V5 arm-order
  work.
- Do not commit, push, merge, or tag without a separate approval.

## Design

### Public writer

Add `app/evaluation/indirect_injection_public_writer.py` with strict frozen
Pydantic models for the public manifest, per-case evidence, metrics, and metric
definitions. The exporter will:

1. Require the pinned source manifest hash.
2. Parse and validate the complete source run with the existing live-run writer
   contract before reading any rows.
3. Project source rows through an explicit field allowlist; it will never copy a
   source mapping wholesale.
4. Sort rows deterministically by case ID and guard mode.
5. Recompute the public summary from projected rows rather than copying the
   private summary.
6. Write into a same-parent staging directory, validate the complete package,
   atomically reserve a nonexistent target directory, and create every target
   file in exclusive mode so a raced destination is never replaced.

### Standalone verifier

Add `app/evaluation/indirect_injection_public_verifier.py` using only Python's
standard library. The exact same source is copied into the package as
`verify.py`. It will validate:

- the exact eight-file package contract;
- every checksum without a self-referential checksum entry;
- strict JSON object keys and primitive types;
- 72 unique rows and 36 complete OFF/ON pairs;
- pair-level input and retrieval-order fingerprints;
- public source hash provenance;
- every published numerator, denominator, and rate by recomputation;
- `null` rates when a denominator is zero.

Thin CLI wrappers will be added under `scripts/` for export and repository-local
verification.

### Public package

The immutable target is `data/v2/public/r2_s1_d7/` and contains exactly:

```text
README.md
manifest.redacted.json
summary.json
per_case.redacted.jsonl
metric_definitions.json
source_run.sha256
checksums.sha256
verify.py
```

## TDD sequence

1. Add writer tests for pinned provenance, exact metrics, deterministic ordering,
   redaction, traversal rejection, overwrite rejection, and zero denominators.
2. Run the focused writer tests and retain the expected import/behavior failures
   as RED evidence.
3. Implement the writer and export CLI; rerun focused tests to GREEN.
4. Add verifier tests for tampering, checksums, strict files/schema, recomputation,
   and clean-directory execution.
5. Run verifier tests to RED, implement the verifier, and rerun to GREEN.
6. Export the frozen formal run exactly once to the tracked target.
7. Copy only the resulting package to a temporary clean directory and execute
   `python verify.py` there.
8. Run focused tests, the wider test suite, public-repository audit, frozen hash
   checks, and Git diff/status inspection.

## Acceptance criteria

- The package independently reproduces the documented D7 counts, including
  OFF `7/24`, raw signal `3/24`, user-visible success `3/24`; ON zeros; reached
  `15/28`; conditional quarantine `15/15`; unreached `13/28`; benign quarantine
  `0/32`; clean `12/12`; mixed `20/20`; and poison-only filtered `4/4`.
- No frozen source content or machine-local detail appears in any package file.
- One-byte or one-value tampering makes verification fail.
- Re-export to an existing target fails instead of overwriting it.
- A second export to a fresh target is byte-for-byte deterministic.
- The standalone verifier succeeds with only the eight package files present.
