# R2-S7 Decisions

## ADR-LC-001 - Preserve and Extend the Current Immutable Index Contracts

Status: Accepted for G0 baseline

Date: 2026-07-26

Requirements: `REQ-LC-001`, `REQ-LC-005`, `REQ-LC-006`, `REQ-LC-007`,
`REQ-LC-008`, `REQ-LC-009`, `REQ-LC-011`

### Context

The current repository already has a coherent generated-corpus ingestion and
immutable index publication path. R2-S7 must add governed enterprise source
events and selective computation without weakening that path or mislabelling it
as production ingestion.

### Current Contract Map

| Area | Current implementation contract | Existing test evidence |
|---|---|---|
| Parser dispatch | `ParserRegistry` maps registered suffixes to one parser, rejects unknown suffixes, wraps unexpected parser exceptions, and exposes parser name/version. Default formats are Markdown, text, HTML, CSV, JSONL, PDF, and DOCX. | `tests/ingestion/test_parsers_text.py`, `tests/ingestion/test_parsers_office.py` |
| Manifest ingestion | `load_source_manifest` accepts only generated corpus or smoke fixture schemas. `ingest_corpus` confines relative paths, checks byte count and SHA-256, parses, then maps manifest governance metadata into `DocumentRecord`. | `tests/ingestion/test_normalize.py` |
| Version governance | Deduplication is scoped by tenant, region, ACL, policy, version, and filed department. Authoritative chains must be complete, acyclic, non-overlapping, and have exactly one active head. | `tests/ingestion/test_versions.py` |
| Chunk identity | `chunk_id` hashes document ID, full chunker config, kind, section path, locator, ordinal, text hash, and parent ID. Governance metadata is copied to every chunk. | `tests/ingestion/test_chunking_v2.py` |
| Build preparation | `_prepare` loads the manifest, reparses every source, governs every record, rechunks every canonical document, and verifies global chunk-ID uniqueness and parser-version consistency. | `tests/indexing/test_builder.py` |
| Full artifact build | `_build_artifact_bytes` embeds every indexable chunk and reconstructs complete documents, chunks, parents, BM25 tokens, and `IndexFlatIP` artifacts in memory. | `tests/indexing/test_builder.py` |
| Manifest integrity | `IndexManifest` is strict, validates counts/timestamps/unique artifact paths, and binds every artifact by byte count and SHA-256. | `tests/indexing/test_manifest.py`, `tests/indexing/test_builder.py` |
| Version store | A build writes to a version-scoped staging directory, validates it, installs it as a version, and activates only afterward. Active pointer writes use fsync plus `os.replace`. Active versions cannot be force-overwritten. | `tests/indexing/test_store.py`, `tests/indexing/test_index_cli.py` |
| Snapshot loading | `load_index_version` validates the manifest and every artifact before `V2IndexSnapshot` creates typed mappings and checks FAISS/BM25/model cardinality and references. | `tests/retrieval/test_snapshot.py` |
| Retrieval ACL | `AccessPolicy` fails closed on malformed identity/metadata and requires tenant, region, and group intersection. ACL filtering precedes ranking; parent expansion is independently reauthorized. | `tests/security/test_access_policy.py`, `tests/retrieval/test_pipeline_acl.py`, `tests/retrieval/test_pipeline_parent.py` |
| Operator CLI | `build_indexes_v2` accepts only a full generated preset corpus, supports dry-run, immutable build-and-activate, force only for validated inactive versions, and explicit activation rollback. | `tests/indexing/test_index_cli.py` |
| CI | GitHub Actions pins Python/dependencies, compiles sources, verifies frozen evaluation and expanded-corpus quality, runs the deterministic suite on Ubuntu and Windows, then audits public candidates. | `.github/workflows/ci.yml` |

### Current Full-Rebuild Data Flow

```text
generated manifest.json
  -> strict generated-manifest validation
  -> relative-path confinement
  -> read bytes + byte-count/SHA-256 check
  -> suffix-selected parser reads source
  -> DocumentRecord normalization
  -> tenant/ACL-scoped exact and normalized deduplication
  -> authoritative version-graph validation
  -> deterministic chunking
  -> embed every indexable chunk
  -> rebuild complete FAISS and BM25 artifacts
  -> serialize complete document/chunk/parent artifacts
  -> write version-scoped staging directory
  -> validate manifest, hashes, counts, dimensions, and artifact models
  -> install immutable version directory
  -> validate version again
  -> atomically replace active.json
  -> retrieval loads and validates active snapshot
  -> ACL filter -> metadata filter -> rank/fuse -> parent reauthorization
```

### Reusable Components

- Strict Pydantic domain models and structured `DocumentParseError`.
- Existing PDF/DOCX/text parsers after a new pre-parser asset-validation
  boundary.
- `DocumentRecord`, `DocumentVersion`, version graph checks, and deterministic
  chunking.
- Complete-artifact serialization and `IndexManifest` hash binding.
- Version-scoped staging, validation, immutable installation, atomic activation,
  and explicit rollback.
- `V2IndexSnapshot`, pre-ranking ACL filtering, parent reauthorization, and
  safe access errors.
- Generated-corpus CLI remains the compatibility path and must not be relaxed to
  accept arbitrary enterprise bundles.

### Change Required

- Add a separate strict SourceEvent/bundle contract; do not overload the
  synthetic `CorpusManifest`.
- Replace the current ingestion path's suffix-only trust with pre-parser
  extension/MIME/signature/resource/path validation and quarantine.
- Remove the check-then-parser-read gap for untrusted assets by parsing a
  validated immutable staged snapshot.
- Add EML child-asset extraction without treating headers or body instructions
  as authority.
- Add a revision catalog, optimistic concurrency, idempotency ledger,
  tombstones, and deterministic ChangePlan.
- Add tenant-scoped parsed/chunk/embedding caches whose keys include every
  correctness-affecting version/configuration input.
- Add an incremental assembly path that reuses computation but still emits the
  same complete immutable target-artifact contract.
- Add deletion-residue and failure-injection verification across documents,
  chunks, BM25, FAISS, parent expansion, citation, pointer state, and rollback.
- Add an operator-only lifecycle CLI/API without reopening a public raw ingest
  endpoint.
- Add exact-SHA lifecycle evidence and preregistered paired experiments.

### Decision

Keep `scripts/build_indexes_v2.py` and the generated-corpus path strict and
backward compatible. Add lifecycle orchestration beside it, adapting accepted
revisions into the existing `DocumentRecord`/chunk/index contracts. Reuse the
current full immutable publication boundary; optimize only computation before
target-snapshot assembly.

### Alternatives Rejected

1. **Relax the generated corpus manifest and reuse the current CLI directly.**
   Rejected because it mixes synthetic preset provenance with untrusted
   enterprise source events and weakens a currently tested contract.
2. **Mutate active FAISS/BM25 artifacts in place.** Rejected because partial
   failure, deletion residue, and rollback correctness become materially harder
   to prove.
3. **Replace the existing builder.** Rejected because its artifact validation,
   immutable store, snapshot, and ACL contracts are already useful and covered
   by deterministic tests.

### Known Risks

- `Path.resolve()` containment alone is not a complete Windows
  junction/reparse/TOCTOU defense.
- `ingest_corpus` hashes bytes and then lets a parser reopen the source path,
  leaving a source-replacement window for untrusted inputs.
- Current builder timing combines preparation, embedding, serialization, and
  writes; G0 needs explicit instrumentation before claiming component timings.
- Current artifacts use pickle for BM25 tokens. Hash validation occurs before
  snapshot deserialization, but lifecycle publication must preserve that order.
- In-memory full artifact assembly may dominate wall time even when embedding
  calls fall; performance claims require paired measurement.

### Migration and Compatibility

The new lifecycle path will produce complete artifacts conforming to the
existing `IndexManifest` and `V2IndexSnapshot` contracts. Existing generated
corpus tests remain unchanged. Any required manifest extension must use a
versioned schema, an ADR, migration logic, and backward-compatibility tests.

### Re-evaluate When

Revisit this decision only if measured failure evidence shows that the current
immutable artifact/store contract cannot represent correct deletion, rollback,
or tenant isolation, or if the 2000-document experiment proves full snapshot
assembly itself prevents the required operational behavior.

## ADR-LC-002 - Add an Optional Read-Only Full-Build Phase Observer

Status: Accepted for G0 measurement

Date: 2026-07-26

Requirements: `REQ-LC-005`, `REQ-LC-007`, `REQ-LC-010`

### Context

The current `build_index_artifacts` manifest records only a caller-supplied
start/finish duration. G0 requires directly observed prepare, embedding,
index-construction, serialization, write, and validation durations without
changing index semantics or maintaining a second build implementation.

### Alternatives

1. Report only total wall time and embedding delegate time.
2. Subtract embedding time from total time and call the remainder
   serialization.
3. Copy the builder flow into a benchmark-only module.
4. Add an optional phase observer to the existing builder and keep it disabled
   by default.

### Decision

Choose option 4. The observer receives only a bounded phase identifier and
non-negative elapsed milliseconds. It does not receive document text, paths,
credentials, or mutable builder state. The default remains `None`, preserving
all existing callers and return values.

The benchmark runs each repetition in a fresh child process so process peak RSS
is meaningful per run. Embedding call count is measured by a delegate wrapper,
not inferred from manifest counts.

### Why the Other Options Were Rejected

Option 1 cannot identify a serialization or validation bottleneck. Option 2
mislabels tokenization, FAISS construction, writes, and validation as
serialization. Option 3 can silently drift from the production path and would
measure a benchmark replica rather than the current builder.

### Compatibility

The observer is keyword-only and optional. Artifact bytes, manifest schema,
output layout, validation order, build failure behavior, and the
`IndexManifest` return contract remain unchanged. Tests must prove phase
coverage and unchanged artifact hashes with and without observation.

### Risks

Clock reads and callbacks add small measurement overhead. The observer can also
raise if a caller supplies a broken callback; the G0 benchmark uses a bounded
in-memory recorder and tests it before repeated runs.

### Re-evaluate When

Replace this observer only if a future persistent tracing system can provide
the same phase boundaries without document content, or if measured observer
overhead is material relative to build time.

## ADR-LC-003 - Bind Accepted Evidence with Strict Schemas and Prefix Hashes

Status: Accepted for G1 implementation

Date: 2026-07-26

Requirements: `REQ-LC-009`, `REQ-LC-010`, `REQ-LC-011`

### Context

The G0 journal, decisions, results, failures, traceability rows, and handoff are
human-readable evidence, but no single machine check currently proves their
schemas, references, append-only history, or artifact hashes. A later change
could silently rewrite an accepted paragraph or reuse a record ID unless G1
creates an explicit audit boundary.

### Decision

Use strict Pydantic models with unknown fields forbidden for experiment,
failure, research-request, traceability, handoff, append-anchor, and artifact
hash records. JSONL writes validate the complete existing file, reject duplicate
IDs, append one canonical JSON line through an append-only file descriptor, and
flush it before returning.

An experiment is first registered with all hypothesis, baseline, intervention,
controlled-variable, dataset, repetition, metric, threshold, environment, and
command fields. Results or corrections use a new `experiment_id` and
`revision_of`; validators require all preregistered fields to equal the parent
record. `REGISTERED` and `RUNNING` records cannot contain a final outcome.
`COMPLETED` records require exactly one bounded final status.

At Gate acceptance, each append-only file receives an anchor containing its
repository-relative path, accepted byte length, record count, and SHA-256 of
that exact byte prefix. Future validation requires the file to be at least that
long and the accepted prefix hash to remain equal. This allows suffix appends
while detecting edits or truncation in accepted history.

`CODEX_HANDOFF.json` owns the current anchors because it is the control-plane
state read by the next agent. It is strict and cross-checked against decisions,
requirements, failure records, research requests, and recorded test runs, but
it is not self-anchored. `TRACEABILITY.csv` is likewise a mutable projection
whose identifiers and references are validated rather than prefix-anchored.

Evidence artifact manifests disclose only repository-relative path, byte count,
and SHA-256. Public evidence scanning remains a separate fail-closed check and
must detect credential-shaped values and private or absolute paths without
publishing the matched raw content in lifecycle summaries.

### Alternatives Rejected

1. **Git history alone.** Rejected because dirty, uncommitted Gate evidence must
   still be checked before commit, and cross-file references need semantic
   validation.
2. **Hash the whole file forever.** Rejected because any legitimate append would
   invalidate the accepted hash and encourage destructive rewrites.
3. **Store every historical copy.** Rejected because it duplicates public
   content and increases leak and maintenance surface.
4. **Update an experiment record in place.** Rejected because it destroys the
   distinction between preregistered intent and observed result.
5. **Use an LLM as the evidence validator.** Rejected because schema,
   identity, hash, and prefix checks are deterministic invariants.

### Security Boundary

The validator accepts only bounded repository-relative paths, rejects traversal,
absolute paths, symlinks, duplicate identifiers, unknown fields, and malformed
hashes, and never copies source-document content into evidence. Public scanner
findings block Gate acceptance.

### Compatibility

This package is additive. It does not modify ingestion, retrieval, active index
publication, authentication, or lifecycle business behavior. Existing G0
documents remain valid and become the first accepted evidence prefix.

### Re-evaluate When

Replace the local-file append boundary only when evidence moves to a transactional
append-only store with equivalent immutable history, exact content binding, and
offline export validation.

## ADR-LC-004 - Separate Canonical SourceEvent Semantics from Persistence

Status: Accepted for G2 implementation

Date: 2026-07-26

Requirements: `REQ-LC-002`, `REQ-LC-005`, `REQ-LC-009`, `REQ-LC-010`

### Context

The current generated-corpus manifest is trusted synthetic fixture provenance,
and `govern_documents` receives already parsed `DocumentRecord` values. Neither
contract can represent an untrusted enterprise change request, an idempotency
key, an expected current revision, or a cross-tenant source-key conflict.

G2 needs stable input semantics before file validation, parsing, revision
catalog persistence, and index publication are introduced.

### Decision

Add `app/ingestion/source_events.py` as an additive domain module. A
`SourceEvent` is strict and bounded. UPSERT requires a lexical POSIX relative
content path, declared media type, lowercase content SHA-256, and at least one
ACL group. DELETE requires an expected revision and forbids every content and
ACL field. Both operations require tenant, region, source-system, source-key,
timezone-aware occurrence time, and a pseudonymous actor.

Normalize occurrence times to UTC and ACL groups to sorted unique values before
canonical JSON serialization. Serialize with sorted keys, compact separators,
ASCII escaping, explicit nulls, and non-finite numbers disabled. The SHA-256 of
those bytes is the event payload identity.

Free-form metadata contains only bounded scalar values. Normalize metadata keys
by removing punctuation and case before comparing them with protected event,
tenant, region, source, ACL, actor, operation, and revision aliases. Reject a
protected alias rather than allowing it to shadow the typed field.

Use a process-local `SourceEventLedger` as the G2 public behavior boundary. It
owns accepted event receipts and current source heads:

1. An accepted event ID with the same payload hash returns the original receipt
   as an explicit replay.
2. An accepted event ID with another payload hash raises
   `event_payload_conflict`.
3. A source identity already owned by another tenant raises
   `source_tenant_conflict`.
4. A new source requires no expected revision; an existing source requires an
   exact expected revision.
5. DELETE requires a live existing source and creates a deterministic tombstone
   receipt; replay of that same DELETE remains idempotent.
6. Any conflict occurs before mutation.

The resulting revision ID is `rev_` plus the full canonical payload SHA-256.
This is an opaque G2 concurrency token, not yet a persisted
`DocumentRevision`. Ledger snapshots are strict, sorted, and canonical so a
later Gate can bind them to durable storage without changing event semantics.

### Alternatives Rejected

1. **Reuse the generated `CorpusManifest`.** Rejected because it would mix
   synthetic build provenance with operator-submitted lifecycle events.
2. **Put event fields in free-form metadata.** Rejected because tenant, ACL,
   source, and revision ownership would become overrideable.
3. **Use last-write-wins.** Rejected because concurrent updates would silently
   overwrite one another.
4. **Generate random revision IDs.** Rejected because deterministic replay and
   snapshot equality would require hidden randomness.
5. **Build a durable revision database in G2.** Rejected because transaction,
   recovery, and migration requirements belong with the G5 revision catalog.
   G2 freezes domain semantics and deterministic import/export first.
6. **Call a parser from event validation.** Rejected because G3 must validate
   untrusted assets before parser dispatch.

### Security and Correctness Boundary

G2 never opens `content_relpath`, reads source bytes, trusts document content,
changes authorization, or mutates an index. Lexical path validation is an input
contract only; physical root containment and redirect/reparse checks remain G3.
Conflict exceptions contain bounded identifiers and codes, not source content.

### Compatibility

Existing corpus generation, parsing, `DocumentRecord`, version governance,
builder, index publication, retrieval, and ACL behavior remain unchanged.

### Known Limitations

- Ledger durability and concurrent multi-process locking are not claimed.
- Rejected attempts are not accepted ledger facts and do not reserve event IDs.
- The deterministic revision token is not yet a `DocumentRevision` record.
- Source recreation after a tombstone is allowed only with the current
  tombstone revision as `expected_revision_id`; DELETE of an already deleted
  source is rejected unless it is a replay of the accepted DELETE event.

### Re-evaluate When

Re-evaluate the process-local boundary in G5, when revision-catalog durability,
crash recovery, transaction isolation, tombstone lineage, and migration tests
are implemented.

## ADR-LC-005 - Admit Untrusted Assets Before Parser Dispatch

Status: Accepted for G3 implementation

Date: 2026-07-26

Requirements: `REQ-LC-003`, `REQ-LC-009`, `REQ-LC-010`, `REQ-LC-011`

### Context

`ParserRegistry.parse` selects a parser from the source suffix and then opens
the supplied path. That is appropriate only for an already admitted local
asset. It does not authenticate an operator, constrain a source root, reject
redirecting path components, enforce byte limits, compare declared and detected
types, or isolate malformed content.

Calling the current registry directly on an enterprise source path would mix
authorization, filesystem security, type validation, and parsing in one
failure boundary.

### Decision

Add an additive `admit_source_event_asset` public operation in
`app/ingestion/file_validation.py`. It accepts a canonical UPSERT
`SourceEvent`, an authenticated `Principal`, one existing absolute source root,
one application-owned absolute storage root, and a strict bounded policy.

Check the operator role, tenant, and region before inspecting either root.
Authorization failures contain only a stable reason code. DELETE events cannot
enter file admission.

Resolve the event's canonical POSIX relative path under the source root.
Inspect the root and every path component with `lstat`; reject symbolic links,
Windows junctions, reparse points, non-regular final objects, and multi-link
files. Open the final file once with no-follow flags where the platform
supports them, run `fstat` before reading, and require the opened device/inode
identity to match the pre-open object. This narrows replacement races without
claiming a platform-independent kernel sandbox.

Copy at most `min(max_file_bytes, max_event_bytes) + 1` bytes into a private
incoming directory while computing SHA-256. Never reread the source. Empty and
oversized inputs are rejected and discarded.

Classify the bounded copy using an explicit extension/media/signature matrix:

| Suffix | Declared/verified media |
| --- | --- |
| `.txt` | `text/plain` |
| `.md`, `.markdown` | `text/markdown` |
| `.html`, `.htm` | `text/html` |
| `.csv` | `text/csv` |
| `.jsonl` | `application/x-ndjson` |
| `.pdf` | `application/pdf` |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.eml` | `message/rfc822` |

Textual signatures require bounded UTF-8 data without NUL. HTML, CSV, JSONL,
and EML additionally require minimal format witnesses. PDF requires `%PDF-`.
DOCX requires a ZIP signature and bounded central-directory inspection with
`[Content_Types].xml` and `word/document.xml`; member data is not extracted.

ZIP, RAR, and 7z content that is not an admitted DOCX is quarantined as
`archive_not_supported`. Unknown binary, suffix/MIME/signature disagreement,
event hash mismatch, and invalid DOCX structure are quarantined. Quarantined
payloads use a `.blob` name so the parser registry cannot select them.

`app/ingestion/quarantine.py` owns storage mechanics. Each operation builds one
unpredictably named incoming directory containing a payload and canonical
redacted receipt, flushes files, then renames the complete directory into
`staged/` or `quarantine/` on the same storage root. Any uncommitted directory
is removed on exit. Rejected content has no persisted payload.

### Reason Precedence

Authorization and path errors occur before file access. After a bounded copy,
resource limits precede event hash, archive, unknown binary, extension,
declared MIME, and signature checks. The first deterministic reason is the
receipt reason.

### Alternatives Rejected

1. **Make every parser validate paths.** Rejected because security behavior
   would drift by format and a parser exception could occur before admission.
2. **Trust extension or declared MIME.** Rejected because both are
   caller-controlled.
3. **Use magic bytes alone.** Rejected because many text formats have no unique
   magic and OOXML shares a ZIP container.
4. **Copy with the original basename.** Rejected because it leaks source names
   and permits predictable collisions.
5. **Automatically unpack archives.** Rejected because recursion, expansion,
   encryption, and child-asset limits belong to later explicitly bounded work.
6. **Quarantine an oversized full payload.** Rejected because persisting it
   would violate the same resource bound used to protect admission.
7. **Add an ingestion API in G3.** Rejected because API job semantics and
   operator lifecycle commands belong to G8.

### Security and Correctness Boundary

No document bytes, original basename, source path, or storage absolute path
enter exceptions or receipts. Document content cannot grant permission or
change disposition. The module imports no parser or index builder. A
quarantined asset is data for operator inspection only and is not parseable by
suffix.

### Known Limitations

- Python cannot provide identical no-follow and handle-relative primitives on
  every supported platform. Component checks plus file-identity comparison are
  the G3 portable boundary; stronger OS sandboxing remains deployment work.
- Rejecting files with link count greater than one is conservative and may
  require an explicit trusted-source exception in a future controlled
  connector.
- Minimal type detection is admission screening, not malware analysis.
- G3 storage is local filesystem state, not a distributed transaction log.

### Re-evaluate When

Re-evaluate limits and child-asset accounting in G4 when MIME attachments and
nested messages enter the same validator. Re-evaluate root primitives when a
production connector supplies open directory handles or an OS sandbox.

## ADR-LC-006 - Parse Staged EML With Shared Child-Asset Budgets

Status: Accepted for G4 implementation

Date: 2026-07-26

Requirements: `REQ-LC-003`, `REQ-LC-004`, `REQ-LC-009`, `REQ-LC-010`

### Context

An EML is both one admitted file and a container of more untrusted assets.
Python's MIME parser can represent plain and HTML bodies, transfer-encoded
attachments, nested `message/rfc822` parts, and defects, but it does not enforce
the project's authorization, staging, type-agreement, event-wide resource, or
public-observability contracts.

Calling `get_payload(decode=True)` before checking an encoded part can allocate
the complete decoded attachment. Sending decoded bytes directly to a document
parser would bypass G3. Counting each recursive call independently would let a
deep email reset limits. Treating sender, subject, body, or attachment
instructions as policy would also turn data into authority.

### Decision

Add a dedicated G4 orchestration operation rather than registering `.eml` in
the suffix-only `ParserRegistry`. Its inputs are a strict `SourceEvent`,
authenticated `Principal`, matching `STAGED` `IngestedAsset`, absolute
application storage root, G3 admission policy, and strict EML policy.

The operation repeats the operator, tenant, region, event, receipt, storage
path, file identity, byte-count, and SHA-256 checks before reading MIME. It
parses the already bounded bytes with standard-library `BytesParser` and
`EmailMessage`; it never reopens the original source path.

One parse session owns monotonic counters for:

- root plus child asset count;
- stored root plus decoded child bytes;
- decoded bytes for one child and for all children;
- visited MIME parts;
- nested-message depth;
- HTML input and extracted text;
- aggregate parser output.

Limits are the stricter applicable values from `AssetAdmissionPolicy` and the
G4 EML policy. A nested operation receives the same session object, so recursion
cannot reset a counter. Base64 and quoted-printable payloads are preflighted
from their encoded length before decoding, decoded strictly, and checked again
against the exact byte count.

Add a byte-oriented child admission operation to the G3 validator. It accepts
only a validated parent event, principal, parent receipt, bounded bytes,
declared media type, and filename suffix. It preserves no original basename.
It reuses the same extension/declared MIME/detected MIME/signature matrix and
publishes a parent-linked `IngestedAsset` into staging or quarantine. This is
not a second MIME-specific validator.

For body selection, a multipart body prefers non-attachment `text/plain`.
Only when no plain body exists may bounded HTML be converted to text with a
standard-library non-executing parser. Script, style, template, object, embed,
image, link, and other active or remote elements produce no fetch, execution,
or control action. Signatures and disclaimers remain text.

Each ordinary attachment re-enters child admission and, if staged, the existing
document parser registry through immutable receipt-bound bytes. Each
`message/rfc822` part is admitted as a child EML and recursively parsed by G4.
The parsed model holds internal body/subject data, redacted address values,
child receipts, parsed attachment results, nested results, and bounded warning
codes. A separate public trace model contains no body, subject, address,
filename, source location, exception text, absolute path, or stable content
hash.

### Defect and Failure Policy

MIME defect handling is explicit:

- structural boundary/invariant defects, malformed transfer encoding,
  encrypted content, nesting or resource overruns, child admission quarantine,
  and child parser failure fail closed;
- recoverable standards defects may be represented only by stable, bounded
  warning codes;
- no raw defect string is copied into public trace or evidence.

On a fail-closed result, the root becomes non-parseable quarantine data. Any
already published staged child from that parse is also made non-parseable.
No parsed representation is returned to indexing. Quarantine publication is a
local storage disposition, not proof that content is malware-free.

The root quarantine is published before descendant cleanup. Parent-chain
validation makes staged descendants unreadable as soon as an ancestor has a
quarantine disposition, even when a later child cleanup operation fails.
Quarantine payload transfer is streaming and integrity checked; this prevents
a known-over-limit root from being fully materialized in memory merely to
record its disposition.

`.msg` is outside the RFC 5322/MIME format and receives
`msg_not_supported`; it is never handed to `BytesParser`.

### Reason Precedence

Authorization and strict contract checks precede storage access. Receipt and
stored-payload integrity precede MIME parsing. Structural/depth/part-count
checks precede body extraction. Encoded-size and shared-budget reservations
precede attachment decoding. Child validation precedes child parser dispatch.
The first fail-closed reason becomes the deterministic root parse reason.

### Alternatives Rejected

1. **Register `.eml` directly in `ParserRegistry`.** Rejected because a path
   and suffix do not prove authorization, staging, event ownership, or budget
   lineage.
2. **Trust `EmailMessage.get_content()`.** Rejected because convenience
   decoding does not provide the required pre-decode resource accounting.
3. **Parse attachments in memory without G3.** Rejected because MIME metadata
   and filenames are attacker controlled.
4. **Create one independent budget per nested email.** Rejected because nesting
   would reset limits.
5. **Reject every stdlib defect.** Rejected because some recoverable defects
   can be represented safely as warnings.
6. **Treat every defect as a warning.** Rejected because missing boundaries and
   MIME invariants can change the interpreted asset tree.
7. **Use an LLM to classify MIME safety.** Rejected because authorization,
   type agreement, byte limits, and parser control flow require deterministic,
   reproducible enforcement.
8. **Strip signatures or disclaimers.** Rejected because no evaluated
   correctness experiment supports that transformation.

### Security and Correctness Boundary

G4 proves deterministic parsing of bounded fictional EML fixtures and
fail-closed child handling. It does not prove malware absence, safe rendering
of HTML, production filesystem ACLs, distributed transactions, `.msg`
support, archive extraction, OCR, or that every real-world malformed mail is
recoverable. Parsed content remains untrusted data for the later ingestion and
retrieval safety layers.

### Re-evaluate When

Re-evaluate streaming MIME parsing when admitted EML limits grow beyond the
current bounded-memory envelope. Re-evaluate encrypted or archive attachments
only after a sandboxed worker, decompression budgets, password policy, malware
scanning, and separate threat-model approval exist.

## ADR-LC-007 - Persist Event State and Revisions as One Canonical Catalog

Status: Accepted and implemented in G5

Date: 2026-07-26

Requirements: `REQ-LC-001`, `REQ-LC-005`, `REQ-LC-007`, `REQ-LC-009`,
`REQ-LC-010`, `REQ-LC-011`

### Context

G2 deliberately keeps `SourceEventLedger` in memory. Its snapshot proves
canonical event ordering and linear source lineage, but a restart loses the
state required to detect event replays, stale updates, tenant takeover, and
deletion history. Persisting receipts and revisions in separate files would
introduce a crash window in which an event is accepted without a corresponding
materialized revision, or a revision exists without the accepted event.

G5 must also tell a later incremental builder exactly what changed. A plan that
depends on traversal order, process time, random identifiers, dictionary
insertion order, or the order of independent source events cannot be used as
reproducible evidence.

### Decision

Add one local `PersistentRevisionCatalog` whose authoritative file is a
checksum-bound canonical envelope. The envelope contains one validated
`RevisionCatalogSnapshot`: the complete G2 ledger snapshot and exactly one
`DocumentRevision` per receipt. The catalog publishes only after the event,
revision, head, lineage, checksum, and canonical ordering validate together.

An exclusive cross-process lock serializes the complete read-modify-write
operation. The process hardens and validates the application-owned directory,
holds its directory identity for the transaction, and accepts only bounded,
regular, single-link, non-redirected managed files. Publication writes a
private unpredictable temporary file, flushes it, and atomically replaces the
authoritative file. POSIX synchronizes the held directory descriptor; Windows
uses the existing write-through `MoveFileExW` private-file primitive.

The envelope generation equals its accepted event count and binds the previous
snapshot hash. A separately replaced anchor records the latest confirmed
generation, previous hash, and current hash. The anchor detects a missing
initialized catalog, same-generation divergence, and rollback to an older
internally valid catalog. If a crash leaves the catalog exactly one generation
ahead of the anchor, recovery accepts it only when its previous hash equals the
anchor and then advances the anchor.

A failure before catalog replacement is definitely uncommitted. A failure
after replacement but before directory, anchor, or read-back confirmation is
`catalog_commit_outcome_unknown`. The only safe recovery action is replaying
the same event ID and payload through the G2 idempotency rule.

Every UPSERT revision binds the event payload hash, content hash, declared
media type, ACL, parser identity, normalizer identity, normalized-content hash,
the parent event ID, and staged asset/document pseudonyms. Every DELETE creates a content-free
tombstone that links to the previous revision and inherits the previous ACL.
Historical revisions and tombstones are append-only. A replay may omit
materialization because the original revision is already authoritative; if it
supplies materialization, it must match exactly.

Persistence validation repeats runtime lineage semantics: every root is
UPSERT, DELETE requires a live parent, tombstones inherit region and ACL, and
every revision matches its receipt. Recovery therefore rejects model states
that ordinary `SourceEventLedger.apply` could never create.

Add a pure `build_change_plan` operation. It accepts validated base and target
catalog snapshots, requires the target to be a forward extension of accepted
base history, diffs canonical source heads, and emits sorted classifications.
The plan stores no creation time. Its source-event digest and `plan_id` derive
from canonical JSON inputs. A non-empty base requires its index run and the
target run must be different. Conflict and quarantine dispositions bind their
event, payload, tenant, source, and reason; either makes the plan
non-executable. Materialization changes are distinct from governance changes
so G6 cannot silently reuse parser- or normalizer-dependent computation.

### Alternatives Rejected

1. **Persist only the latest source head.** Rejected because replay,
   provenance, tombstone history, and optimistic-concurrency evidence would be
   lost.
2. **Write one file per event without a catalog transaction.** Rejected because
   partial publication and recovery ordering would become authoritative
   behavior.
3. **Use silent last-write-wins.** Rejected because competing updates would
   hide lost work and invalidate the G2 expected-revision contract.
4. **Use wall-clock timestamps or random UUIDs in ChangePlan identity.**
   Rejected because identical inputs would not reproduce identical plans.
5. **Mutate active index artifacts while applying catalog events.** Rejected
   because governance acceptance and index publication are separate failure
   domains.
6. **Delete historical revisions when a source is deleted.** Rejected because
   rollback, audit, and incident reconstruction require immutable history.
7. **Trust a self-checksummed catalog without an external local anchor.**
   Rejected because an older file can be internally valid while erasing newer
   replay, tenant, and tombstone history.

### Security and Correctness Boundary

The catalog is application-owned local filesystem state, not a distributed
database or consensus protocol. Canonical checksums detect corruption and
non-canonical writes. The private-directory and anchor boundary does not defend
against a same-user host compromise that can replace both catalog and anchor,
nor does it prove survival of real destructive power loss. Production
deployment still requires backup policy, authenticated operator APIs, an
external append-only audit sink, and database-grade recovery tests.

G5 records content and normalized hashes only in the private catalog. Public
evidence contains fixture hashes and aggregate test results, never real source
paths, bodies, filenames, addresses, or stable private content identifiers.

### Re-evaluate When

Move to a transactional database when multiple service replicas, remote
writers, unbounded catalog size, retention policy, or distributed recovery
become in-scope. Preserve the same canonical event, revision, tombstone, and
ChangePlan contracts during that migration.

## ADR-LC-008 - Separate Exact Computation Reuse from Index Publication

Status: Accepted for G6 implementation

Date: 2026-07-26

Requirements: `REQ-LC-001`, `REQ-LC-006`, `REQ-LC-007`, `REQ-LC-009`,
`REQ-LC-010`, `REQ-LC-011`

### Context

The existing full builder correctly produces an independent index version, but
it performs parse, normalize, chunk, embedding, FAISS, BM25, serialization,
and validation in one call. G5 can now say exactly which governed source
changed, but the current `IndexManifest` does not bind a revision-catalog hash,
and cached `DocumentRecord` or `ChunkRecord` values contain tenant and ACL
metadata. A cache keyed only by content text would therefore permit stale
governance or cross-tenant reuse.

G6 must prove exact selective computation before G7 changes the index
publication path. It must also preserve the existing v1 index manifest and full
builder compatibility.

### Decision

Add a private, persistent, flat computation cache with separate strict keys for
parsed, normalized, chunk-layout, and embedding artifacts. Cached content
artifacts deliberately omit tenant, ACL, region, authority, revision,
source-path, and observation-time fields. Canonical key bytes select an opaque
SHA-256 filename; a canonical envelope binds the complete key and payload
hashes. Reads validate private filesystem state, canonical bytes, checksums,
payload models, and vector shape before returning a hit. Writes are serialized,
atomic, immutable, bounded, and idempotent only for byte-identical content.

Cache keys include tenant, source, document, content and the complete relevant
upstream pipeline identity. Every component fingerprint binds a semantic
version, implementation digest, and dependency versions. Parsed keys bind
content, media type, and parser. Normalized keys bind parsed output, accepted
content/normalized hashes, parser, and normalizer. Chunk keys bind normalized
output, parser, normalizer, canonical `ChunkerConfig`, and chunker
implementation. Embedding keys bind normalized chunk text, the complete
parser/normalizer/chunker pipeline, backend, model identifier, model digest,
requested dimension, and normalization. Asset and revision IDs remain in
provenance bindings rather than computation keys: equal accepted content may
be reused only inside the same tenant/source/document namespace. The
downstream policy remains conservative: a parser, normalizer, or chunker
change misses every affected downstream stage even if a fixture happens to
produce equal text. An incorrect hit is a P0 correctness defect.

After parsed/normalized reuse, materialize fresh governed domain records from
the target revisions and run `govern_documents()` over the complete live target
set. Only then compute or reuse content-only chunk layouts. Rebuild every
`ChunkRecord` by projecting the governed target document fields onto that
layout. This preserves whole-corpus duplicate/version behavior and prevents
stale ACL reuse.

Add a G6 computation executor that verifies an executable G5 `ChangePlan`,
target catalog, live target revisions, and, for non-empty plans, the exact base
catalog. The executor reconstructs the expected G5 plan from base, target, run
IDs, conflicts, and quarantine exclusions, then requires complete equality.
It always materializes and governs the complete live target corpus and does
not consume base index artifacts. Therefore a caller-created base-index
binding is neither needed nor trusted in G6. G7 must validate the actual base
`IndexManifest`, run ID, and catalog binding before immutable target assembly
or activation.

The executor emits a deterministic computation manifest and in-memory
artifacts only. The manifest binds the final governed documents, chunks,
embeddings, governance decisions, pipeline, plan, revisions, and tombstones by
canonical SHA-256. A separate measurement object reports callback counts,
cache hits/misses, canonical serialization time, and total wall time; timing
does not enter artifact identity and does not establish a speedup claim.

### Alternatives Rejected

1. **Cache only by chunk text hash.** Rejected because it omits tenant,
   pipeline, model digest, dimension, and source provenance.
2. **Cache complete `DocumentRecord` values by content hash.** Rejected because
   records contain ACL, tenant, revision, and source metadata that can become
   stale even when body text is unchanged.
3. **Modify the v1 `IndexManifest` immediately.** Rejected because G6 does not
   yet build a complete target snapshot and would force an unnecessary
   compatibility migration before G7.
4. **Treat cache corruption as a miss.** Rejected because silent recomputation
   would hide local tampering and make incident evidence ambiguous.
5. **Update FAISS or BM25 in place.** Rejected because it violates the existing
   immutable-version and failure-isolation contracts.
6. **Reuse unchanged governed records without rerunning whole-corpus
   governance.** Rejected because one source can change duplicate selection or
   authoritative-version outcomes for another source.
7. **Let a caller self-certify a base index sidecar in G6.** Rejected because
   a checksum supplied with the object it claims to authenticate is not a
   trust boundary. G6 instead revalidates base-to-target catalog semantics;
   G7 will load and verify the authoritative immutable index manifest.
8. **Reuse downstream output whenever only its immediate payload hash is
   unchanged.** Rejected for this frozen stage because the approved cache
   contract requires parser, normalizer, and chunker changes to invalidate
   affected downstream entries. This sacrifices some possible hits for
   explainable invalidation.

### Consequences and Limitations

G6 can prove callback and embedding-call reuse plus exact invalidation. It
cannot yet claim a faster end-to-end build, a complete incremental index, or
safe activation. Whole-corpus governance and target metadata projection still
run on every execution; only their content-heavy upstream work is cached.

The local private cache is not a distributed cache and does not defend against
a same-user host compromise. Envelope SHA-256 detects accidental corruption,
non-canonical bytes, and mismatched files; it is not a MAC and cannot stop a
same-user attacker from rewriting both payload and checksum. Multi-replica
cache coherence, retention, eviction, backup, sharding, and remote
object-store semantics remain out of scope. The flat private-directory scan
also has an unmeasured scaling cost that must be quantified before any
performance claim.

### Re-evaluate When

Revisit the artifact split if real measurements show governance-only
recomputation is material. Revisit the local cache when multiple writers on
different hosts, unbounded data, eviction, or remote persistence become
requirements. Preserve the exact key and envelope contracts during migration.

## ADR-LC-009: Publish Incremental Computation as a Complete Bound Snapshot

Status: Accepted for G7 implementation

Date: 2026-07-26

Requirements: `REQ-LC-001`, `REQ-LC-007`, `REQ-LC-008`, `REQ-LC-010`,
`REQ-LC-011`

### Context

G6 can selectively reuse parse, normalization, chunk, and embedding work, but
its result is not an index and deliberately contains no trusted base manifest
hash. The existing v1 builder already stages complete versions and atomically
replaces `active.json`, but it starts from raw corpus input, allows a force
replacement path, does not bind a revision catalog, and cannot represent an
empty BM25 corpus.

### Decision

Keep the v1 index manifest for loader compatibility and add a hash-bound
`lifecycle.json` sidecar with a deterministic publication identity. Persist
canonical target catalog, ChangePlan, computation manifest, and ordered
embedding-row evidence as additional manifest artifacts. Reconstruct and
validate every model, mapping, BM25 row, normalized FAISS row, deletion
mapping, and parent reference before no-overwrite installation.

For non-empty plans, derive the base binding by loading the actual immutable
version and its lifecycle/catalog evidence. Reject legacy bases without this
binding. Use one cross-platform publication lock for all store activations,
G7 install/activate operations, and rollback. Recheck expected active base
under the lock. Treat exact publication identity as replay and any different
identity under the same run as conflict.

Support a zero-row target with a real empty `IndexFlatIP` and an in-memory
empty BM25 adapter. On rollback, validate the candidate and fixed-query
citation fingerprint before activation, then append a hash-chained audit event
stating that old data became visible again.

### Alternatives Rejected

1. **Mutate FAISS and BM25 in place.** Rejected because partial failure,
   deletion, and rollback become multi-artifact repair problems.
2. **Trust `base_index_run_id` from ChangePlan.** Rejected because a run ID is
   provenance, not proof that the persisted manifest binds the base catalog.
3. **Add optional unverified catalog fields to manifest v1.** Rejected because
   caller-supplied checksums would look authoritative without stored canonical
   evidence.
4. **Overwrite an existing target run on retry.** Rejected because immutable
   run IDs make replay, incident analysis, and rollback mechanically simpler.
5. **Keep an installed target after injected activation failure.** Rejected
   for the G7 transactional path because the frozen protocol requires failed
   attempts not to leave a loadable failed version.
6. **Reject an all-deleted corpus.** Rejected because deleting the final source
   is a valid enterprise lifecycle operation.

### Consequences and Limitations

Publication writes more evidence bytes and performs full target
serialization/validation even when computation was reused. This is
intentional: reuse reduces selected work but does not weaken release safety.
The lock and rename protocol is single-host; it is not distributed consensus
or an object-store transaction. The local rollback audit is hash chained but
not externally signed, replicated, or atomic with a remote audit sink.

## ADR-LC-010: Expose One Synchronous Authenticated Operator Service

Status: Accepted for G8 implementation

Date: 2026-07-27

Requirements: `REQ-LC-001`, `REQ-LC-002`, `REQ-LC-003`, `REQ-LC-005`,
`REQ-LC-007`, `REQ-LC-008`, `REQ-LC-009`, `REQ-LC-010`, `REQ-LC-011`

### Context

G2-G7 contain the event, admission, catalog, reuse, immutable publication, and
rollback primitives, but only tests compose them. There is no production
operation boundary, no CLI, and no operator API. Building separate orchestration
paths would make authorization order, replay, status, and error behavior drift.
A fake asynchronous job facade would also create an interface promise the
repository cannot currently keep.

Catalog acceptance and index publication span distinct durable stores. A
failure after event acceptance can leave the catalog ahead of the active
index. Hiding that state or rolling back an accepted source event implicitly
would make audit history ambiguous.

### Decision

Add one synchronous operator service used by both CLI and HTTP adapters. It
receives an already verified operator principal plus trusted root
configuration. API requests cannot choose private roots. CLI authentication
uses the existing JWT/JWKS verifier and completes before opening the events
file or resolving the input root. Transport events omit actor identity; the
service derives the canonical actor pseudonym from the principal.

Keep preview side-effect free and explicit about its limitation: it validates
event and conflict semantics against a snapshot but does not claim file
admission. A new or changed UPSERT returns `materialization_pending` and cannot
claim a target catalog hash, plan ID, or executable ChangePlan. DELETE-only and
accepted-replay previews can be exact because their materialization is already
known or not required. Build applies authenticated events through G3-G6 and
publishes through G7. Build without activation and build with G7 CAS activation
are separate operations. Existing-target activation and rollback remain G7
operations under the shared publication lock. Rollback adds a durable intent
before pointer replacement. A post-pointer audit failure is not reported as an
ordinary rollback failure: it returns `activation_outcome_unknown`, and a later
authenticated status or rollback reconciles the intent against the actual
active manifest before appending or cancelling the audit transition.

Persist enough revision materialization provenance to rebuild after process
restart. Exact replay resolves to the accepted receipt and materialization
before file admission. If source state is ahead of the active snapshot after a
failed build, preserve it and report a sanitized `index_update_pending` state;
do not rewrite event history to simulate a transaction.

Expose only synchronous operation results and sanitized status. Define stable
domain error categories shared by CLI exit codes and API responses. Do not
serialize raw exceptions, caller tokens, claims, private roots, source paths,
file names, email fields, or content.

### Alternatives Rejected

1. **Separate CLI and API orchestration.** Rejected because security ordering
   and replay semantics would diverge.
2. **Return a fake job ID.** Rejected because there is no durable queue,
   worker lease, retry ownership, or restart recovery.
3. **Allow API callers to choose input or index roots.** Rejected because an
   operator endpoint is not a general filesystem capability.
4. **Accept a serialized canonical actor from the request.** Rejected because
   identity provenance must come from the verified principal.
5. **Read files during preview.** Rejected because preview must be deterministic
   and free of durable or untrusted-I/O side effects.
6. **Undo catalog acceptance after a build failure.** Rejected because it
   would erase an accepted event while its immutable receipt and admitted
   asset may already exist.

### Consequences and Limitations

G8 is a local, synchronous operation model. A large build holds an HTTP request
open and is appropriate only for controlled operator use. It is not a
distributed transaction, durable queue, scheduler, or multi-host control
plane. Catalog-ahead-of-index recovery is explicit and restartable, but
automatic retries and remote operation leases remain future work.

## ADR-LC-011 - Bind Fictional E2E Evidence to Stable Invariants

**Status:** Accepted in G9

### Context

G2-G8 had strong component and operation-boundary tests, but no single fixture
proved the complete business sequence. A useful public scenario must be
realistic enough to exercise policy, project, operations, and email ingestion
while containing no real organization, user, credential, machine path, or
private document.

The secure staging layer deliberately assigns random asset identities. Those
identities become revision, catalog, ChangePlan, and publication inputs. It is
therefore incorrect to require catalog, plan, or publication hashes from two
fresh isolated runs to be equal. Exact retry within one accepted durable state
must still return the same receipt, plan, and publication identity.

### Decision

Add one canonical, hash-complete, wholly fictional enterprise bundle. Its
loader reads bounded regular-file descriptors, rejects links and path escape,
checks canonical JSON, exact bytes and SHA-256, enforces UTF-8 and a fictional
identity policy, and returns strict operator events only after all assets pass.

Run the bundle through the production operator, admission, parsing, revision,
computation, immutable publication, retrieval, activation, and rollback path.
Use a deterministic test embedding backend only to make lifecycle correctness
offline and reproducible. Label it explicitly and prohibit performance or
retrieval-quality claims.

The public summary records stable run IDs, counts, fixed-query fingerprints,
and Boolean invariants. It excludes random asset, revision, catalog, plan, and
publication identities. Exact retry equality is asserted inside the same
accepted state. A repository-root-relative checksum file binds the summary to
the canonical manifest and every fictional source byte.

### Alternatives Rejected

1. **Publish fresh-run plan and publication hashes.** Rejected because random
   secure-staging identities make them intentionally different.
2. **Replace random asset IDs with deterministic IDs for the demo.** Rejected
   because the fixture must exercise the production security boundary rather
   than weaken it for prettier evidence.
3. **Use real enterprise documents.** Rejected because public proof must be
   redistributable and independently auditable without privacy review.
4. **Call deterministic test embeddings a model benchmark.** Rejected because
   they establish lifecycle behavior only.
5. **Hide the fixture behind pytest only.** Rejected because an offline,
   content-free verification CLI gives reviewers a fast integrity check
   without Ollama, JWT, or network setup.

### Consequences and Limitations

The fixture proves one local single-host lifecycle scenario and exact
invariants around it. It does not establish semantic retrieval quality,
production throughput, private-enterprise acceptance, distributed operation,
or live-model reproducibility. Fresh isolated runs may have different
random-derived internal hashes while producing the same fixed-query
fingerprints and accepted scenario invariants.
