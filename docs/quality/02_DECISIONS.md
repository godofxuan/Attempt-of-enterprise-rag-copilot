# R2-S8 Decisions

## ADR-QE-001 - Separate quality evidence from the legacy CSV

Status: ACCEPTED

The legacy `human_review.csv` remains supported as an informal inspection
artifact. A new strict schema and publisher own independent quality evidence.
Changing the legacy format in place would blur old and new evidence semantics.

## ADR-QE-002 - Blind machine metadata, not the reference rubric

Status: ACCEPTED

Reviewers may receive the frozen expected response mode, reference answer, and
authorized reference evidence needed to grade consistently. They must not
receive model identity, variant, machine pass/fail, machine failure stage, or
source case IDs. This is outcome grading with a reference, not preference
ranking between named models.

## ADR-QE-003 - Keep security gates deterministic

Status: ACCEPTED

Human and model graders can add semantic evidence, but they cannot override
authorization, forbidden-content, secret-leak, or unsafe-action failures.

## ADR-QE-004 - No fabricated completion

Status: ACCEPTED

Fixture judgements may test software behavior only. They are marked
`fixture_only` and are excluded from project quality claims. G5 requires real,
independently supplied human judgements.

## ADR-QE-005 - Separate source bytes from displayed evidence text

Status: ACCEPTED

Cross-platform newline normalization means a source artifact's byte hash can
differ from the hash of the text shown to a reviewer. Both are stored and
validated. Conflating them either rejects valid Windows inputs or hides a
transformation.

## ADR-QE-006 - Human retrieval grades are ordinal

Status: ACCEPTED

Every document in the declared candidate pool is graded
`0/1/2/uncertain`. This supports human precision@5, recall@5, nDCG@5, raw
agreement, and weighted kappa. Binary generated
`gold_doc_ids` remain useful for regression recall but are not treated as
independent relevance truth.

## ADR-QE-007 - Reliability precedes quality

Status: ACCEPTED

Release logic first evaluates sample size, reviewer agreement, unresolved
disagreement, and uncertainty. Quality thresholds are evaluated only after the
labels are reliable enough. This distinguishes `INCONCLUSIVE` evidence from a
reliably measured `FAILED` system.

## ADR-QE-008 - Evidence bundles must be recomputable

Status: ACCEPTED

A summary-only artifact is insufficient. The private evidence bundle carries
the packet, original pseudonymous submissions, optional adjudication, and
summary. Verification recomputes the summary and decision from source labels.

## ADR-QE-009 - LLM judge has no release or security authority

Status: ACCEPTED

The LLM judge is an auxiliary semantic scorer calibrated against resolved human
labels. It cannot create its own gold, adjudicate human disagreement, replace
ACL/secret/unsafe-action rules, or approve a release. The schema fixes both
`security_gate_authority=none` and `release_authority=false`.

## ADR-QE-010 - Judge calibration requires repeated fixed trials

Status: ACCEPTED

At least three runs with identical model digest, prompt hash, inference-config
hash, and packet binding are required. A single perfect-looking run is
`INCONCLUSIVE` because stochastic stability cannot be measured.

## ADR-QE-011 - Reviewer pseudonyms share one identity domain

Status: ACCEPTED

Per-reviewer random salts protect identity but let one person generate multiple
hashes. One coordinator-held CSPRNG pepper is now reused only for identity
pseudonymization within a campaign. Submissions carry the pepper's SHA-256 as
an identity-domain identifier and use HMAC-SHA256 for the reviewer pseudonym.
Aggregation rejects mixed domains. This is a technical duplicate check, not a
substitute for organizational confirmation that two real people participated.

## ADR-QE-012 - The current review is reference-guided

Status: ACCEPTED WITH LIMITATION

Reviewers see the expected response mode, reference answer, and authorized
reference evidence. This supports consistent criterion-based grading but may
anchor refusal judgements. The packet is blind to model identity and machine
verdicts; it is not verdict-blind. A verdict-blind research arm would require a
separate versioned protocol and must not be inferred from this evidence.

## ADR-QE-013 - Separate agreement statistics by meaning

Status: ACCEPTED

Raw agreement is a macro-average across dimensions, Cohen's kappa is calculated
only for overall acceptability, and retrieval uses ordinal weighted kappa.
Heterogeneous labels are no longer pooled into one candidate-count-dominated
kappa.

## ADR-QE-014 - Uncertainty is conservative, not removable

Status: ACCEPTED

An uncertain returned grade is treated as 0 while the same candidate is treated
as 2 in the ideal candidate pool. This lower-bound convention keeps the query
in precision, recall, and nDCG while the separate uncertainty gate records the
measurement weakness.

## ADR-QE-015 - Held-out acceptance currently requires all cases

Status: ACCEPTED

The stratified sampler does not bind population stratum sizes or inclusion
probabilities. It remains valid for rubric calibration, but held-out population
claims require `all_cases` until weighted-estimator provenance is implemented.

## ADR-QE-016 - Cross-root publication is recoverable, not atomic

Status: ACCEPTED

The public packet and private control map live under different roots, so one
filesystem rename cannot atomically commit both. A retry verifies the complete
existing packet against current source/spec and publishes only a missing
control map; exact existing controls are idempotent, and mismatches fail closed.

## ADR-QE-017 - Hash-bound text artifacts use canonical LF bytes

Status: ACCEPTED

Artifact hashes bind bytes, not logical text. Every generated text artifact
must therefore choose an explicit newline convention before hashing. CSV output
uses `lineterminator="\n"`, matching the repository's LF policy. A released
packet with a clean-checkout hash mismatch is rejected and replaced under a new
packet ID; its manifest is never edited to conceal the failure.

## ADR-QE-018 - CI evidence must exist in the tracked tree

Status: ACCEPTED

A test that reads ignored local evidence is not reproducible even when it passes
on the producer's machine. Formal public evidence referenced by repository tests
must be tracked or packaged self-contained. Ignore exceptions are narrow:
only named immutable G10 runs and six exact manifest-bound synthetic metadata
files are public. CI validity is checked from an exported Git index with the
normal operating-system TEMP location, not from the enriched development tree.

## ADR-QE-019 - Linux no-replace publication uses a kernel primitive

Status: ACCEPTED

A user-space `destination.exists()` check followed by `os.rename()` has a race
window and POSIX rename may replace an existing empty directory. Linux therefore
uses `renameat2(RENAME_NOREPLACE)` for atomic collision enforcement. Windows
keeps its native no-replace rename and bounded sharing-denial retry. The
preflight-check fallback exists only for platforms where the stronger primitive
is unavailable and does not upgrade their concurrency guarantee.

## ADR-QE-020 - Coordinator secrets belong to the effective operator identity

Status: ACCEPTED

The default real campaign initializer compares the effective Windows token
account with the intended host account before creating a pepper or identity
file. The CLI enforces this for every output root. Unit tests isolate the
low-level file contract with explicit temporary roots and replace only the
external identity check; a delegated Codex process cannot create a real
coordinator directory. This prevents a technically private ACL from locking the
actual operator out while preserving the existing current-user-plus-SYSTEM
private ACL policy.

Identity placeholders are phase-controlled rather than immutable. Their exact
paths are manifest-bound and they must be empty at readiness; the coordinator
then populates them for pseudonym generation. Hashing their initial empty bytes
as permanent artifacts would incorrectly classify the required transition as
tampering.
