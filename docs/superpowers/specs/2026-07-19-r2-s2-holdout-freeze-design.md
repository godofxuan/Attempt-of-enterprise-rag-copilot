# R2-S2 Independent Holdout Freeze Design

Status: `APPROVED FOR IMPLEMENTATION` under the existing R2-S2 authorization.

Date: 2026-07-19

## 1. Problem

R2-S1 uses visible synthetic dev/test cases. They are useful regression evidence but cannot estimate performance on attacks that the Guard developer has not seen. R2-S2 therefore needs a holdout protocol that separates case authorship, freezing, Guard changes, one-time evaluation, and result review.

The repository must provide the protocol and validators without checking the raw holdout into Git. Codex must not author a local holdout and then call it independent.

## 2. Considered Approaches

### A. Local sealed package with a checked-in freezer and verifier

Recommended. An independent reviewer creates a local package. The freezer validates metadata and coverage, binds all payload bytes and the code baseline with SHA-256, and writes an immutable manifest. Raw files remain ignored and forbidden in Git.

Benefits:

- preserves pre-evaluation secrecy;
- makes the exact dataset, rubric, Guard, evaluator, and Git baseline reproducible;
- allows later verification without rerunning a model;
- does not modify the frozen official R2-S1 test cohort.

Limitation: software cannot prove that the author was genuinely independent. The manifest records an attestation, and the project must report it as a process control rather than cryptographic identity proof.

### B. Commit holdout payloads into the public repository

Rejected. This is easy to reproduce but turns the holdout into another visible regression set as soon as it is committed.

### C. Immediately add a third `holdout` split to every evaluator contract

Deferred. This touches dataset, runner, gate, writer, manifest, and CLI schemas before an independent payload exists. It increases migration risk and can accidentally let custom data masquerade as the official frozen test set.

## 3. Package Boundary

Local packages live under:

```text
holdout_submissions/<submission-id>/
```

This path is both Git-ignored and a forbidden public-audit prefix.

Required author-provided files:

```text
case_catalog.json
payload.json
rubric.json
```

Generated once by the freezer:

```text
freeze_manifest.json
```

The freezer refuses an existing manifest and never edits the three input files.

## 4. Case Catalog

`case_catalog.json` is strict metadata, not attack text. It contains:

- schema version and holdout ID;
- one unique `case_id` per case;
- label: `attack` or `benign`;
- one or more attack families or `benign_hard_negative`;
- one or more source surfaces;
- language code;
- an opaque `payload_key` that binds the metadata to `payload.json`.

Required attack-family coverage:

1. `semantic_paraphrase`
2. `cross_chunk_composition`
3. `encoded_unicode`
4. `tool_inducement`
5. `long_context`
6. `metadata_surface`
7. `open_surface`
8. `find_surface`

Required source surfaces are `body`, `metadata`, `parent`, `open`, and `find`. English and Chinese must both be represented.

Admission minimums:

- at least 36 total cases;
- at least 24 attack cases;
- at least 12 benign hard-negative cases;
- every required attack family appears at least twice;
- every required source surface appears at least twice;
- every catalog case has exactly one payload entry and vice versa.

These are protocol admission minimums, not a claim of statistical representativeness.

## 5. Payload and Rubric

`payload.json` is a strict envelope with the same holdout ID and a unique list of `{case_id, payload_key, payload}` objects. `payload` is an opaque JSON object so an independent author can prepare future evaluator inputs without changing the freezer. The freezer checks identity alignment but deliberately does not inspect or optimize attack text.

`rubric.json` freezes four required human-review dimensions:

- semantic instruction following;
- sensitive information disclosure;
- unauthorized action attempt;
- legitimate task completion.

Each dimension defines labels and decision guidance. The rubric also declares blinded primary and secondary reviewer IDs. The secondary review may happen after evaluation, but its role must be assigned before freezing.

## 6. Freeze Manifest

`freeze_manifest.json` records:

- schema version, submission ID, holdout ID, and UTC freeze time;
- SHA-256 and byte count for all three input files;
- case counts and computed coverage counts;
- exact catalog/payload case-ID digest;
- current Git HEAD and branch;
- clean tracked-worktree assertion;
- Guard ruleset path and SHA-256;
- live evaluator path and SHA-256;
- freezer implementation path and SHA-256;
- an explicit separation attestation:
  - author is not the Guard implementer;
  - raw payload was not shown to the Guard implementer before freeze;
  - labels were not changed after observing model results;
  - evaluation is limited to one sealed holdout run per admitted code baseline.

The verifier reloads strict models, recomputes every hash/count/coverage field, checks the exact four-file set, and rejects directory-name or ID contradictions.

## 7. State Machine

```text
DRAFT -> FROZEN -> EVALUATED_ONCE -> REVEALED
```

This implementation covers `DRAFT -> FROZEN` and repeatable FROZEN verification. Evaluation and reveal receipts are later stages because no independently authored package exists yet.

No command may silently overwrite or re-freeze an existing submission. A revised package requires a new submission ID.

## 8. Failure Handling

The freezer fails closed for:

- missing or extra files;
- malformed or duplicate IDs;
- catalog/payload mismatch;
- insufficient family, surface, language, attack, or benign coverage;
- incomplete rubric or reviewer assignment;
- false separation attestations;
- dirty tracked Git state;
- non-commit Git HEAD;
- missing baseline files;
- an existing freeze manifest.

The verifier performs no network, retrieval, embedding, or LLM calls.

## 9. Testing

Tests construct temporary synthetic packages only. They cover:

- a valid 36-case package freezes and verifies;
- hashes, counts, coverage, case-ID digest, code baseline, and exact file set;
- insufficient family/surface coverage rejection;
- catalog/payload mismatch rejection;
- rubric/reviewer rejection;
- false attestation rejection;
- immutable no-overwrite behavior;
- post-freeze payload tampering rejection;
- public audit rejection if a raw holdout path is ever presented as a Git candidate.

## 10. Claims Boundary

After this implementation the project may claim that it has an executable holdout-freezing protocol. It may not claim that an independent holdout exists, has been run, or proves security. Those remain `NOT RUN` until another reviewer supplies and freezes the package.
