# R2-S7 Secure Knowledge Lifecycle Stage Contract

Status: G0-G10 complete; R2-S7 accepted with one local disk-hygiene exception

Baseline commit: `d465eedb80cae4bc7b2e3be71b782ad565cc188e`

Target branch: `codex/rag-eval-system`

## 1. Stage Objective

R2-S7 must prove that enterprise knowledge additions, updates, deletions,
conflicts, and build failures can be handled without mutating the active index,
crossing tenant boundaries, or leaving deleted content in the newly activated
snapshot.

The accepted product claim after closeout is limited to:

> An enterprise Agentic RAG prototype with governed ingestion, revision
> management, incremental compute reuse, immutable index publication, deletion,
> rollback, and exact-SHA evidence.

This stage does not establish production readiness or performance on private
enterprise data.

## 2. Scope

### REQ-LC-001 - Preserve Current Index Publication Contracts

Keep immutable index versions, validated manifests, content-addressed artifact
checks, atomic active-pointer replacement, explicit rollback, and failure
isolation.

### REQ-LC-002 - Establish Canonical Source Events

Represent UPSERT and DELETE as strict, bounded, timezone-aware, deterministic
events. Replays of the same event and payload are idempotent; reuse of an event
ID with a different payload is an explicit conflict.

### REQ-LC-003 - Validate Untrusted Assets Before Parsing

Apply root containment, path-component checks, redirect/reparse rejection,
extension/MIME/signature agreement, bounded resource limits, unpredictable
staging names, quarantine, and fail-closed parser dispatch.

### REQ-LC-004 - Parse Fictional EML Fixtures Safely

Use the standard-library MIME parser for plain text, HTML-to-text, attachments,
and nested `message/rfc822` assets. Treat content as data and defer `.msg`.

### REQ-LC-005 - Govern Revisions and Deterministic Change Plans

Track revision lineage, optimistic concurrency, tombstones, duplicates,
authoritative-version conflicts, ACL changes, and deterministic added/changed/
unchanged/deleted classifications.

### REQ-LC-006 - Reuse Unchanged Computation Safely

Reuse parsed, normalized, chunk, and embedding artifacts only when all
tenant-scoped cache-key inputs match. Any parser, normalizer, chunker, model,
dimension, or tenant namespace change must invalidate affected entries.

### REQ-LC-007 - Build a Complete Immutable Target Snapshot

Incremental means selective recomputation followed by a full, independent,
validated target snapshot. The active FAISS, BM25, documents, chunks, and
parents artifacts are never edited in place.

### REQ-LC-008 - Verify Delete and Rollback Semantics

Deletion creates a tombstone and excludes the document from every target
artifact and retrieval path. Rollback explicitly reactivates an old immutable
snapshot and records that old data becomes visible again.

### REQ-LC-009 - Enforce Operator and Content Boundaries

Authenticate and authorize the operator before reading source bytes or starting
a build. Retrieved or ingested document text cannot grant permissions, trigger
privileged tools, or enter public evidence.

### REQ-LC-010 - Produce Reproducible Evidence

Bind each accepted run to Git state, input hashes, source bundle, base and
target manifests, component/model versions, commands, cache outcomes, tests,
artifact hashes, environment, duration, and limitations.

### REQ-LC-011 - Preserve Cross-Platform Behavior

Keep deterministic Ubuntu and Windows CI coverage, including path containment,
without repository-local absolute paths or committed private/runtime data.

### Minimal Vertical Slices

1. G0 current-contract and baseline evidence.
2. G1 evidence schemas, append-only records, traceability, and handoff checks.
3. G2 canonical SourceEvent plus idempotency/conflict ledger.
4. G3 bounded file validation, secure staging, and quarantine.
5. G4 safe EML parsing with child-asset handling.
6. G5 revision catalog, tombstones, and deterministic ChangePlan.
7. G6 parsed/normalized/chunk reuse with explicit invalidation.
8. G6 tenant-scoped embedding cache with exact miss correctness.
9. G7 full target-snapshot assembly and pre-activation validation.
10. G7 delete, failure injection, activation, and rollback verification.
11. G8 operator CLI/API boundary and redacted observability.
12. G9-G10 fictional realistic E2E fixtures and preregistered experiments.

## 3. Protected Invariants

1. `active.json` is replaced atomically only after the target version validates.
2. A published version directory is immutable; an active run ID cannot be
   overwritten in place.
3. Manifest SHA-256, artifact byte counts, and artifact SHA-256 values bind
   loaded data to the declared version.
4. Document and chunk IDs remain deterministic for unchanged inputs and
   configuration.
5. A policy has exactly one active authoritative version; version chains are
   acyclic, complete, and temporally non-overlapping.
6. Deduplication cannot cross tenant, region, ACL, policy, version, or filing
   boundaries.
7. Retrieval applies tenant, region, and group ACL before ranking and repeats
   authorization before parent expansion.
8. Build, embedding, serialization, validation, or activation failure cannot
   replace the prior active pointer.
9. Old validated snapshots remain available for explicit rollback.
10. Existing deterministic tests and evidence are not removed, weakened, or
    silently rewritten.
11. Source content, private identity, absolute user paths, secrets, and real
    email addresses do not enter public evidence.
12. Synthetic or mock evidence is labelled as such and is not presented as a
    private-enterprise pilot.

## 4. Acceptance Gates

### Correctness

- Same event ID plus same canonical payload: 100% idempotent.
- Same event ID plus different payload: 100% explicit conflict.
- Stale expected revision: 100% explicit conflict.
- Unchanged chunk embedding calls: zero.
- Changed embedding calls: exactly the number of new or changed indexable
  chunks.
- Deleted records remaining in target documents, chunks, BM25, FAISS mapping,
  parent expansion, citation, or active top-20 retrieval: zero.
- Failed build active-pointer mutations: zero.
- Rollback restores the bound manifest and fixed-query results.
- All pre-existing deterministic tests continue to pass.

### Security

- Unauthorized retrieval, parent expansion, citation, and cross-tenant cache
  reuse: zero.
- No source byte may be accessed before operator authorization succeeds.
- Privilege change caused by document instructions: zero.
- Raw content, real email addresses, secrets, or absolute local paths in public
  evidence: zero.

### Performance Evidence

Performance is measured, not assumed. On the 1225-document canonical lifecycle
view derived from the 2000-source deterministic corpus, the targets are at
least 90% fewer embedding calls and at least 30% lower median wall time.
Missing either target is allowed only when recorded as
`NO_MEASURABLE_BENEFIT`, `REGRESSION`, or `INCONCLUSIVE`; no resume performance
claim may then be made.

### Cross-Platform

Ubuntu and Windows CI must pass. Platform-specific redirect, junction, reparse,
and hardlink limitations must be tested where available and explicitly
reported where unavailable.

## 5. G0 Baseline Boundary

The first G0 execution is limited to:

- exact Git/branch/dirty-state proof;
- current contract map and full-rebuild data flow;
- reusable-versus-change-required analysis;
- this stage-contract draft and `CODEX_HANDOFF.json`;
- no more than twelve vertical slices;
- focused deterministic baseline;
- first RED-test plan.

G0 remains open until the later full deterministic baseline and the required
240-source/2000-document repeated rebuild measurements are recorded. No
optimization may begin before that baseline closes.

### G0 Full-Rebuild Measurement Protocol

This protocol is frozen before the first performance run:

- `expanded`: 240 synthetic source documents, manifest SHA-256
  `5d96338e4d637c207c381323fc6919f575983992e553a06f548a7e7e0fc24e57`;
- `expanded_benchmark`: 2000 synthetic source documents, manifest SHA-256
  `833338d8472a1da652134d5b23c100a08cc5e76db785154e8609314b2be1f834`;
- deterministic embedding: 128 dimensions and at least 10 isolated-process
  full rebuilds for each corpus;
- local BGE embedding: at least 5 isolated-process full rebuilds for each
  corpus only if the already-installed configured model and Ollama service are
  available; otherwise the result is `NOT RUN` with the observed reason;
- no model download, model replacement, corpus regeneration, cache reuse, or
  active-index mutation is allowed during G0;
- one UTC builder timestamp is frozen across every repetition in a
  configuration because that timestamp is part of `documents.json`; observed
  wall-clock start and finish remain separate measurement fields;
- each repetition starts a new process and writes a new empty output directory;
- P50 and P95 use the existing nearest-rank implementation;
- each run records total wall time, prepare time, embedding time and call count,
  index-construction time, artifact-serialization time, artifact-write time,
  validation time, process peak RSS, corpus counts, embedding dimension,
  artifact-set hash, and output-manifest hash;
- artifact-serialization time covers deterministic conversion of documents,
  chunks, parents, BM25 tokens, and the FAISS index into bytes. BM25
  tokenization and FAISS construction are recorded in index construction;
- the coordinator log, per-run JSONL, summary JSON, commands, environment, and
  SHA-256 checksums are retained below `artifacts/lifecycle/<run_id>/`;
- all temporary build outputs remain on D below `.private/lifecycle/<run_id>/`
  and are not committed.

These G0 measurements describe the current full-rebuild cost. They are not an
optimization experiment and cannot support an incremental speedup claim.

### First RED-Test Plan

The first implementation RED tests, to be written only after G0/G1 approval,
are:

1. `T-LC-001`: valid canonical UPSERT serializes deterministically.
2. `T-LC-002`: valid DELETE cannot contain document body bytes.
3. `T-LC-003`: extra fields, naive timestamps, absolute paths, traversal, NUL,
   UNC, and drive escapes are rejected.
4. `T-LC-004`: same event ID and payload is an idempotent replay.
5. `T-LC-005`: same event ID with a different canonical payload conflicts.
6. `T-LC-006`: stale `expected_revision_id` conflicts without state mutation.
7. `T-LC-007`: tenant, region, ACL, and revision fields cannot be overridden by
   free-form metadata.
8. `T-LC-008`: event ordering is deterministic when operations commute and
   produces an explicit conflict when they do not.

### Implemented G0 Evidence Tests

1. `T-LC-009`: the optional phase observer covers every frozen build phase and
   does not change artifact bytes.
2. `T-LC-010`: repeated full-rebuild rows retain frozen configuration,
   deterministic artifact identity, and nearest-rank summaries.
3. `T-LC-011`: the benchmark coordinator preserves isolated-process rows,
   status, summaries, commands, and hashes.
4. `T-LC-012`: process peak RSS measurement is non-negative and included in
   each repeated-build row.

## 6. G1 Evidence Infrastructure Boundary

G1 establishes the auditable evidence substrate before lifecycle business
behavior is implemented. It is limited to:

- strict schemas for experiment, failure, research-request, traceability, and
  handoff records;
- append-only JSONL writes that reject duplicate record identifiers;
- experiment revisions that use a new identifier, retain `revision_of`, and
  preserve every preregistered field;
- accepted-prefix anchors containing a repository-relative path, accepted byte
  count, record count, and SHA-256 digest;
- deterministic artifact hash manifests containing only relative path, byte
  count, and SHA-256;
- cross-file identifier and handoff consistency checks;
- public-evidence scanning for credential-shaped values, private paths, and
  other prohibited content.

G1 does not create source events, parse enterprise documents, change the active
index, implement revision lifecycle behavior, or claim an enterprise pilot.

### G1 Acceptance Tests

1. `T-LC-013`: illegal experiment lifecycle states are rejected.
2. `T-LC-014`: missing experiment preregistration fields are rejected.
3. `T-LC-015`: duplicate JSONL record identifiers are rejected.
4. `T-LC-016`: mutation or truncation of an accepted evidence prefix is
   detected while a suffix append remains valid.
5. `T-LC-017`: a synthetic sensitive-content fixture is detected by the public
   evidence scanner.
6. `T-LC-018`: experiment revisions cannot alter preregistered fields.
7. `T-LC-019`: traceability and handoff references are strict, bounded, and
   cross-file consistent.
8. `T-LC-020`: evidence artifact hashing is deterministic and rejects paths
   outside the selected evidence root.
9. `T-LC-021`: the lifecycle evidence CLI validates the repository and returns
   a structured, non-content-bearing summary.

### Accepted Append-Only Files

The following files may grow only by suffix after a Gate accepts their current
prefix:

- `docs/lifecycle/01_ENGINEERING_JOURNAL.md`
- `docs/lifecycle/02_DECISIONS.md`
- `docs/lifecycle/03_RESULTS.md`
- `docs/lifecycle/EXPERIMENTS.jsonl`
- `docs/lifecycle/FAILURES.jsonl`
- `docs/lifecycle/RESEARCH_REQUESTS.jsonl`

`00_STAGE_CONTRACT.md`, `TRACEABILITY.csv`, and `CODEX_HANDOFF.json` are mutable
control-plane projections. They are strictly validated but are not themselves
prefix-anchored because Gate status, requirement status, and current handoff
state must change. Corrections to accepted evidence are appended as new
records; accepted history is never silently rewritten.

## 7. G2 Canonical SourceEvent and Idempotency Boundary

G2 establishes the first lifecycle business-domain input without reading source
bytes or invoking a parser. It is limited to:

- strict, bounded `source_event_v1` UPSERT and DELETE records;
- deterministic UTC normalization, ACL normalization, canonical JSON bytes,
  and canonical payload SHA-256;
- lexical repository-relative content paths for UPSERT;
- content-free DELETE events;
- protected governance metadata that cannot be overridden by free-form keys;
- deterministic revision receipts derived from accepted canonical events;
- same-ID/same-payload replay, same-ID/different-payload conflict, optimistic
  expected-revision conflict, and cross-tenant source ownership conflict;
- deterministic export/import of ledger state for a later persistence layer;
- explicit conflict when operations on one source cannot commute safely.

The source identity is the pair `(source_system, source_key)`. Once accepted,
that identity remains owned by one tenant even after a DELETE. Rejected events
do not mutate source state or reserve an event ID. Accepted events and their
receipts are immutable ledger facts.

The G2 ledger is a process-local domain object with strict snapshot
serialization. Durable file/database transactions, authentication, staging,
parsing, revision-catalog persistence, ChangePlan, index building, activation,
and rollback remain outside G2.

### G2 Acceptance Tests

1. `T-LC-001`: valid UPSERT normalizes and serializes canonically.
2. `T-LC-002`: valid DELETE carries no content path, media type, hash, ACL, or
   free-form body.
3. `T-LC-003`: extra fields, naive timestamps, overlong values, absolute paths,
   traversal, backslashes, NUL, UNC, and drive escapes are rejected.
4. `T-LC-004`: same event ID plus the same canonical payload returns an
   explicit replay of the original receipt.
5. `T-LC-005`: same event ID plus a different canonical payload raises an
   event-payload conflict and leaves state unchanged.
6. `T-LC-006`: a stale or missing expected revision raises an optimistic
   concurrency conflict and leaves state unchanged.
7. `T-LC-007`: free-form metadata cannot override event, tenant, region, source,
   ACL, actor, operation, or revision fields.
8. `T-LC-008`: events for different source identities commute to the same
   canonical snapshot; competing same-source updates produce an explicit
   conflict rather than hidden reordering.

## 8. G3 Bounded File Admission, Staging, and Quarantine Boundary

G3 establishes the fail-closed boundary between an authorized source event and
all document parsers. It is limited to:

- operator, tenant, and region authorization before source or storage access;
- strict absolute trusted roots plus canonical relative event paths;
- component-wise symlink, junction, and reparse-point rejection;
- regular-file and hardlink checks plus pre-open/post-open file identity
  comparison;
- one bounded source read into an application-owned incoming directory;
- extension, declared MIME, detected MIME, and minimal signature agreement;
- explicit rejection for empty or oversized files;
- quarantine for spoofing, hash mismatch, unknown binary, and unsupported
  archive content;
- unpredictable application-generated asset names;
- canonical redacted receipts containing no source body, original path, or
  absolute local path;
- atomic incoming-directory publication to `staged/` or `quarantine/`;
- cleanup of every uncommitted incoming directory after failure.

Accepted document families are plain text, Markdown, HTML, CSV, JSONL, PDF,
DOCX, and EML. ZIP, RAR, and 7z are never extracted in G3. A DOCX is accepted
as an OOXML package only when its ZIP directory contains the required Word
members and stays within structural inspection limits.

G3 does not parse document text, extract archives, authorize from document
content, create revisions, construct a ChangePlan, build an index, mutate
`active.json`, or implement an ingestion API. Parser invocation begins only
after a `STAGED` receipt in a later Gate.

### G3 Acceptance Tests

1. `T-LC-022`: an authorized valid asset is copied once into an unpredictable
   staged name with bound hash, size, type, and redacted receipt.
2. `T-LC-023`: missing operator role or tenant/region mismatch fails before
   touching source or storage paths.
3. `T-LC-024`: extension, declared MIME, detected MIME, and signature spoofing
   produce deterministic quarantine reasons.
4. `T-LC-025`: empty and oversized assets are rejected; unknown binary is
   quarantined; incoming partial data is removed.
5. `T-LC-026`: traversal, absolute event paths, root escapes, and symbolic-link
   escapes cannot reach staging.
6. `T-LC-027`: Windows junction/reparse paths are rejected when the platform
   can create the fixture; the platform limitation is an explicit skip.
7. `T-LC-028`: ZIP, RAR, and 7z content is quarantined without extraction,
   while a structurally bounded DOCX can be staged.
8. `T-LC-029`: source replacement and storage publication failures leave no
   incoming or final partial asset.
9. `T-LC-030`: errors and receipts contain no raw body, original filename, or
   absolute source/storage path.
10. `T-LC-031`: every rejected or quarantined asset leaves the active index
    pointer and index directories unchanged, and no parser is invoked.
11. `T-LC-032`: event content-hash mismatch is quarantined before parser use.
12. `T-LC-033`: a linked or reparsed storage root is rejected before copying.
13. `T-LC-034`: staged and quarantined names are unpredictable, collision
    resistant, and do not preserve the original basename.

### G4 Safe EML Parsing Contract

G4 consumes only an authorized `UPSERT` event and a matching, application-owned
`STAGED` EML receipt. Before MIME parsing, the stored payload path, receipt
bytes, file identity, byte count, and SHA-256 must be revalidated. A source
path, quarantined receipt, mismatched event, tampered payload, or `.msg` input
must never reach the MIME parser.

The parser uses Python's standard-library `BytesParser` with `EmailMessage`.
It selects `text/plain` ahead of `text/html`, converts HTML to bounded text
without loading or executing remote resources, preserves the subject and date
as internal parsed data, and exposes only redacted address values. Document
instructions remain data and cannot change policy, dispatch, authorization, or
tool behavior.

Every attachment and nested `message/rfc822` part is a new untrusted child
asset. Before decoding or publication, one shared event budget must account for
the root EML, child count, per-child decoded bytes, total decoded bytes, MIME
part count, nesting depth, HTML output, and total parser output. Decoded child
bytes re-enter the G3 extension/MIME/signature validator and receive a
redacted, parent-linked receipt. Ordinary staged attachments enter the existing
parser registry only through immutable bytes whose SHA-256 matches the staged
child receipt. Nested EML parts recurse through this G4 operation; they are
never selected from a raw source filename.

Recoverable MIME defects become bounded reason-code warnings. Structural
boundary defects, invalid transfer encoding, encrypted content, unsupported
archives, type disagreement, parser exceptions, or any budget overrun fail
closed and quarantine the root parse. Public trace data is allowlisted to
pseudonymous asset IDs, counts, media types, parser versions, status, and
reason codes. Raw or stable content hashes are excluded from the public trace.

The G4 executable checks are:

1. `T-LC-035`: only an authorized, matching, untampered staged EML receipt can
   enter MIME parsing.
2. `T-LC-036`: plain body, HTML fallback, and plain-over-HTML preference are
   deterministic and HTML active/remote content is not executed or loaded.
3. `T-LC-037`: encoded headers, dates, and addresses are parsed with bounded
   subject output and address redaction.
4. `T-LC-038`: regular attachments re-enter G3 admission, receive parent-linked
   redacted receipts, and enter the parser registry only after staging.
5. `T-LC-039`: nested `message/rfc822` parts recurse with deterministic parent
   lineage and depth accounting.
6. `T-LC-040`: attachment count, per-child bytes, total decoded bytes, MIME
   parts, depth, HTML text, and aggregate parser output fail before unsafe
   continuation.
7. `T-LC-041`: invalid transfer encoding, structural MIME defects, encrypted
   content, unsupported archives, child type disagreement, and child parser
   exceptions quarantine rather than index content.
8. `T-LC-042`: recoverable MIME defects are bounded warnings and never include
   body, address, original filename, or absolute-path data.
9. `T-LC-043`: public trace serialization is allowlisted and zero-leak even
   when the email and attachment contain synthetic secrets or prompt
   injection.
10. `T-LC-044`: attachment instructions cannot change control flow,
    authorization, policy, or parser selection.
11. `T-LC-045`: `.msg` receives the explicit `msg_not_supported` disposition
    and is never attempted as RFC 5322/MIME.
12. `T-LC-046`: a G4 failure leaves no parse/index side effect and no
    parse-eligible staged child asset.

## 9. G5 Durable Revision Catalog and Deterministic ChangePlan

G5 persists the accepted G2 event state and its materialized source revisions
as one local transaction. The authoritative catalog file contains the complete
canonical `SourceEventLedgerSnapshot` plus exactly one immutable
`DocumentRevision` for every accepted event receipt. A revision records only
bounded governance and provenance fields; it never stores document text,
original filenames, source paths, or parser output bodies.

An UPSERT revision requires a materialization record whose root content hash
matches the canonical event. A DELETE requires no materialization and creates a
tombstone that inherits the previous live ACL while linking to the previous
revision. Recreating a deleted source appends another UPSERT revision to the
same lineage. No accepted revision or receipt is physically removed.

The local persistence boundary is:

- one absolute application-owned catalog directory with private ACL/mode,
  held-directory identity, redirect, and regular-file checks;
- one cross-process exclusive catalog lock covering load, event application,
  revision construction, validation, and publication;
- a checksum-bound canonical catalog envelope with monotonic event-count
  generation and previous-snapshot hash;
- an independently replaced generation/hash anchor that detects catalog
  deletion, same-generation divergence, and rollback to an older valid file;
- complete temporary-file construction, file `fsync`, one atomic replace, a
  POSIX directory sync, or Windows write-through replacement;
- deterministic cleanup of owned orphan temporary files;
- strict rejection of malformed, non-canonical, oversized, redirected, linked,
  checksum-mismatched, or unsupported-schema catalog artifacts;
- an empty initial snapshot only when no authoritative catalog exists.

The persisted G2 optimistic-concurrency contract remains authoritative. The
same event ID and canonical payload replays without a write. The same event ID
with different payload, stale expected revision, source ownership conflict,
unsafe catalog state, or materialization mismatch fails without changing the
accepted catalog bytes. Concurrent writers serialize through the catalog lock;
there is no silent last-write-wins path.

A failure before replacement is definitely uncommitted. A sync, anchor, or
verification failure after replacement returns
`catalog_commit_outcome_unknown`; the caller must retry the exact same event
ID and payload. The durable ledger then returns either the accepted replay or a
conflict, so no compensating DELETE is guessed.

`ChangePlan` is a pure deterministic diff from a base catalog snapshot to a
forward-descendant target snapshot. It classifies live source identities into
sorted UPSERT, DELETE, unchanged, and retained-tombstone groups. Explicit
conflict or quarantine dispositions make the plan non-executable. The plan
binds the base and target catalog hashes, accepted and excluded event payload
hashes, event counts, base index run ID, and a distinct target index run ID.
Every exclusion carries event, payload, tenant, source, and reason provenance.
Content, materialization, governance, revision-only, deletion, restoration,
and retained-tombstone changes have distinct reason codes. `plan_id` is derived
only from canonical plan inputs, with no wall-clock field or random value.

G5 does not build chunks, embeddings, BM25, FAISS, or an index version. It does
not mutate `active.json`. G6 may consume an executable G5 plan to reuse
unchanged computation while still building a complete immutable target index.

### G5 Acceptance Tests

1. `T-LC-047`: an UPSERT atomically persists one receipt, head, materialized
   revision, and checksum-bound canonical envelope.
2. `T-LC-048`: process restart restores idempotent event replay and exact
   canonical catalog bytes.
3. `T-LC-049`: same-ID payload conflict, stale revision, and materialization
   mismatch leave the authoritative catalog byte-for-byte unchanged.
4. `T-LC-050`: DELETE appends a content-free tombstone, preserves prior
   revisions, inherits ACL, and permits explicit later recreation.
5. `T-LC-051`: concurrent independent events are both durable, while competing
   updates produce exactly one accepted revision and one explicit conflict.
6. `T-LC-052`: a failure before atomic replace leaves the old catalog
   authoritative; a post-replace uncertainty is explicit and retry completes
   without duplicate history.
7. `T-LC-053`: owned orphan temporary files are recovered, while unsafe,
   redirected, linked, oversized, tampered, or unsupported catalog files fail
   closed; deletion and rollback relative to the anchor are rejected.
8. `T-LC-054`: equal base/target inputs produce byte-identical ChangePlans and
   plan IDs across event order, process restart, and repeated calls.
9. `T-LC-055`: ChangePlan rejects a target that removes or rewrites accepted
   history or reuses an immutable run ID, and classifies new, content,
   materialization, governance, revision-only, deleted, restored, unchanged,
   and retained-tombstone sources without overlap.
10. `T-LC-056`: a catalog or planning failure leaves all index versions and
    the active pointer unchanged.

## 10. G6 Exact Computation Reuse Contract

G6 consumes validated live `DocumentRevision` values and an executable G5
`ChangePlan`. It may reuse private parsed, normalized, chunk, and embedding
artifacts, but it does not assemble or publish FAISS, BM25, document, chunk,
parent, manifest, or `active.json` index artifacts. Complete immutable target
snapshot construction remains G7.

Every cache entry is immutable and content addressed. Its canonical key and
canonical payload are independently SHA-256 bound by an envelope. The
application-owned cache root is absolute, flat, private, bounded, and rejects
redirected, non-regular, multiply linked, oversized, non-canonical, or
checksum-invalid entries. Concurrent writers serialize publication and an
existing key may only be replayed with byte-identical canonical content.

Cached content artifacts exclude tenant, ACL, region, authority, revision,
source path, and observation timestamps. Parsed and normalized content are
materialized into fresh target `DocumentRecord` values from the target
revision. G6 then reruns `govern_documents()` over the complete live target
document set before chunk reuse is decided. Cached chunk layouts contain only
content and locator structure; every target `ChunkRecord` is rebuilt with the
governed target document's current ACL, region, authority, and version fields.

Stage keys implement the frozen conservative invalidation policy:

- parsed: tenant, source system/key, document, content hash, media type, parser
  name, semantic version, implementation digest, and dependency versions;
- normalized: tenant/source/document identity, parsed artifact hash, content
  and expected normalized hashes, parser identity, normalizer semantic
  version, implementation digest, and dependency versions;
- chunks: tenant/source/document identity, normalized artifact hash,
  normalized hash, parser and normalizer identity, chunker semantic version,
  implementation digest, dependency versions, and canonical configuration
  hash;
- embedding: tenant/source/document/chunk identity, chunk text hash, complete
  parser/normalizer/chunker pipeline hash, embedding model identifier,
  immutable model digest, backend, requested dimension, and vector
  normalization.

A staged asset or revision ID change alone may reuse a content artifact only
inside the same tenant/source/document namespace when the accepted content,
media type, upstream artifact, and complete relevant component fingerprints
remain equal. Provenance still records the current revision and source
binding in the computation manifest. A tenant, source, document, parser,
normalizer, chunker, embedding model, model digest, dimension, normalization,
content, or relevant upstream artifact change cannot reuse an entry from the
old key. Cache hits are accepted only after the stored key, payload,
checksums, canonical bytes, payload model, vector finiteness, and vector
dimension validate.

The G6 executor validates the target catalog hash and every target plan item
before computation. A non-empty plan requires its exact base catalog. The
executor reconstructs the G5 `ChangePlan` from that base, the target, run IDs,
and exclusions, then requires complete equality with the supplied plan. It
processes the complete live target corpus and never reads or mutates base
index artifacts, so G6 does not accept a caller-created base-index binding.
G7 must independently bind the actual immutable base `IndexManifest`, catalog
hash, and run ID before target assembly or activation. Conflicts, quarantine,
a missing live source materializer, stale revision, mismatched normalized
hash, malformed embedding, or catalog/plan mismatch fail closed before a
successful computation manifest is returned.

The computation artifact manifest is deterministic. It binds the plan, base
and target catalog hashes, target run ID, pipeline fingerprint, processed
revision IDs, source and tombstone bindings, governance result, final governed
documents, chunks, and embeddings by canonical SHA-256. The result separately
reports exact per-stage hits, misses, and callback counts plus successful-run
canonical serialization and total wall time. Timings are measurements, not
artifact identity and not evidence of speedup. The computation manifest is
preparation evidence for G7, not an index manifest or activation
authorization.

### G6 Acceptance Tests

1. `T-LC-057`: an exact replay reuses parsed, normalized, chunk, and embedding
   artifacts without invoking the corresponding callbacks again.
2. `T-LC-058`: tenant, source, document, or content changes cannot hit another
   identity's cache entry; copied models are strictly revalidated at the cache
   boundary.
3. `T-LC-059`: parser or normalizer version changes miss the affected stage
   and every downstream stage.
4. `T-LC-060`: canonical chunker configuration changes miss chunk and
   embedding entries while allowing valid upstream reuse.
5. `T-LC-061`: embedding model identifier, immutable model digest, dimension,
   backend, or normalization changes produce an embedding miss; returned
   dimensions, finite values, and non-zero norm must exactly match the request.
6. `T-LC-062`: tampered, non-canonical, linked, redirected, oversized, or
   permission-unsafe cache state fails closed and leaks no cache payload in
   public errors.
7. `T-LC-063`: the executor rejects non-executable, stale, forged, or
   catalog-mismatched plans; a non-empty plan requires its exact base catalog,
   and failures leave every index directory and `active.json` byte unchanged.
8. `T-LC-064`: concurrent same-key writes converge to one canonical artifact;
   callback or publication failure returns no successful computation manifest
   and a later retry remains possible.
9. `T-LC-065`: governance is rerun over the complete live target corpus;
   governance-only changes refresh target document/chunk ACL fields and a
   change in one source may change another source's canonical disposition;
   tombstones bind zero live artifacts.
10. `T-LC-066`: isolated 100-source 0%, 1%, 5%, and 20% change conditions
    invoke parse, normalize, chunk, and embedding exactly once per changed
    source and zero times for every unchanged source. This is call-count
    correctness evidence, not a wall-time performance experiment.

## 11. G7 Immutable Target Publication Contract

G7 consumes a strictly revalidated G6 `IncrementalComputationResult`, the
exact G5 base and target catalogs, the deterministic `ChangePlan`, and the
pipeline configuration. It always writes a complete independent target
snapshot. Incremental refers only to computation reuse; documents, chunks,
parents, BM25, FAISS, runtime manifest, and lifecycle evidence are rebuilt as
one target version and the active version is never edited in place.

The existing `enterprise_index_manifest_v1` remains load-compatible. A new
`lifecycle.json` artifact carries a deterministic `publication_id` and is
itself hash-bound by the v1 manifest. The publication identity binds the run
and profile, plan and source-event set, G6 computation set, target catalog,
pipeline and governance hashes, complete document/chunk/embedding hashes,
source-to-index mappings, tombstones, and, for non-empty plans, the actual
base run ID, base manifest SHA-256, base catalog SHA-256, and prior lifecycle
publication ID.

The target also stores hash-bound canonical `revision_catalog.json`,
`change_plan.json`, `computation_manifest.json`, and ordered
`embedding_rows.json` evidence. Validation reconstructs and checks the
catalog, plan, computation manifest, documents, original complete chunk
order, split indexed/parent mappings, exact BM25 token rows, normalized FAISS
rows, document/parent references, and deleted prior mappings before install.
Missing runtime artifacts are rejected before pickle deserialization.

A non-empty base is accepted only when the declared version loads as a valid
G7 snapshot and its persisted catalog hash equals the plan's base catalog
hash. A legacy v1 snapshot without that binding cannot be self-certified by a
caller; migration requires a complete G7 bootstrap build. The unified
publication lock protects legacy activation, G7 install/activation, and
rollback. Installation rechecks the expected active base under that lock.
Competing publications from one base therefore have at most one activation;
the other receives an explicit stale-base conflict.

Published run IDs are immutable. An existing target with the same
`publication_id` is an installed replay; when it is already active, replay
does not rewrite `active.json` or `activated_at`. The same run ID with a
different publication identity is a conflict. A newly installed version is
removed if an injected pre-replace activation failure leaves the old pointer
authoritative.

Deletion persists a tombstone in the target catalog and records prior
document, indexed-chunk, and parent-chunk mappings in lifecycle evidence.
Target validation requires zero overlap with those prior mappings. A target
with no live chunks publishes and loads an empty FAISS index and a safe empty
BM25 adapter, so deleting the final document is a valid state rather than a
builder exception.

Rollback validates the old immutable snapshot and its fixed-query retrieval
fingerprint before pointer replacement. The fingerprint binds ordered chunk,
document, parent, source, section, locator, and parent-context citation
fields. Successful rollback restores the old manifest hash and appends a
hash-chained local audit event that explicitly states old data became visible
again.

### G7 Acceptance Tests

1. `T-LC-067`: complete G6 artifacts publish as an independently loadable
   target whose lifecycle and runtime manifests bind every declared artifact.
2. `T-LC-068`: a non-empty publication derives its base run, manifest hash,
   and catalog hash from the actual validated version; a legacy or mismatched
   base fails closed.
3. `T-LC-069`: exact installed and active replays are idempotent, while the
   same run ID with a different publication identity conflicts.
4. `T-LC-070`: two concurrent targets planned from one active base produce
   exactly one activation and one stale-base conflict.
5. `T-LC-071`: documents, chunks, parents, BM25 rows, FAISS rows, lifecycle
   evidence, and model references validate before version installation.
6. `T-LC-072`: all 14 frozen failure points are injected ten times each; every
   failure preserves the old pointer and snapshot, leaves no loadable failed
   target or owned staging directory, and permits a successful retry.
7. `T-LC-073`: deleting the final live source leaves zero document, chunk,
   parent, BM25, FAISS, top-20, citation, or parent-expansion residuals.
8. `T-LC-074`: rollback restores the exact prior manifest SHA-256 and fixed
   query ordering/citation fingerprint, then records old-data visibility in
   the rollback audit chain.
9. `T-LC-075`: parent-child computation order survives split runtime
   artifacts, and a missing manifest-bound runtime artifact is rejected
   before pickle or FAISS deserialization.
10. `T-LC-076`: the shared directory publication primitive recovers only from
   transient Windows `WinError 5` while source remains present and target
   absent; collisions and other permission errors are not retried.

## 12. G8 Authenticated Operator Surface Contract

G8 exposes the accepted G2-G7 lifecycle through one synchronous operator
service. The service is the only business entry point used by the CLI and
HTTP API. It supports preview, build without activation, build with activation,
activation of an existing immutable version, rollback, and sanitized status.
It does not create a job ID unless a real durable job executor exists; G8 has
no background queue and therefore reports a completed synchronous operation.

Authentication and operator authorization must complete before an events file
is opened, an input-root path is resolved, a catalog or active pointer is
loaded, or an index build begins. The CLI verifies a bearer token through the
same trusted JWT/JWKS boundary as the API. The API registers exact
operator-only routes in the existing fail-closed route policy. A request body
cannot select catalog, cache, asset-store, index, or audit roots; those roots
come from trusted server configuration. Source-event actor identity is derived
from the verified principal and never accepted from document content or
caller-controlled event JSON.

The operator event input is a strict transport model rather than a serialized
trusted `SourceEvent`. It accepts bounded source identity, operation, tenant,
region, ACL, expected revision, declared file metadata, and a path relative to
the configured input root. The service creates the canonical `SourceEvent`
only after authorization. DELETE never opens a source file. UPSERT passes
through G3 admission before parser dispatch. Exact event replay reuses the
durable receipt and materialization without writing another asset; same-ID
different-payload and stale-revision cases fail as version conflicts.

Preview is deterministic and side-effect free with respect to the durable
catalog, asset store, computation cache, index versions, active pointer, and
rollback audit. It validates event schemas and conflict semantics but does not
admit or parse source files. Because file bytes have not been admitted, a new
or changed UPSERT returns an explicit `PROPOSED` result with
`materialization_pending`; it must not manufacture an `asset_id`, normalized
hash, parser identity, target catalog hash, plan ID, or executable ChangePlan.
Only DELETE-only and accepted-replay previews whose persisted materialization
already exists may return an exact ChangePlan.

Build is synchronous. It authenticates first, admits and parses each changed
UPSERT, applies the event and revision materialization to the durable catalog,
constructs the deterministic ChangePlan against the actual active snapshot
catalog, executes G6, and publishes a complete G7 target. `build` installs but
does not activate. `build-and-activate` uses G7 expected-active-base CAS.
Failures after accepted catalog events may leave durable source/catalog state
ahead of the active index; status must expose this as a sanitized
`index_update_pending` condition so the same event set and a new run can
resume. G8 does not pretend catalog acceptance and index publication are one
cross-resource transaction.

Activation of an existing target and rollback operate only on immutable
versions under the G7 publication lock. Activation validates the target and
requires the caller's expected active run ID. Rollback uses the G7 rollback
validator and audit chain. Rollback first persists a canonical intent; a
pre-pointer failure removes the intent and leaves the pointer unchanged. If
the pointer changes but audit completion fails, the operation returns
`activation_outcome_unknown` and preserves the intent. Authenticated status or
the next rollback deterministically reconciles the intent against the actual
active manifest and either appends the audit idempotently or cancels an
unapplied intent. Status exposes only schema versions, run IDs,
canonical hashes, counts, operation state, and stable error codes. It must not
include source paths, file names, body text, subjects, addresses, tokens,
claims, exception strings, or private root locations.

The CLI always emits one machine-readable JSON object. Its stable exit code
map is:

1. `0`: success;
2. `2`: schema validation;
3. `3`: authentication or authorization;
4. `4`: file validation;
5. `5`: quarantine threshold;
6. `6`: version or optimistic-concurrency conflict;
7. `7`: build/computation failure;
8. `8`: manifest or immutable-snapshot validation failure;
9. `9`: activation failure;
10. `10`: rollback failure.

No error response may include a raw exception, token, private path, source
content, email field, or model payload. Unclassified failures map to the
narrowest safe operation category and are recorded only as stable codes and
bounded identifiers.

### G8 Acceptance Tests

1. `T-LC-077`: CLI and API reject missing, invalid, non-operator, cross-tenant,
   and cross-region identity before any event file, input asset, catalog,
   cache, index, active pointer, or audit access.
2. `T-LC-078`: strict operator event input rejects extra fields and cannot
   supply actor identity or private storage roots; the canonical actor is
   derived from the verified principal.
3. `T-LC-079`: preview mutates zero durable source, catalog, cache, index,
   pointer, or audit bytes; UPSERT materialization is explicitly pending, while
   DELETE/replay-only input may produce an exact deterministic ChangePlan.
4. `T-LC-080`: exact accepted event replay returns the durable receipt without
   duplicate admission; same-ID different-payload and stale revisions return
   stable conflict codes.
5. `T-LC-081`: build installs a complete validated target without changing
   `active.json`; build-and-activate changes it only through expected-base CAS.
6. `T-LC-082`: activating an existing immutable target validates it, requires
   an expected active run ID, and never overwrites a version.
7. `T-LC-083`: rollback restores the prior manifest/query/citation fingerprint
   and appends the G7 audit event; pre-pointer failures keep the pointer
   unchanged, while a post-pointer audit failure leaves a canonical recoverable
   intent and returns `activation_outcome_unknown`.
8. `T-LC-084`: status reports a restart-safe, sanitized state including
   catalog-ahead-of-index without leaking paths, source fields, content,
   identities, tokens, claims, or exception strings.
9. `T-LC-085`: every CLI operation emits one JSON object and maps the nine
   frozen failure categories to exit codes `2` through `10`.
10. `T-LC-086`: API operations are synchronous and operator-only; no fake job,
    queued state, arbitrary filesystem root, or document-controlled capability
    is exposed.

## 12A. G9 Fictional Enterprise End-to-End Contract

G9 proves that the G2-G8 lifecycle works as one repeatable operator workflow on
a realistic but wholly fictional enterprise bundle. It does not introduce a
new orchestration framework, retrieval algorithm, model, or production
deployment. It converts isolated component evidence into one inspectable
business scenario.

The bundle must contain a canonical manifest and bounded source files from at
least policy, project, operations, and email domains. Every organization,
person, address, identifier, and fact is synthetic. The manifest binds each
relative path, media type, SHA-256, tenant, region, ACL, source key, document
projection, and intended lifecycle transition. No event may contain a private
absolute path or actor identity.

The frozen scenario is:

1. initialize an empty lifecycle state from the fictional bundle;
2. build and activate a complete first index;
3. restart the operator service and replay the same events without reopening
   source files or publishing duplicate assets;
4. apply one content update with expected revision, one ACL-preserving
   unchanged replay, and one source deletion;
5. build the second immutable index without activation, inspect
   `INDEX_UPDATE_PENDING`, then activate it through expected-current CAS;
6. prove the deleted source has zero document, chunk, BM25, FAISS, parent, and
   citation residue;
7. compare fixed-query ordered result/citation fingerprints for both versions;
8. roll back to the first version and recover its exact manifest and query
   fingerprint with one hash-chained audit event.

The deterministic G9 test pipeline may use an explicitly labelled local test
embedder to make the E2E run offline and reproducible. It must still execute
the production operator, admission, parser, catalog, computation, immutable
publication, activation, retrieval, and rollback code. Fake wall-clock timing
or deterministic embeddings are not performance or model-quality evidence.

Public G9 evidence may include only fictional manifest IDs, relative bundle
paths, run IDs, canonical hashes, counts, stable status/error codes, and test
results. It must not include private roots, local usernames, tokens, raw
claims, absolute paths, message addresses, or source bodies.

### G9 Acceptance Tests

1. `T-LC-087`: the fictional bundle manifest is canonical, path-contained,
   hash-complete, size-bounded, and contains no real/private identity marker.
2. `T-LC-088`: the initial event batch builds and activates a complete
   validated index whose catalog, document, chunk, and source counts match the
   manifest.
3. `T-LC-089`: a restarted service replays the exact initial batch after the
   source files are unavailable; every event is `REPLAYED` and asset bytes are
   unchanged.
4. `T-LC-090`: update and delete events use the accepted revision IDs, create
   one deterministic target plan, and leave the active pointer unchanged until
   explicit activation.
5. `T-LC-091`: the second target activates only against the expected first
   run; stale expected-active input fails without pointer mutation.
6. `T-LC-092`: the deleted source has zero residual document, chunk, vector,
   BM25, parent, retrieval, and citation mappings in the second target.
7. `T-LC-093`: rollback restores the first manifest and fixed-query ordered
   result/citation fingerprint and appends exactly one valid audit transition.
8. `T-LC-094`: the complete E2E public summary is deterministic and sanitized,
   and the full existing repository regression remains green.

## 12B. G10 Preregistered Paired Performance Contract

G10 measures whether the accepted incremental lifecycle reduces update work and
wall time relative to rebuilding the same changed target from scratch. It does
not change retrieval behavior, cache keys, publication validation, or security
boundaries to improve a benchmark.

No timing result may be collected until:

1. a deterministic base corpus and deterministic change-set generator are
   canonical and hash-bound;
2. both arms produce the same governed target documents, chunks, embeddings,
   active-index deletion state, and fixed-query fingerprint;
3. a strict paired-result schema and isolated worker command are tested;
4. the exact experiment is appended to `EXPERIMENTS.jsonl` as `REGISTERED`.

### Experimental Unit

One pair starts from the same prebuilt base lifecycle state:

- **baseline arm:** recompute the complete changed target from the accepted
  base state with a new empty target computation cache;
- **intervention arm:** apply the frozen update/delete/ACL change set to the
  base catalog and use the accepted incremental computation plus complete G7
  target publication.

Base preparation is outside both timed regions. Target input validation and
complete immutable publication are inside both timed regions. Each pair has one
fresh coordinator that sequentially launches two fresh arm-worker processes
against separate roots. A single process cannot provide independent per-arm
peak RSS because the operating-system counter is cumulative for the process
lifetime. Pair order alternates AB/BA by repetition to reduce order and
filesystem-cache bias. At least ten deterministic embedding pairs are required.

The baseline is deliberately not raw-file admission from an empty catalog. Both
arms start from byte-copied instances of the same validated base index,
revision catalog, and materialization state. Base-template construction and
workspace copy are outside timing. Bundle/prestate validation, G6 computation
including transaction finalization, and G7 complete target publication,
validation, and activation are inside timing. Fixed-query, ACL, and deletion
fingerprints run after timing and decide whether a row is admissible. Therefore
G10 may claim only a cold-versus-reused **target-build pipeline** comparison,
not original source ingestion or end-to-end RAG latency.

### Frozen Dataset Shape

The intended base is the public `expanded_benchmark` corpus with 1225 canonical
documents and 1225 indexed chunks under chunk size 500 and overlap 80. The
change-set generator must select sources by sorted stable identity and produce
exactly:

- 31 content updates;
- 20 ACL-only governance updates;
- 10 deletions;
- 1164 unchanged live documents.

The generator, base manifest, target catalog, and query set must each receive a
canonical SHA-256 before experiment registration. If the existing corpus cannot
be represented through the lifecycle contract without changing its semantics,
G10 must record `BLOCKED` or freeze a new dataset revision before timing.

### Metrics and Decision Rules

Required paired metrics are:

- total target-build wall time;
- input-validation wall time;
- compute-only wall time;
- publication/validation wall time;
- independent per-arm peak RSS from fresh arm-worker processes;
- parse, normalize, chunk, and embedding callback counts;
- cache hit/miss counts by stage;
- target artifact and fixed-query fingerprint equality;
- computed active-index deletion residual count.

The preregistered deterministic hypothesis may be marked `SUPPORTED` only when:

- all pairs satisfy exact correctness equivalence and zero active-index
  deletion residue;
- the intervention median paired total-time ratio is at most `0.75`;
- at least 8 of 10 pairs are faster under the intervention;
- intervention embedding calls are at most 10 percent of baseline calls.

It is `REGRESSION` if any correctness pair fails or median total-time ratio is
at least `1.05`. A ratio above `0.75` and below `1.05` is
`NO_MEASURABLE_BENEFIT`; infrastructure failure or an unrepresentable frozen
dataset is `BLOCKED` or `INCONCLUSIVE` according to the registered protocol.

Synthetic deterministic results may support only a local pipeline-overhead
claim. A separate Ollama experiment must have its own preregistration, model
digest, minimum five pairs, and decision. G10 cannot convert deterministic
results into a live-model latency claim.

### G10 Acceptance Tests

1. `T-LC-095`: the base/change/query bundle is canonical, exact-hash bound, and
   deterministic across two isolated generations.
2. `T-LC-096`: each pair uses separate roots, one pair coordinator, two fresh
   sequential arm-worker processes, and frozen alternating arm order.
3. `T-LC-097`: both arms start after identical base preparation and include
   complete target validation/publication inside timing.
4. `T-LC-098`: target catalog, document, chunk, embedding, deletion, and query
   fingerprints must match before a timing row is accepted.
5. `T-LC-099`: timing uses a monotonic clock and callback/cache counts come from
   production measurement models, not estimated values.
6. `T-LC-100`: repeated rows reject mixed dataset, pipeline, model, change-set,
   host, process-order, or configuration identity.
7. `T-LC-101`: the coordinator resumes no partial pair, refuses existing run
   IDs, writes private work only under `.private/lifecycle`, and publishes
   bounded public artifacts only under `artifacts/lifecycle`.
8. `T-LC-102`: summary computes paired ratios, nearest-rank P50/P95, faster-pair
   count, callback reductions, independent RSS, AB/BA order-stratified ratios,
   and the frozen decision without post-hoc threshold changes.
9. `T-LC-103`: experiment REGISTERED, RUNNING, COMPLETED, or correction records
   preserve every preregistered field and bind all raw artifact hashes.
10. `T-LC-104`: focused, related, complete repository, public audit, and
    integrated lifecycle validation remain green before any performance claim.

### G10 Closeout

The accepted final formal run is the schema-v2 experiment chain
`EXP-LC-010 -> EXP-LC-011 -> EXP-LC-012`. It binds source commit
`71e26d667d49a5573546e703e7a9fbb78803906d`, the complete measurement source
tree, dependency identities, the canonical v4 bundle, exact preregistered
thresholds, and 45 aggregate/child execution artifacts.

The independently recomputed result is `SUPPORTED`:

- 10 of 10 pairs are correctness equivalent;
- 10 of 10 intervention arms are faster;
- median intervention/baseline total-time ratio is `0.7076844547982923`;
- intervention/baseline embedding-call ratio is `0.025472473294987676`;
- active-index deletion residual count is zero.

This accepts a local deterministic lifecycle pipeline-overhead claim only. It
does not establish live Ollama latency, semantic retrieval quality, production
throughput, or private-enterprise acceptance. The preceding
`EXP-LC-007 -> EXP-LC-009` run remains valid evidence for source commit
`5570d02`, but it was superseded as the current-source claim after full-suite
testing found and fixed a Windows publication inconsistency. The final
self-contained public package is `data/v2/public/lifecycle_g10_v3`; v2 remains
historical evidence for the preceding source commit.

One non-product exception remains open as `FAIL-LC-076`: an old pytest
temporary directory on the host system drive has an ACL that prevents cleanup
by the current token. Every subsequent Python and pytest command used the
project-drive `.private/lifecycle/pytest-temp` root.

## 13. Out of Scope

- LangGraph, MCP, multi-agent orchestration, Kubernetes, distributed queues,
  complex vector databases, open web tools, Self-RAG, and untriggered rerankers.
- In-place mutation of active vector, BM25, document, chunk, or parent
  artifacts.
- `.msg`, OCR, production IdP integration, remote JWKS refresh, production
  traffic, formal security certification, and legal/privacy approval.
- Owner-only private pilot execution or human correctness/faithfulness labels.
- Claims based on one timing run, mock timing, undocumented datasets, or
  post-hoc experiment thresholds.
- Byzantine same-user host compromise, deletion of both catalog and anchor,
  distributed consensus, remote writers, online schema migration, and
  destructive power-loss testing.

## 14. Terms

- **SourceEvent**: canonical, identity-bound UPSERT or DELETE input.
- **Asset**: an untrusted file, email body, attachment, or nested email handled
  independently.
- **Revision**: immutable governed state for one logical source key.
- **Tombstone**: a revision that marks deletion without destroying historical
  snapshots.
- **ChangePlan**: deterministic classification of requested changes relative to
  a base snapshot.
- **Compute reuse**: reuse of unchanged intermediate results; it does not imply
  in-place index mutation or end-to-end speedup.
- **Computation cache**: private immutable stage artifacts keyed by every
  correctness-affecting input; it is neither a shared tenant namespace nor an
  index snapshot.
- **Base catalog binding**: the exact catalog snapshot used to reconstruct and
  verify a non-empty G6 ChangePlan.
- **Base index binding**: the G7 tuple of base run ID, base catalog hash, and
  exact serialized base manifest hash required before index assembly or
  activation; G6 does not manufacture or trust this binding.
- **Target snapshot**: complete immutable candidate index version.
- **Activation**: atomic replacement of the active pointer after validation.
- **Rollback**: explicit activation of a previously validated immutable
  snapshot.
- **Public evidence**: repository-safe summaries and hashes containing no raw
  private content or machine-specific paths.
- **Canonical SourceEvent**: a strict normalized UPSERT or DELETE request whose
  canonical JSON bytes define its payload hash.
- **Event receipt**: the immutable accepted result binding an event payload to
  its previous and resulting revision identifiers.
- **Idempotent replay**: reprocessing an accepted event ID with the same
  canonical payload and returning its original receipt without state mutation.
- **Operator service**: the synchronous, identity-bound G8 business boundary
  shared by CLI and API.
- **Catalog ahead of index**: accepted source/revision state that has not yet
  been represented by the active immutable snapshot after a failed or
  deliberately non-activated build.
