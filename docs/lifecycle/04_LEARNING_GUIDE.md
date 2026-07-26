# Secure Knowledge Lifecycle Learning Guide

## G0 - How the Current Full Rebuild Actually Works

### Problem

Before adding incremental lifecycle behavior, we need to know what the current
system does, which contracts it already protects, and where full rebuild time
is spent.

### Naive Approach

Time one call to the builder and report the fastest number. This is unreliable:
it hides phase costs, model warm state, process memory, artifact instability,
and run-to-run variation.

### Selected Approach

Measure the real `build_index_artifacts` path in a fresh process for every
repetition. A read-only observer records six phase boundaries. A counted
embedding delegate proves the number of model calls. Exact artifact hashes
prove repeated runs produced equivalent outputs.

### Source Entry Points

- `app/ingestion/normalize.py`: load, hash, and parse every source.
- `app/ingestion/versions.py`: choose governed canonical documents.
- `app/ingestion/chunking.py`: produce stable chunks.
- `app/indexing/builder.py`: embed, build BM25/FAISS, serialize, write, validate.
- `app/indexing/benchmark.py`: typed measurement and nearest-rank summaries.
- `scripts/benchmark_full_rebuild.py`: isolated worker coordinator and evidence.

### Data Flow

```text
manifest + source files
  -> parse every file
  -> govern versions and duplicates
  -> chunk every canonical document
  -> embed every indexable chunk
  -> construct normalized vectors, FAISS, and BM25 tokens
  -> serialize documents/chunks/parents/BM25/FAISS
  -> write one complete index directory
  -> reload and validate every artifact and hash
```

This is a complete rebuild. It has no change plan, parse reuse, chunk reuse, or
embedding cache yet.

### Why There Are Two Embedding Backends

The deterministic 128-dimensional delegate is fast and repeatable. It isolates
Python parsing, governance, chunking, BM25, FAISS, serialization, write, and
validation costs. It is not a model-performance substitute.

The installed BGE model measures the actual local request path. It shows that
serial per-chunk embedding dominates wall time at 2000 documents. Both views
are required because replacing one with the other would hide a bottleneck.

### What `P50` and `P95` Mean Here

P50 is the nearest-rank median-like observation: at least half of runs are no
slower than this value. P95 is the nearest-rank high-tail observation. With
only 5 BGE repetitions, P95 is the maximum observed value, so it is useful as
a small-sample bound but not a production SLO estimate.

### Why Peak RSS Uses a Fresh Process

Windows records peak working set from process start. That counter cannot be
reset reliably between two builds in one process. A child process per
repetition makes each peak comparable and also prevents Python object/cache
state from leaking between repetitions.

### Failure Mode 1 - Temp Directory Trust Class

The first full-suite command put pytest fixtures below repository-local
`.tmp/lifecycle`. Existing identity settings correctly reject repository-local
key files outside `.private`, and the evidence CLI correctly treats `.tmp` as
an internal path. Six tests failed.

The fix was not to weaken either validator. Tests now use D-drive
`.private/lifecycle`, which preserves the intended private/external trust class.
See `FAIL-LC-002`.

### Failure Mode 2 - Timestamp as Artifact Input

`ingested_at` is stored in `DocumentRecord` and serialized into
`documents.json`. Two otherwise identical rebuilds therefore have different
artifact hashes if their builder timestamps differ.

The benchmark freezes one builder timestamp across a configuration and records
real observed start/finish separately. See `FAIL-LC-003`.

### Rejected Approaches

- Total time minus embedding time: incorrectly labels construction, write, and
  validation as serialization.
- Copying the builder into a benchmark module: risks measuring a drifting
  replica.
- Deleting warm or slow runs after execution: violates the frozen protocol.
- Batching or caching during G0: would measure an intervention, not the current
  baseline.
- Claiming speedup from fewer mock calls: call reduction is not end-to-end
  latency evidence.

### Tests

- `tests/indexing/test_builder.py`: observer completeness and byte equivalence.
- `tests/indexing/test_full_rebuild_measurement.py`: counts, phases, hashes,
  summary consistency, and mixed-configuration rejection.
- `tests/indexing/test_full_rebuild_benchmark_cli.py`: repetition floors, path
  confinement, and safe run IDs.
- `tests/observability/test_metrics.py`: current versus peak RSS.

### Interview Practice

**Why not implement incremental indexing before measuring?**

Without a current baseline, reduced calls cannot be translated into a measured
benefit. The baseline also shows two distinct targets: preparation work under a
fast deterministic delegate and embedding requests under the real model.

**Why does an immutable full target snapshot still matter after adding reuse?**

Reuse should avoid recomputing unchanged intermediate values, but publication
must still produce a complete independent snapshot. This preserves hash
validation, atomic activation, rollback, and failure isolation.

**What did G0 prove?**

It proved the current full-rebuild flow is repeatedly measurable on the two
frozen synthetic corpora, produces stable artifact sets under controlled
inputs, and passes the existing regression suite. It did not prove incremental
speedup, production scalability, or enterprise-data quality.

### Exercise

Trace one 2000-document build from `_prepare` to `validate_index_directory`.
List which values can be safely reused only after tenant, parser, normalizer,
chunker, embedding model, dimension, and content hashes all match. This becomes
the input to G1/G6 evidence and cache-key design.

## G1 - How the Evidence Boundary Works

### Start with the Problem, Not the Classes

A test report is not automatically trustworthy just because it is JSON. Four
different errors can still occur:

1. The record can omit the hypothesis or threshold that should have been fixed
   before execution.
2. A later result can silently change the original intervention.
3. A human editor can rewrite yesterday's accepted journal paragraph.
4. The handoff can say no failures are open while the failure ledger says one
   is still open.

G1 gives each error a deterministic enforcement point.

### `evidence.py`

`ExperimentRecord` represents both preregistration and later revisions.
`REGISTERED` permits only the planned inputs. `RUNNING` and `COMPLETED` require
a new `experiment_id`, a `revision_of` parent, and a reason. The helper
`validate_experiment_history` compares every preregistered field with the
parent. This prevents a successful outcome from being manufactured by moving
the threshold after the run.

`append_jsonl_record` first obtains an exclusive adjacent lock, reloads and
validates every old line, checks all IDs, serializes one canonical JSON line,
opens the ledger with `O_APPEND`, writes it, and calls `fsync`. This is a local
single-host writer boundary, not a distributed transaction log.

`EvidencePrefixAnchor` protects content already accepted at a Gate. For
example, if the first 5000 bytes of the journal hash to `H`, a later journal may
be 6000 bytes, but its first 5000 bytes must still hash to `H`. This permits a
new suffix and rejects edits or truncation in the accepted prefix.

`EvidenceArtifactHash` binds an artifact by repository-relative path, size, and
SHA-256. Path resolution checks every component so traversal and symbolic-link
redirection cannot make the validator hash an unintended file.

### `validation.py`

The repository validator loads all ten required lifecycle files. It then treats
the handoff and traceability table as projections of authoritative records:

- requirement IDs must exist in the stage contract;
- decision IDs must exist in the ADR file;
- test IDs must be defined by the stage contract;
- experiment IDs must exist in the experiment ledger;
- evidence IDs must exist in the engineering journal;
- handoff open failures must equal all `OPEN` failure records;
- handoff blocking requests must equal all blocking research requests;
- all six append-only files must have valid prefix anchors;
- every declared artifact hash must recompute exactly.

The public scanner is deliberately separate. The schema validator answers
"is this structurally and referentially valid?" The scanner answers "does this
public surface expose forbidden content?" A record must pass both.

### Why No LLM Is Used Here

An LLM may later help judge semantic answer quality, but it is the wrong tool
for exact ID uniqueness, enum states, path confinement, byte lengths, and
SHA-256 equality. Those are binary, reproducible invariants. Using an LLM would
make the same evidence pass or fail differently across runs.

### Failure Boundaries

- A stale lock blocks the writer rather than risking concurrent corruption.
- A partial or malformed JSONL line makes future validation fail closed.
- A changed accepted byte produces an anchor mismatch.
- An unknown field is rejected rather than silently ignored.
- CLI failures disclose only an error code and exception type; they do not echo
  the rejected content into another public log.

### Interview Practice

**Why is `O_APPEND` not enough by itself?**

It controls writes made through that file descriptor, but it cannot stop a text
editor from replacing old bytes. The prefix anchor detects that second class of
tampering.

**Why does a completed experiment need a new ID?**

The original ID is the immutable preregistration. A new revision preserves both
what was planned and what was observed, so thresholds and interventions remain
auditable.

**What is the authority order?**

Append-only JSONL ledgers and accepted prefixes are historical facts.
Traceability and handoff are mutable projections. The validator recomputes the
projection relationships instead of trusting their claims.

**What did G1 not implement?**

No source event, parser, revision catalog, cache, incremental builder, delete,
activation, or rollback behavior. Those begin in later Gates only after this
evidence substrate is accepted.

## G2 - Canonical Events, Idempotency, and Conflicts

### The Business Problem

Suppose an HR system sends an update and times out before it receives the
response. It retries the request. At nearly the same time, another operator
edits the same policy.

The service must answer three different questions:

1. Is this exactly the previously accepted request being retried?
2. Is this event ID being reused for different content?
3. Is this a new request based on an old source revision?

Treating all three as "duplicate" loses data. Treating all three as new writes
can apply the same business operation twice or silently overwrite a concurrent
change.

### Read the Code in This Order

1. Start with `SourceEventModel` in
   `app/ingestion/source_events.py`. It defines legal fields and rejects extra
   input.
2. Read its field and model validators. They normalize values and enforce the
   UPSERT/DELETE split.
3. Read `canonical_source_event_bytes` and
   `source_event_payload_sha256`. They turn a validated event into one stable
   byte representation and identity.
4. Read `SourceEventLedger.apply`. Its check order is part of the behavior:
   replay/payload conflict, source ownership, expected revision, operation
   state, then mutation.
5. Read `SourceEventLedgerSnapshot` and `from_snapshot`. They validate the
   exported ledger as a complete linear history rather than trusting the
   serialized object.
6. Read `tests/ingestion/test_source_events.py` in the same order. Each test
   demonstrates one contract with a small fixture.

### Why Canonicalization Comes Before Hashing

Two payloads can mean the same thing while having different surface forms:

```text
2026-07-26T08:00:00Z
2026-07-26T16:00:00+08:00
```

They represent the same instant. Likewise, ACL groups `["finance", "hr"]` and
`["hr", "finance", "hr"]` represent the same set.

G2 normalizes the time to UTC and the ACL to a sorted unique tuple before
serialization. JSON keys are sorted and separators are fixed. Only then is
SHA-256 calculated. Otherwise a harmless ordering or time-zone difference
would look like an event conflict.

The fixed witness test is important. A round-trip test proves that the current
serializer agrees with itself; a hard-coded expected hash also detects an
unintended future format change.

### Three Identities That Must Not Be Confused

**Event ID** identifies one submitted business command. It supports retry
detection.

**Payload hash** identifies the canonical content bound to that event ID. It
detects event-ID reuse with a different command.

**Revision ID** identifies the accepted resulting source state. In G2 it is a
deterministic concurrency token derived from the payload hash. A persisted
revision record will be introduced later.

The decision table is:

```text
known event ID + same payload hash      -> replay original receipt
known event ID + different payload hash -> event_payload_conflict
new event ID + stale expected revision   -> expected_revision_conflict
new event ID + current expected revision -> apply exactly once
```

### Why Replay Is Checked First

After a DELETE, the source head says "deleted." If a network retry of that exact
DELETE checked source state first, it would fail as `source_already_deleted`.
That breaks idempotency.

The ledger first checks whether the event ID is already bound to the same
payload. If so, it returns the original accepted receipt without consulting the
new current state. A different payload under that ID still conflicts.

### Expected Revision Is Optimistic Concurrency

The ledger does not lock a source while a human reads and edits it. Instead,
the caller submits the revision it observed:

```text
read rev_A
operator 1 applies update based on rev_A -> current becomes rev_B
operator 2 applies update based on rev_A -> conflict, no mutation
```

This is optimistic because concurrent work is allowed, but acceptance requires
the assumption "the source is still at rev_A" to be true. The caller must
reload, compare, and explicitly decide how to resolve the conflict.

### Why DELETE Has No Body or ACL

A delete event says which governed source and current revision should become a
tombstone. Carrying document bytes in a DELETE creates unnecessary retention
and leak risk. Carrying a caller-supplied ACL would let deletion rewrite the
source's authorization history.

The event therefore omits both. The resulting tombstone head preserves the
previous ACL internally so the historical governed identity is not lost.

### Source Ownership and Region

`source_key` by itself is not globally safe. G2 uses
`(source_system, source_key)` as the logical identity and permanently binds it
to one tenant after the first accepted event. Another tenant cannot claim it
after deletion.

Region is also a lineage invariant. Moving a source to another region is not a
normal update because it may have residency and deletion implications. G2
rejects silent movement. A future explicit migration workflow would need a
separate audited design.

### Metadata Is Not a Second Control Plane

Free-form metadata is useful for small business labels, but it must not contain
another spelling of a governed field. G2 removes punctuation and ignores case
when comparing keys with protected aliases:

```text
tenant_id
Tenant-ID
tenant.id
TenantId
```

All normalize to the same protected concept and are rejected. Typed fields
remain the only authority for tenant, region, source, ACL, actor, operation,
content identity, and expected revision.

### Why Lexical Path Validation Is Not File Safety

G2 rejects obviously unsafe path syntax without touching the filesystem. This
prevents absolute paths, `..`, backslashes, drive prefixes, URI-like values,
and NULs from entering the domain event.

That does not prove that a real path stays under an allowed root. A harmless
relative path can later traverse a symbolic link or Windows reparse point.
Physical containment, redirect rejection, MIME/signature checks, resource
limits, staging, and quarantine are G3 responsibilities.

### Snapshot Validation

Export/import is useful for tests and for defining a future persistence
contract, but accepting any hash-consistent JSON would be unsafe. G2 verifies:

- event IDs, source identities, and resulting revision IDs are unique;
- records are in canonical order;
- each receipt's revision is bound to its payload hash;
- tenant, region, source identity, and deletion state agree with the head;
- each previous revision exists;
- there is one root and no branch, cycle, or disconnected record;
- the current head points to the lineage tip.

Import constructs fresh immutable values. It does not retain mutable objects
owned by the caller.

### Common Wrong Implementations

- **Last-write-wins:** hides concurrent business conflicts.
- **Duplicate ID means success:** accepts a changed payload under an old ID.
- **Hash raw input JSON:** treats harmless ordering differences as conflicts.
- **Random revision token:** makes deterministic replay and test snapshots
  depend on hidden randomness.
- **DELETE with document body:** retains data that deletion did not need.
- **Only freeze the outer model:** nested lists can still mutate accepted state.
- **Validate hashes but not lineage:** permits branches, missing parents, or a
  head that points into the middle of history.
- **Call the parser during event validation:** crosses the untrusted-file
  boundary before G3 controls exist.

### What the Tests Prove

The 51 focused tests cover legal UPSERT/DELETE records, a fixed canonical hash,
unsafe and malformed inputs, replay, every conflict class, no-mutation on
conflict, tombstone recreation, immutable values, deterministic commuting
order, and snapshot tampering.

The wider ingestion, lifecycle, index, ACL, public-audit, and full suites prove
that the additive module did not regress existing behavior. They do not prove
database durability or real enterprise ingestion.

### Interview Practice

**What is the difference between idempotency and optimistic concurrency?**

Idempotency recognizes a retry of one already accepted command and returns the
same result. Optimistic concurrency rejects a new command when the source has
changed since the caller read it. Event ID plus payload hash solves the first;
expected revision solves the second.

**Why not use an LLM to decide whether two events are the same?**

Event equality is a security and transaction invariant. It must be byte-stable,
fast, reproducible, and independently auditable. Semantic similarity would
make different commands look equal and could vary by model or prompt.

**Why is the ledger process-local?**

G2 freezes domain semantics before choosing persistence. A real durable ledger
needs transaction isolation, crash recovery, file or database locking,
migrations, and concurrent-writer tests. Claiming those from an in-memory
dictionary would be false. G5 will add the durable revision catalog around the
already tested event contract.

**Why preserve ACL on a tombstone?**

DELETE should remove current content, not erase the governed identity and
authorization history of the source. Preserving prior ACL supports audit and
prevents the delete command from injecting a replacement ACL.

**How do you know a rejected event did not partially apply?**

All conflict and validation checks occur before the receipt and source-head
maps are changed. Tests snapshot the ledger before a rejected operation and
assert canonical state equality afterward.

### Exercise

Use the test fixture to create an UPSERT at `rev_A`. Construct two updates that
both expect `rev_A`. Apply them in both orders and explain why the first
succeeds, the second conflicts, and neither order can silently erase the other
command. Then contrast this with two events for different source identities,
whose canonical final snapshot is order-independent.

## G3 - Why Files Must Be Admitted Before They Are Parsed

### The Boundary in One Sentence

A parser answers "what information is inside this already trusted local
asset?" G3 first answers "is this caller allowed, is this the intended file,
is it bounded, what type is it, and where can it safely live?"

Mixing those questions lets a malformed file execute expensive parser work or
leave partial state before authorization and containment have finished.

### Read the Code in This Order

1. Read `AssetAdmissionPolicy` and `admit_source_event_asset` in
   `app/ingestion/file_validation.py`.
2. Follow `_revalidate_contracts` and `_authorize`. Notice that neither reads a
   path.
3. Read `_bounded_source_path`, `absolute_path_has_redirect`, and
   `_open_verified_source`.
4. Follow `_copy_and_hash`; the source is read once into an application-owned
   bounded payload.
5. Read the reason precedence in the bottom half of
   `admit_source_event_asset`.
6. Read `IngestedAsset` and `SecureAssetStore` in
   `app/ingestion/quarantine.py`.
7. Read `tests/ingestion/test_file_validation.py` by behavior: valid staging,
   disposition, authorization, path attacks, race injection, publication
   failure, and receipt invariants.

### Lexical and Physical Path Safety Are Different

G2 rejects event strings such as `../file`, absolute paths, drive escapes, UNC,
backslashes, NUL, and empty components. That is lexical safety.

The string `department/policy.pdf` can still be physically unsafe:

```text
source-root/
  department -> junction to another directory
```

G3 uses `lstat`, which describes the path object itself rather than following
it. It checks every existing absolute root component and every relative source
component for:

- symbolic-link mode;
- Windows reparse-point attributes, including junctions;
- a non-regular final object;
- more than one hardlink.

The real Windows RED test showed why checking only the final root is
insufficient. A root below a junction looks like an ordinary directory when
only the last component is inspected.

### Why Check Again After `open`

An attacker can replace a file between `lstat` and `open`:

```text
lstat policy.pdf -> inode A
replace policy.pdf
open policy.pdf  -> inode B
```

G3 opens with `O_NOFOLLOW` where Python exposes it and immediately runs
`fstat` on the open descriptor. Device and inode must equal the pre-open
metadata before any bytes are read. This narrows a time-of-check/time-of-use
race.

It is not a universal kernel sandbox. Python and Windows do not expose
identical handle-relative primitives. That limitation is explicit rather than
hidden under a "secure" name.

### Why Reject Hardlinks Conservatively

A hardlink is a second name for the same file object. It can stay lexically
inside the root while another name outside the root mutates the same bytes.
G3 rejects `st_nlink > 1`.

This can reject a legitimate connector that deliberately uses hardlinks. Such
a connector would need a separately reviewed trust contract. Silent acceptance
would weaken the default boundary.

### Authorization Must Precede Storage Creation

The service checks:

1. `rag.operator` role;
2. principal tenant equals event tenant;
3. principal region equals event region;
4. operation is UPSERT.

Only after those checks can it inspect source or storage roots. Tests pass
nonexistent "must not touch" paths to unauthorized principals and verify that
no directory appears. This proves order through behavior rather than a source
code assertion.

Document bytes cannot grant a role because authorization is complete before
the bytes are opened.

### Why Revalidate an Already Typed Model

Pydantic normally validates model construction, but internal code can use
`model_copy(update=...)` or `model_construct` and produce an instance whose
fields did not pass validators.

The RED test forged `../outside.pdf` into a `SourceEvent` and the first G3
implementation staged the outside file. The public operation now serializes
and revalidates SourceEvent, Principal, and policy. Validation errors become
bounded admission codes and do not echo rejected data.

This is defense in depth at a security boundary, not a claim that every
internal function must distrust every object.

### One Bounded Copy

The source descriptor is read in chunks until EOF or one byte beyond the
effective limit:

```text
effective limit = min(max_file_bytes, max_event_bytes)
```

During that same pass G3 writes `payload.part` and computes SHA-256. It never
opens the enterprise source a second time. One extra byte distinguishes "equal
to the limit" from "larger than the limit" without reading the entire oversized
file.

Empty and oversized copies are removed. A full oversized payload is not placed
in quarantine because doing so would defeat the resource bound.

### Extension, MIME, Detection, and Signature

These values have different trust:

- suffix comes from the source name;
- declared MIME comes from the event caller;
- detected MIME is derived from the bounded copy;
- a signature is the concrete witness used by detection.

Acceptance requires the explicit suffix-to-media matrix and a compatible
content witness. No one signal is authoritative.

For binary formats:

- PDF starts with `%PDF-`;
- ZIP, RAR, and 7z signatures identify unsupported archives;
- DOCX starts as ZIP and then must pass bounded OOXML structural checks.

For text formats, unique magic often does not exist. G3 requires UTF-8 without
NUL, then checks stronger witnesses for HTML, EML, JSONL, and CSV. Markdown is
accepted as safe text only when suffix and declared media both say Markdown.
It is not falsely reported as independently magic-detected Markdown.

### DOCX Without Archive Extraction

DOCX is a ZIP container. G3 reads central-directory metadata but does not
extract member bodies. It enforces:

- bounded member count;
- unique safe logical member paths;
- no absolute, backslash, dot, or traversal names;
- no encrypted members;
- bounded declared member and total uncompressed sizes;
- bounded compression ratio;
- required `[Content_Types].xml` and `word/document.xml` witnesses.

Safe explicit directory entries such as `word/` are allowed. An ordinary ZIP,
including one renamed to `.docx`, remains quarantined unless all DOCX
conditions hold.

This is format admission, not malware scanning and not final DOCX parsing.

### Staging Is a Small Filesystem Transaction

Each asset receives an unpredictable `asset_<32 hex>` identifier. The store
creates:

```text
.incoming/asset_<id>/
  payload.part
```

After disposition, it renames the payload, writes and fsyncs canonical
`receipt.json`, then renames the complete directory into:

```text
staged/asset_<id>/
```

or:

```text
quarantine/asset_<id>/
```

Because incoming and final directories share one storage root, final directory
publication is a same-filesystem rename. If copy, receipt write, fsync, or
rename fails, the context removes the entire incoming directory.

### Quarantine Is a State, Not an Exception

A quarantined receipt binds:

- event and random asset identity;
- declared and detected media;
- actual byte count and SHA-256;
- stable reason code;
- a relative application storage path;
- UTC creation time.

Its payload is always named `payload.blob`. The current parser registry selects
by suffix, so a quarantined PDF, archive, or EML cannot accidentally enter a
parser through its original suffix.

Exceptions are used for authorization, root, resource, and storage failures
where no complete quarantined fact can safely be published.

### Why Receipts Need Cross-Field Validation

`extra="forbid"` and frozen fields do not prove that fields agree. Before
hardening, this object was legal:

```text
status = STAGED
reason = signature_mismatch
path   = quarantine/.../payload.blob
```

The model now binds disposition to path, reason, hash, size, and verified type.
This matters when `receipt.json` is loaded later rather than constructed by the
same function.

### Zero-Leak Design

Receipts contain:

- application-generated asset ID;
- event ID;
- redacted name with only an allowlisted short suffix;
- relative storage path;
- type, size, hash, reason, and time.

They do not contain original basename, source path, storage absolute path, or
body bytes. Exceptions use stable messages and codes. G3 does not emit content
logs.

### Common Wrong Implementations

- Call the parser and catch its exception as "validation."
- Compare a resolved path with a root string but ignore intermediate reparse
  points.
- Check a file before opening but never compare the opened object.
- Read once for MIME detection and again for staging.
- Keep an oversized full file in quarantine.
- Use the original filename inside application storage.
- Quarantine under `.pdf` or `.docx`, allowing suffix-based parser dispatch.
- Write payload first and receipt later into the final directory.
- Trust a Pydantic instance that was copied without revalidation.
- Put application storage below the connector source root.
- Claim ZIP member limits while automatically extracting the archive.

### Interview Practice

**What is the difference between staging and quarantine?**

Staging contains a complete asset that passed the G3 admission contract and is
eligible for a later parser. Quarantine contains a complete bounded asset that
failed a content/type/hash policy but is retained for operator inspection. Its
`.blob` name is deliberately not parseable by the registry.

**Why not rely on `Path.resolve()`?**

Resolution follows redirects. It can prove where a path resolved at one moment,
but it does not explain which component redirected or bind the object later
opened. G3 checks components with `lstat`, opens with no-follow where possible,
and compares `fstat` identity.

**Why is a content-hash mismatch quarantined instead of rejected?**

The actual file was safely bounded and copied, but it differs from the event's
claimed identity. Retaining the isolated copy and receipt gives an operator an
auditable conflict without allowing the payload into a parser.

**Why are archives quarantined?**

Archive extraction introduces recursive child counts, total expanded bytes,
compression bombs, encryption, member path traversal, and nested format
policies. G3 has not implemented that contract. DOCX receives only a narrow,
bounded structural exception.

**How did you prove no parser or index side effect?**

The test replaces `ParserRegistry.parse` with a function that fails if called,
submits a quarantined asset, and observes zero calls. It also snapshots an
existing active pointer and directory, then verifies byte and entry equality.

**What does G3 not prove?**

It does not prove EML attachment recursion, full parser correctness, malware
absence, production ACL configuration, distributed durability, lifecycle API
authorization, or successful index publication. Those are separate Gates.

### Exercise

Trace the Windows junction RED test. Explain why `lstat` on only the final
source root missed the redirect, why walking from the drive anchor found it,
and why the later device/inode comparison still remains necessary for a
different race class.

## G4 Beginner Guide: Safe EML and Child Assets

### What an EML really contains

An EML starts with headers, a blank line, and a body. MIME lets that body become
a tree containing plain text, HTML, attachments, inline media, and complete
nested emails. Therefore EML is both a document and a container format.

G3 admitted the root file. It did not admit any decoded child inside it.

### Why G4 is not registered by suffix

The existing `ParserRegistry` receives only a path. G4 must also prove:

- authenticated operator role;
- tenant and region ownership;
- exact SourceEvent and receipt relationship;
- root byte count and SHA-256;
- parent-child lineage;
- one recursive event-wide resource budget.

The public entry is therefore
`app.ingestion.email_parser.parse_staged_email`. It is an orchestration
operation around the MIME parser, not a suffix-only parser.

### Root checks before MIME

The code performs these steps in order:

1. reconstruct and validate event, Principal, and policies;
2. enforce operator role, tenant, region, and UPSERT;
3. reconstruct the root receipt;
4. bind event ID, hash, and declared MIME to the receipt;
5. require root status STAGED and verified `message/rfc822`;
6. compare canonical stored receipt bytes;
7. reject redirects, non-regular files, and multi-link files;
8. compare stored byte count and SHA-256;
9. enforce current root size policy;
10. call stdlib `BytesParser`.

The original source path is never reopened.

### Plain and HTML

For `multipart/alternative`, G4 explicitly requests:

```python
message.get_body(preferencelist=("plain", "html"))
```

HTML fallback uses `HTMLParser`, not a browser. It has no HTTP client, CSS
engine, or JavaScript engine. Attributes are ignored and active/remote element
content is suppressed. Output is bounded while it is accumulated.

Signatures and disclaimers remain because no experiment proves that deleting
them improves correctness without deleting useful facts.

### Transfer encoding versus charset

Transfer encoding turns email transport text into bytes:

- Base64 uses four ASCII characters for up to three bytes.
- Quoted-printable represents selected bytes as `=XX`.
- 7bit, 8bit, and binary preserve more direct byte forms.

Charset then turns text bytes into Python text. A byte can be invalid UTF-8 but
valid ISO-8859-1. G4 preserves exact decoded bytes first and applies the
declared charset second.

Base64 length and padding are checked before allocation, then
`b64decode(validate=True)` is used. Quoted-printable validates every `=` before
calling the forgiving decoder. Exact byte size is checked again after decode.

### Every attachment re-enters G3

Filename, suffix, declared MIME, and bytes are attacker controlled.
`admit_child_asset_bytes` creates:

- a random child asset ID;
- parent event and parent asset lineage;
- a suffix-only redacted name;
- independent byte count and SHA-256;
- a new STAGED or QUARANTINED disposition.

The same G3 extension/MIME/signature matrix handles roots and children. A PDF
called `.txt` is not accepted as text.

### One budget crosses recursion

A nested message does not get fresh limits. `_ParseSession` is shared across
the entire tree. Counters only increase for parts, child count, bytes, output,
and nesting.

This is an important Agent rule:

> Recursive work consumes the parent budget; recursion does not reset
> authority or resources.

### Why there are two child phases

Preflight inspects and decodes all bounded children without publishing them.
This catches a late count, size, depth, or encoding failure before any child is
staged.

Publication then admits each child through G3 and parses only staged receipts.
If a later publication step fails, the root is quarantined first. That
immediately blocks reads of staged descendants through parent-chain
validation. Child cleanup then gives each descendant its own quarantine
disposition where possible.

### Why quarantine copies before publishing

Mutating a staged directory through several renames can stop halfway. G4 builds
a complete quarantine object in `.incoming`, fsyncs it, and publishes the
directory once. A published quarantine twin makes a stale staged copy
ineligible even if old-directory cleanup fails.

Fault-injection tests prove:

- failure before publication leaves the original staging valid and cleans
  `.incoming`;
- failure after publication leaves quarantine authoritative and stale staging
  unreadable.

### Why no LLM is used

An LLM should not decide identity, root containment, hash equality, byte
limits, base64 validity, parser eligibility, or receipt consistency. Those are
deterministic security properties.

The attachment prompt-injection sentence is parsed as document text. It has no
code path to Principal, policy, parser choice, or tool capability. Later LLM
use receives that text as untrusted data; it does not replace G4 controls.

### Important bugs and fixes

**HTML became empty after `<link>`.** Link is a void element and has no closing
tag. Treating it as paired kept suppression active forever. Void active
elements are now ignored without altering paired suppression state.

**A valid 8-bit mail was quarantined.** The stdlib display string contained
replacement characters, but its decoded payload preserved exact bytes. G4 now
uses bytes first and the declared charset second.

**The first quarantine transition was not failure-atomic.** In-place renames
were replaced by complete private construction, one directory publication,
and staged supersession.

**Valid stored receipts suddenly failed child admission.** The event inventory
loaded canonical JSON into a Python dictionary and then used strict Python
validation. JSON timestamps are strings, so strict validation rejected them.
The fix is `model_validate_json(raw)`, followed by the same canonical-byte
comparison. Strict JSON validation and strict Python-object validation are
different input contracts.

**A stricter mail limit still allocated the whole mail.** The first G4 entry
read the admitted file before comparing it with the runtime mail limit. The
final path chooses the over-limit reason from the bound receipt first and
streams the quarantine copy while recomputing size and SHA-256.

**Child cleanup could fail before the root was quarantined.** Failure handling
now publishes the root quarantine first. Parent-chain validation then blocks
every staged descendant even if physical child cleanup later fails.

**A parser could read different bytes between two hash checks.** Checking a
path before and after parsing does not prove which bytes the parser observed.
G4 now passes immutable bytes into text, HTML, CSV, JSONL, PDF, and DOCX
parsers. The receipt hash is compared with those same bytes before dispatch.

**Two child admissions could both spend the final event slot.** The old
inventory and publication were separate operations. A hashed event lock now
covers parent verification, inventory, limit checks, and publication. The lock
uses a native Windows or POSIX file lock so separate service processes share
the same critical section.

**Nested mail CRLF bytes became shorter.** Default email serialization writes
LF and may refold headers. Nested EML now uses CRLF and disables source-header
refolding; regression tests bind its exact byte count and SHA-256.

**The output budget counted only primary text.** It now counts returned
subject, redacted addresses, date, warnings, sections, tables, metadata,
locators, and parser structured strings. Parsed outcomes also reject false MIME
counts, false child-byte totals, and duplicate tree references.

**A public SHA-256 still disclosed a content fingerprint.** Even without body
text, the same hash lets observers correlate equal content across tenants or
test a known candidate. Public mail traces no longer contain content hashes.

### Interview questions

**Why standard-library MIME?** MIME grammar is established protocol logic. The
project adds enterprise controls around a proven parser: identity, budgets,
type validation, lineage, quarantine, and observability.

**How do you stop attachment bombs?** Check encoded size before decode, exact
size after decode, and share count/byte/depth/output budgets across the tree.
Archives are not extracted.

**How is prompt injection contained?** Typed Principal/event/policy objects
control behavior. Content can only become parsed data.

**How is an attachment parse bound to its receipt?** G4 compares immutable
child bytes with the receipt SHA-256 and gives those same bytes to a parser that
supports in-memory input. The parser never reopens the mutable staged path.

**What is public?** Only a pseudonymous asset ID, parser version,
status/reason, counts, decoded bytes, and warning codes. Not hashes, body,
subject, addresses, filenames, paths, or raw errors.

**What remains for production?** Malware scanning, sandboxed workers,
distributed recovery, production ACLs, streaming large mail, encrypted mail,
archive policies, `.msg`, OCR, and operational retention.

### Exercise

Trace `mixed_attachment.eml` through SourceEvent, root IngestedAsset,
`_PreparedChild`, child IngestedAsset, child ParseResult,
EmailAttachmentResult, internal EmailParseOutcome, and EmailPublicTrace. At
each step, identify trusted control fields, untrusted content, and public-safe
fields.

## G5 Durable Revision Catalog and ChangePlan

### The problem G5 solves

G2 knew how to accept one event safely, but its ledger lived only in Python
memory. After a restart, the service forgot:

- which event IDs were already accepted;
- the current revision of each source;
- which tenant owns a source key;
- whether the source is live or deleted;
- the previous revisions needed for audit.

G5 makes that state durable without changing the G2 rules. It does not let a
second persistence-specific implementation decide conflicts. It restores the
tested G2 ledger, calls `apply`, and persists the resulting ledger and revision
together.

### The four identifiers

Do not treat these as interchangeable:

- `event_id` is the caller's idempotency identity.
- `payload_sha256` hashes the complete canonical SourceEvent.
- `revision_id` is `rev_` plus that event payload hash.
- `asset_id` is the pseudonymous staged file used to materialize an UPSERT.

`RevisionMaterialization.parent_event_id` prevents a staged provenance record
from being rebound to another event. Its content hash must also equal the
event content hash. Parser name/version, normalizer version, normalized hash,
and document ID explain how admitted bytes became index input.

### Why event receipt and DocumentRevision are both needed

The receipt proves event acceptance, optimistic concurrency, and the previous
and resulting revision IDs. `DocumentRevision` adds the private governance and
materialization facts needed by indexing. The catalog validator requires
exactly one revision per receipt and one receipt per revision.

For every source lineage:

- the first revision must be UPSERT;
- every following revision points to the previous tip;
- the chain cannot branch or cycle;
- DELETE requires a live parent;
- a tombstone has no content or materialization;
- a tombstone inherits region and ACL;
- the source head points to the chain tip.

These checks run during deserialization because persisted bytes are recovery
input. "The normal API cannot create it" is not sufficient.

### Atomicity and the uncertain-commit case

The catalog and ledger are not written separately. A complete next snapshot is
serialized, flushed, and atomically replaces `catalog.json`.

There are two different failure classes:

1. Before replace: the old catalog is still authoritative. The error is a
   confirmed publication failure.
2. After replace: the new catalog may already be authoritative even if
   directory sync, anchor update, or read-back failed. The error is
   `catalog_commit_outcome_unknown`.

For class 2, never guess a compensating DELETE. Retry the same event ID and
payload. If the commit happened, replay returns the accepted revision. If it
did not, the event applies once.

This is the same practical problem seen in payment and message-processing
systems: a client can lose the acknowledgement after the server commits.
Idempotency resolves the uncertainty.

### Why there is an anchor

A SHA-256 inside one file detects accidental modification, but an older
catalog can still contain a perfectly valid checksum. It may erase newer event
and tenant history.

The catalog envelope therefore contains:

- `generation`, equal to accepted event count;
- `previous_snapshot_sha256`;
- `snapshot_sha256`.

The separate anchor records the highest confirmed generation, previous hash,
and current hash. Recovery accepts either an exact match or one forward
generation whose previous hash equals the anchor. It rejects a missing
initialized catalog, rollback, same-generation divergence, and a jump that
cannot be explained by one interrupted anchor update.

The anchor is not a blockchain and not a remote audit service. A same-user host
attacker who can replace both files remains outside the local trust boundary.

### Why the directory is part of the transaction boundary

An atomic rename is useful only if the directory is trusted. G5 reuses the
project's private filesystem primitives to:

- require an absolute non-redirected directory;
- apply and verify owner-private ACL/mode;
- hold the directory identity during the transaction;
- reject symlink, junction/reparse, directory, and hardlinked file entries;
- use unpredictable exclusive temporary names;
- use POSIX directory `fsync` or Windows write-through replacement.

Tests use future-time process starts and a separate process that holds the
lock. The second process must time out. This proves actual contention rather
than merely creating two tasks that might run one after another.

### How ChangePlan remains deterministic

ChangePlan is a pure diff of two validated snapshots. It has no `created_at`
and no random plan ID. It sorts every source and exclusion, hashes canonical
JSON, and derives `plan_id` from those inputs.

Reason precedence matters for G6:

| Difference | Classification | Reuse implication |
| --- | --- | --- |
| New live source | `new_source` | compute all |
| Deleted then live | `source_restored` | compute target |
| Raw content hash | `content_changed` | invalidate parse onward |
| Parser/normalizer/media/output identity | `materialization_changed` | invalidate affected compute |
| Region or ACL | `governance_changed` | rebuild governed artifacts |
| New revision, same index inputs | `revision_only` | reuse compute |
| Same head | `unchanged` | reuse compute |
| Live to tombstone | `source_deleted` | exclude from target |
| Existing tombstone | `tombstone_retained` | remains excluded |

A non-empty base must name its existing immutable index run, and the target run
must be different. G5 still does not claim that the base manifest actually
contains the base catalog hash; G6/G7 must add and revalidate that binding.

### Interview questions

**Why not just store the latest document?** Because replay detection,
optimistic concurrency, deletion audit, rollback analysis, and provenance all
need immutable history.

**Why not update FAISS immediately after an event?** Catalog acceptance and
index publication are separate failure domains. G5 changes governance state;
G6/G7 build and validate a complete target before switching `active.json`.

**What does a tombstone delete?** It deletes nothing physically. It marks the
new source head as deleted. A later target index excludes that source, while
old immutable snapshots and historical revision records remain auditable.

**How do competing writers behave?** One native file lock covers load through
publication. After the first writer advances the head, the second writer's old
expected revision produces an explicit conflict.

**Is this production distributed storage?** No. It is a hardened local
single-node transaction boundary. Multiple service replicas, remote writers,
large catalogs, online migration, external audit, and real power-loss testing
need a transactional database and deployment work.

### Exercise

Start with an empty catalog. Trace UPSERT A, replay A, UPSERT B with A as the
expected revision, DELETE C, and a stale competing UPSERT D. For each step,
write down the event status, source head, previous/resulting revision, envelope
generation, anchor action, and ChangePlan classification.

## G6 Exact Parsed, Chunk, and Embedding Reuse

### What G6 actually changes

Before G6, the builder repeats this work for every source:

```text
accepted revision
  -> parse bytes
  -> normalize text
  -> materialize governed DocumentRecord
  -> govern the complete corpus
  -> chunk canonical documents
  -> embed indexable chunks
  -> build index artifacts
```

G6 caches only the expensive content computations in the middle. It does not
build FAISS/BM25 or switch `active.json`; those are G7 responsibilities.

The new flow is:

```text
strict base + target catalogs
  -> reconstruct and verify ChangePlan
  -> parsed cache lookup or parse
  -> normalized cache lookup or normalize
  -> fresh target DocumentRecord with current ACL/revision
  -> govern every live target document
  -> chunk-layout cache lookup or chunk
  -> fresh target ChunkRecord with current ACL/revision
  -> embedding cache lookup or embed
  -> deterministic computation manifest + measurements
```

Source entry:
`app/indexing/incremental_computation.py::execute_incremental_computation`.

Persistent cache:
`app/indexing/computation_cache.py::PersistentComputationCache`.

Tests:
`tests/indexing/test_computation_cache.py` and
`tests/indexing/test_incremental_computation.py`.

### Why there are four cache stages

A single final-result cache cannot express partial invalidation:

- Parser changes should not reuse parsed output.
- Normalizer changes may reuse parsing but not normalization.
- Chunker changes may reuse parsed/normalized output but not chunks.
- Embedding-model changes may reuse every text artifact but not vectors.

Four stages let the result report the exact first miss and every required
downstream miss. They also make failure recovery useful: if embedding fails,
the successfully published parsed, normalized, and chunk artifacts can be
reused by the retry.

### Content artifact versus governed record

`ParsedContentArtifact`, `NormalizedContentArtifact`, and
`ChunkLayoutArtifact` deliberately contain no tenant ACL, region, authority,
revision time, or source path.

This does not mean the cache is cross-tenant. The key still includes tenant,
source, and document namespace. It means a cached payload cannot itself carry
stale authorization into the next target.

For every run, G6 creates a fresh `DocumentRecord` from the current
`DocumentRevision`. It checks tenant, region, ACL, checksum, normalized hash,
parser identity, text, structured sections, and deterministic revision time.
After whole-corpus governance, a cached chunk layout is projected onto the
fresh document, creating new `ChunkRecord` values with current ACL and version
fields.

Common mistake: caching a complete `ChunkRecord` by text hash. The text may be
equal while ACL changes from `group-employees` to `group-legal`. Reusing the
old record would be an authorization bug.

### What each key proves

| Stage | Important key inputs | Why |
| --- | --- | --- |
| Parsed | tenant/source/document, content hash, media type, parser semantic version, implementation digest, dependencies | Equal bytes parsed by different code are not assumed equal |
| Normalized | parsed payload hash, expected normalized hash, parser and normalizer fingerprints | Normalization is bound to accepted provenance and actual parser output |
| Chunk | normalized payload/hash, parser, normalizer, chunker and canonical config hash | The frozen policy invalidates downstream work when upstream components change |
| Embedding | tenant/source/document, normalized chunk text hash, complete content-pipeline hash, backend/model ID/model digest/dimension/normalization | Equal text from the wrong pipeline, tenant, model weights, or vector shape is not a hit |

`semantic_version` is a human release label. `implementation_sha256` binds the
actual implementation identity. `dependency_versions` captures behavior that
may change outside the component file. The model digest is separate because
the same model name can point to different weights.

The current policy is conservative. If a parser implementation changes but
produces exactly equal normalized text for one fixture, chunk and embedding
still miss. This is fewer hits than an output-only policy, but it matches the
approved auditable invalidation contract. Any future relaxation needs an ADR
and paired correctness/performance evidence.

### Why exact canonical bytes matter

Python value equality is not serialized identity. For example, `-0.0 == 0.0`
is true, but their canonical JSON bytes and hashes differ.

For an existing key, G6 first validates the stored envelope and then requires
the stored canonical bytes to equal the new canonical bytes before returning
`REUSED`. Otherwise it raises `cache_key_collision`. This ensures the returned
payload hash always names the bytes actually stored.

The SHA-256 envelope detects accidental corruption, non-canonical content, and
a file copied to the wrong key path. It is not a MAC. A same-user attacker who
can rewrite payload and checksum remains outside this local prototype's threat
boundary.

### Why non-empty plans need the base catalog

A plan hash proves that one plan object is internally self-consistent; it does
not prove the classifications came from the real base.

For a non-empty plan, G6 receives the exact base catalog, validates its hash
and event count, and calls the G5 planner again with:

- base catalog;
- target catalog;
- base and target run IDs;
- conflict exclusions;
- quarantine exclusions.

The rebuilt plan must equal the supplied plan. This prevents a caller from
changing `content_changed` into `unchanged` and recomputing only the plan hash.

G6 does not need the base index to compute a complete target corpus. It never
copies FAISS/BM25 artifacts from that base. G7 does need the actual immutable
base `IndexManifest` before assembling or activating a new index. Catalog
lineage and index publication authority are intentionally separate checks.

### Whole-corpus governance is still rerun

Even an unchanged source can change its canonical disposition when another
source arrives. Examples include a duplicate becoming non-canonical or a
new authoritative version retiring an old head.

Therefore G6:

1. parses/normalizes every live source through cache or callback;
2. materializes every current document;
3. runs `govern_documents()` over the complete target;
4. chunks/embeds only the canonical governed documents.

This costs more than blindly processing only the `upserts` list, but preserves
the existing global version and duplicate rules.

### Result and measurement boundaries

`ComputationArtifactManifest.artifact_set_id` binds:

- plan and base/target catalog hashes;
- target run and pipeline;
- every source/revision/cache artifact binding;
- tombstones;
- governance output hash;
- final documents, chunks, and embeddings hashes;
- document/chunk/indexed counts.

`IncrementalComputationResult` recomputes the final artifact hashes during
strict validation and checks document/chunk/embedding relationships. A
self-consistent manifest paired with different artifact tuples is rejected.

The separate measurement object reports:

- parse/normalize/chunk/embedding callback counts;
- cache hits and misses;
- canonical serialization time for newly written cache envelopes and the
  computation manifest;
- successful function wall time through final result validation.

The 100-source test proves that 0%, 1%, 5%, and 20% changes cause exactly 0, 1,
5, and 20 calls respectively at each stage. It does not prove latency
improvement. The test uses deterministic embeddings and an in-memory cache for
call-count isolation; persistent cache behavior has separate filesystem and
concurrency tests. G10 must run the pre-registered paired wall-time experiment
before a resume can claim build acceleration.

### Failure and retry behavior

- Corrupt/non-canonical/linked/redirected/oversized cache state fails closed.
- A callback failure returns no successful computation manifest.
- Successfully published upstream cache entries remain reusable.
- Failure before atomic cache replace is definitely uncommitted.
- Failure after replace is `cache_commit_outcome_unknown`; retry the exact key.
- Tombstones produce explicit tombstone bindings and zero live artifacts.
- G6 does not write index versions, so it cannot mutate `active.json`.

### Interview questions

**Why not key embeddings only by chunk text?** Text does not identify tenant,
parser/normalizer/chunker behavior, model weights, dimension, backend, or
normalization. A text-only hit can cross an isolation boundary or reuse a
vector produced under a different contract.

**Why cache chunk layout instead of ChunkRecord?** Layout contains content and
locator structure. `ChunkRecord` also contains ACL, region, version, authority,
source, and governance fields that must come from the current target.

**Why rerun governance if all documents hit cache?** Governance is a corpus
function. A new source can change duplicate or version selection for another
source whose text did not change.

**How do you prove an incremental plan is not forged?** Strict schema and
`plan_id` are insufficient. G6 validates exact base/target catalogs and
rebuilds the deterministic G5 plan, then requires full equality.

**Why is a checksum not authentication?** A checksum detects unintentional
change when the expected checksum is trusted. If an attacker can replace both
content and checksum, both remain self-consistent. Authentication needs a key
or external trusted ledger.

**What does 20% change mean in the test?** In a fixed 100-source corpus, 20
source contents change. Exactly 20 parse, normalize, chunk, and embedding
callbacks occur; 80 sources hit every stage.

**Can the resume say the build is 30% faster?** No. G6 proves selective call
reduction and correctness. Wall-time benefit, variance, serialization/I/O
bottlenecks, and real-model behavior are G10 paired experiments.

**What remains before activation?** G7 must consume the computation result,
strictly revalidate it, bind the actual base index manifest and catalog, write
a complete independent target snapshot, validate every artifact, and only
then atomically replace the active pointer.

### Exercise

Take one source with unchanged text but a new ACL, then apply these changes one
at a time: parser semantic version, normalizer implementation digest, chunker
size, embedding model digest, dimension, and tenant. For each change, write
the expected parsed/normalized/chunk/embedding hit or miss, identify which
fresh governance fields are rebuilt, and name the test that proves it.

## G7 Beginner Guide: From Computation to a Safe Active Index

### The core distinction

G6 answers, "Which expensive results may be reused?" G7 answers, "Can the
entire next index become active without corrupting what users currently
query?" A list of changed chunks is not an index. The runtime needs one
self-consistent set of documents, chunks, parent relationships, BM25 state,
FAISS vectors, manifest, and provenance.

### Code path, in order

1. `execute_incremental_publication` receives a canonical event and file.
2. G3 validates and stages the file; G6 computes or reuses parse, normalize,
   chunk, and embedding artifacts.
3. `_strict_inputs` revalidates the complete result and reconstructs the G5
   plan. This prevents a caller from pairing valid objects from different runs.
4. `_base_binding` loads the real immutable base run. A run ID alone is not
   proof; its manifest and lifecycle catalog hashes must match the plan.
5. The builder writes every target artifact into a fresh staging directory.
6. Validation reparses models, checks order and references, recomputes BM25
   tokens, reconstructs FAISS rows, and proves deleted IDs have no residual
   mapping.
7. The target directory is installed without overwrite.
8. Under the shared publication lock, the code checks that `active.json` still
   points to the expected base. Only then is the pointer atomically replaced.

Readers continue using the old immutable directory until step 8. A crash before
that point therefore cannot expose half of the new index.

### Why a lifecycle sidecar exists

The established runtime understands manifest v1. Replacing it would widen the
compatibility risk. G7 keeps that manifest and adds `lifecycle.json`, itself
bound into the manifest artifacts. The sidecar links publication identity,
base identity, target catalog, plan, computation evidence, and tombstones.
This adds provenance without teaching old retrieval code a second index
format.

### Delete and empty target

Deletion is not "filter the answer." The deleted document must disappear from
documents, chunks, parent mappings, BM25 rows, FAISS rows, and citation
metadata. When the last source is deleted, FAISS can represent zero rows but
`rank_bm25` cannot build a normal empty model. `_EmptyBM25` supplies the
runtime's empty-query behavior while the persisted target still records zero
rows and a real empty FAISS index.

### Rollback

Rollback means activating an older immutable version, not copying old files
over new files. Before pointer replacement, G7 loads and validates the
candidate and runs a fixed query. It compares ordered result and citation
fields with the fingerprint captured before activation. The audit event says
that older data became visible again, which matters for incident review.

### Why Windows retry is narrow

`WinError 5` can be transient when a scanner or ACL update briefly holds a
newly written directory. Retrying every `PermissionError` would hide real
security failures. `atomic_directory_move` retries only the observed state:
Windows, error 5, source directory still present, target still absent, bounded
attempts. This is availability hardening without weakening collision or
permission semantics.

### Interview questions

**Why not update FAISS in place?** Because documents, BM25, FAISS, parent
links, and citations would commit at different times. A failure would require
repairing an unknown mixed state. A complete immutable target reduces commit
to one pointer change.

**What does active-base CAS prevent?** Two writers may compute from base A.
After writer 1 activates B, writer 2 must not activate C as if A were still
current. Rechecking the pointer under the lock rejects writer 2's stale base.

**Why validate vectors after writing?** File checksums prove bytes did not
change; they do not prove row order matches chunk IDs or vectors are normalized
for inner-product search. G7 reconstructs rows and checks both semantics.

**Is rollback atomic with its audit event?** No. Pointer activation is local
and atomic; the following local hash-chain append is separately durable. A
production design needs a remote signed audit sink or transactional outbox.

**Does 140 injected failures prove crash safety?** It proves Python-visible
failure isolation at 14 named boundaries over repeated attempts. It does not
prove kill-at-instruction or power-loss behavior.

**Can the resume claim faster indexing?** No. G6 proves reduced callback
counts; G7 adds full serialization and validation. Only the G10 preregistered
paired benchmark can support a wall-time claim.

## G8 Beginner Guide: Turning Primitives into an Operable Lifecycle

### What changed conceptually

Before G8, the repository had strong parts but no single supported way to run
them together. G8 adds an application boundary, not another retrieval trick.
Both the CLI and API call `LifecycleOperatorService`, so identity order,
replay, build, activation, rollback, status, and errors cannot drift between
two implementations.

### Why authentication must happen before file access

An unauthorized request must not be able to learn whether a path exists, make
the server parse a large file, create a catalog lock, probe Ollama, or trigger
rollback recovery. The sequence is therefore:

```text
verify token -> require operator -> check tenant/region -> derive actor
             -> acquire operation capability -> touch lifecycle state
```

FastAPI identity middleware runs before body parsing. The CLI performs the same
check before resolving root overrides or opening JSONL. This is stronger than
"we check permissions somewhere in the function": the ordering itself is a
tested security property.

### Why preview has two result kinds

For an unseen UPSERT, preview knows the event intent but not the admitted asset
ID, verified media type outcome, parser identity, normalized hash, target
catalog hash, or final plan ID. Returning a normal ChangePlan would invent
facts. `PROPOSED` therefore reports counts and
`materialization_pending_count`.

For exact replay, the durable catalog already contains the receipt and
materialization. For DELETE, no source file needs parsing. Those cases may
produce an `EXACT` plan. The response model rejects mixed shapes so callers
cannot accidentally receive `plan_kind=EXACT` with only a proposal.

### How exact replay works

`SourceEventLedger` hashes canonical event bytes. The same event ID and same
payload returns the existing receipt; the same ID with different payload is a
conflict. G8 performs this check before source admission. That is why a
successful event can be retried after its input file disappears: the system is
replaying accepted history, not ingesting a new file.

The build response returns a bounded event result with payload hash and
resulting revision ID. An operator can store those values for the next
optimistic update without receiving file paths or document content.

### Why EML needs two parser entry points

First acceptance is not pure parsing. Attachments and nested messages must
become child assets with parent lineage, byte budgets, media validation, and
quarantine behavior. That is the job of `parse_staged_email`.

G6 may call a parser again after process restart or cache deletion. Reusing the
publishing entry point would create child assets again. The read-only entry
point validates the same root MIME structure and budgets, extracts the same
root body, but never publishes or quarantines. The test snapshots every asset
file and timestamp to prove the second call is observationally read-only.

### Why the model digest and dimension are data correctness

An embedding cache key is meaningful only if it names the weights and output
shape that produced the vector. A model name such as `bge-m3` is an alias, not
a weight identity. The pipeline reads the unique digest, probes dimension, and
rejects later dimension drift. It also rejects `NaN`, infinity, booleans, and
numeric strings, because they are not valid finite JSON-number vectors for the
index contract.

`localhost` is normalized to `127.0.0.1`, environment proxies are disabled,
and redirects are disabled. This both avoids the Windows IPv4/IPv6 ambiguity
seen earlier and prevents the local request from being redirected outside the
intended boundary.

### Why there are two locks

The lifecycle operation lock serializes catalog/build/activate/rollback
workflows. G7's publication lock protects immutable version installation and
`active.json`. They are different locks because build calls into G7; using the
same non-reentrant lock around the whole operation would deadlock when G7 tried
to acquire it again.

Lock acquisition errors are mapped only before the lock yields. An error from
Ollama, parsing, catalog, or publication after acquisition keeps its own
category. Correct error taxonomy matters because operators decide whether to
retry, inspect state, or stop based on it.

### Why rollback can return an unknown outcome

The pointer and local JSONL audit are two files. One atomic rename cannot commit
both. G8 writes an intent first. If the pointer changes and the audit write
fails, returning a normal failure would tempt a blind retry even though users
may already see the old index. `activation_outcome_unknown` tells the caller to
query status. Recovery compares the actual pointer with intent source/target,
then appends the audit exactly once or cancels an unapplied intent.

### Interview questions

**Why not expose a job ID?** There is no durable queue, worker lease, retry
owner, heartbeat, or restartable job state. A job ID would be a false contract.
G8 is honestly synchronous.

**What happens when catalog acceptance succeeds but index build fails?** The
accepted event remains durable. Status reports `INDEX_UPDATE_PENDING`. Replaying
the same event set and publishing a new run resumes without duplicate source
admission.

**How do API and CLI avoid security drift?** They contain transport concerns
only and delegate all business behavior to the same operator service. The API
uses exact route policy; the CLI uses the same identity verifier.

**Why is a read-only catalog loader separate from normal snapshot loading?**
Normal loading owns recovery and can create a lock or repair an anchor. Preview
promises zero durable mutation, so it needs a verifier that fails closed rather
than repairing.

**Did G8 prove industrial performance?** No. It proves an operable,
authenticated, restartable local workflow. G9 adds realistic fictional E2E
fixtures; G10 must preregister and run paired measurements before any speedup
claim.

### Exercise

Trace one UPSERT through the API from JWT middleware to `active.json`. For each
step, write: trusted input, untrusted input, durable write, idempotency key,
possible stable error, and the test that proves the failure cannot expose a
partial active index.

## G9 Beginner Guide: Proving the Whole Lifecycle

### Why G9 exists

Before G9, each layer had tests, but an interviewer could still ask: "Have you
actually run all of those layers as one business workflow?" G9 answers that
question without pretending synthetic data is a real customer deployment.

The distinction is:

```text
component test:
    can one module satisfy its contract?

end-to-end lifecycle test:
    do all accepted contracts compose without changing their security meaning?
```

G9 found defects that component tests had missed. That is the main engineering
value of an E2E fixture.

### Files to read in order

1. `data/enterprise_bundle/manifest.json`
   - declares the fictional assets, source events, expected revision links,
     ACL groups, and fixed query;
   - binds every source file by relative path, byte count, media type, and
     SHA-256.
2. `app/lifecycle/enterprise_bundle.py`
   - defines the strict manifest schema;
   - safely reads the manifest and assets;
   - cross-validates the graph before returning events.
3. `scripts/verify_enterprise_bundle.py`
   - offers a fast offline integrity check;
   - emits counts and hashes only, never source bodies.
4. `tests/lifecycle/test_enterprise_e2e.py`
   - executes the real operator service and production G3-G7 code;
   - proves initial build, restart replay, change, deletion, activation, and
     rollback.
5. `data/v2/public/lifecycle_g9/summary.json`
   - stores only stable public invariants.
6. `data/v2/public/lifecycle_g9/checksums.sha256`
   - proves which exact manifest, sources, and summary the evidence describes.

### How the manifest graph works

An asset describes immutable bytes:

```text
path + byte_count + media_type + sha256
```

An UPSERT event points at those bytes and adds source identity, tenant, region,
ACL, observation time, and the desired document projection. The manifest
validator checks that path, digest, and media type match an asset exactly.

A change event does not contain a guessed revision ID. Instead it stores
`expected_revision_from_event_id`, which points to an earlier initial event.
After the initial build succeeds, `resolve_batch` reads the actual accepted
revision receipt and constructs a concrete operator event. This demonstrates
optimistic concurrency without hard-coding a result that only one run could
produce.

The fixed query also binds an expected initial source key. The validator
requires that key to select exactly one initial UPSERT. The E2E test derives the
expected document ID from that manifest binding, so the manifest is executable
contract data rather than decoration.

### Why there are event template and concrete event types

A real operator DELETE must include `expected_revision_id`. Otherwise two
operators could delete different revisions while believing they deleted the
same state.

The public bundle cannot know the accepted revision until its initial batch has
run. `OperatorSourceEventTemplateInput` therefore permits only this unresolved
bundle representation. `OperatorSourceEventInput`, used by CLI/API requests,
requires the concrete revision and preflights the complete canonical
`SourceEvent` validation.

This split prevents two bad compromises:

- weakening the actual operator API so DELETE may omit concurrency control;
- embedding a run-specific fake revision in a supposedly reusable fixture.

### What safe bundle loading means

The loader does not call `read_text()` on arbitrary paths and trust the result.
For each file it:

1. checks each original path component with `lstat`;
2. rejects symlinks and non-directory parents before resolution;
3. proves the resolved target remains under the bundle root;
4. opens with no-follow where supported;
5. compares pre-open path, descriptor, and post-open path identity;
6. requires a one-link regular file;
7. enforces per-file and total byte limits;
8. detects size or modification-time change during the read;
9. compares bytes with the canonical manifest length and SHA-256.

Path containment answers "where did the target end up?" Link rejection answers
"what path object did the caller actually supply?" Both are needed.

### Why raw EML scanning was insufficient

Email transfer encoding changes how content appears on disk:

```text
real decoded text -> Base64 characters in the .eml file
```

A regular expression over raw EML sees only the Base64 alphabet. G9's first
identity policy could therefore miss a real address inside a decoded body or
attachment.

`inspect_email_decoded_surfaces` reuses the production G4 parser's bounded MIME
inspection. It validates structure and limits, then exposes parsed header
values and transfer-decoded leaf payloads as bytes. The bundle applies the
same private-marker and `example.invalid` policy to raw and decoded surfaces.
It does not publish child assets or mutate quarantine state.

### Initial build

The first batch contains four UPSERTs. For each source, the operator:

```text
validates identity and scope
-> admits source bytes
-> parses/materializes a document
-> appends event and revision state
-> computes the target ChangePlan
-> reuses or computes pipeline stages
-> assembles a complete immutable target
-> validates all target artifacts
-> installs and activates by compare-and-swap
```

The E2E test then loads the index through the normal retrieval snapshot and
records one fixed-query fingerprint.

### Restart replay

The test renames the copied source directory so the original input paths are
unavailable. It creates a new service instance and sends the same four events.
All four must return `REPLAYED`.

That alone is not enough. G9 also compares:

- target revision-catalog hash;
- documents hash;
- chunks hash;
- embeddings hash;
- ordered document, indexed-chunk, and parent-chunk ID hashes;
- computation order;
- fixed-query ordered result/citation fingerprint.

The admitted asset directory is compared by relative file name and exact bytes
before and after replay. This proves restart replay is both idempotent and
semantically equivalent.

### Pending build and CAS activation

The change batch updates the remote-access policy and deletes the vendor
source. Build runs with `activate=False`, so it installs a validated immutable
target but does not change `active.json`.

Status must report `INDEX_UPDATE_PENDING`. This is not an error. It means the
accepted catalog is ahead of the user-visible index by operator choice.

Activation includes `expected_current_run_id`. If another writer has activated
something else, the compare-and-swap fails. G9 activates the changed target
against the initial run, then proves a stale repeat is rejected.

### How deletion residue is calculated

The project intentionally preserves immutable history, tombstones, admitted
assets, and cache evidence. Therefore "zero deletion residue" must not mean
"the source bytes no longer exist anywhere."

G9's accepted claim is narrower:

> The changed active index contains no source-addressable live representation
> of the deleted document.

The test captures the deleted source's initial indexed and parent chunk IDs,
then computes a residual set from:

- active document map;
- indexed chunk map;
- parent chunk map;
- BM25 row mapping;
- FAISS row mapping;
- live source bindings;
- fixed-query retrieval hits.

The summary serializes the computed length as
`active_index_deleted_residual_count`. It must be zero. The tombstone must
still name prior document IDs, because audit history is a feature, not residue
in the active search view.

### Why fresh-run plan hashes are not public evidence

Secure admission assigns random asset IDs. Those IDs intentionally influence
revision, catalog, plan, and publication identity. As a result:

```text
same accepted durable state + exact retry
    -> same plan/publication identity

new isolated run + newly admitted assets
    -> internal identities may differ
```

The first public summary got this wrong. The corrected summary publishes
stable counts, Boolean invariants, run labels, manifest hash, and query
fingerprints. It tests exact retry identity within one state but does not
publish random-derived values as cross-run constants.

### What the Windows cache bug teaches

The complete suite found a race outside the new fixture. Four processes all
started with an empty computation-cache root. The old order was:

```text
create root -> harden ACL -> create/acquire lock
```

The lock protected entries but not its own security-sensitive bootstrap.
Processes could observe one another changing ACLs.

The corrected order creates and acquires the lock before ACL mutation, then
holds the directory identity and hardens through handles. Reads and writes
share this protocol. This is an industrial lesson: a lock protects only the
operations that occur after it is acquired. Naming a file "lock" does not
retroactively serialize initialization.

### Interview questions

**Why use fictional data instead of a real company document dump?**

Public evidence must be redistributable, reviewable, and safe to push. A
canonical synthetic bundle gives exact failure reproduction without claiming
customer acceptance. Real private data would require separate privacy,
retention, and legal controls and could not serve as open evidence.

**How is this more than technology stacking?**

The scenario represents an operator workflow with business consequences:
accepted source history, optimistic conflicts, delayed activation, deletion
visibility, and rollback. Each capability has an invariant, error state, and
machine-verifiable artifact. G9 also found and fixed cross-layer defects.

**Why not make secure asset IDs deterministic for prettier hashes?**

That would weaken the production security boundary to satisfy a demo. The
evidence was changed to describe stable invariants rather than changing the
system to manufacture stable random-derived IDs.

**Does active-index zero residue satisfy a legal erasure request?**

No. It proves the deleted source is not searchable in the changed active
snapshot. Legal erasure may require expiring immutable versions, catalog
history, assets, backups, and cache according to a governed retention policy.

**Why compare both artifact hashes and a query fingerprint on replay?**

Artifact hashes prove exact internal reconstruction. The query fingerprint
proves the externally relevant ordered retrieval/citation projection is also
unchanged. Either check alone leaves a different class of regression unseen.

**Why did full tests find a cache bug when focused G9 tests passed?**

Focused tests validate the feature's direct blast radius. The full suite adds
cross-module concurrency and platform behavior. Both layers are needed:
focused tests give fast diagnosis, while full tests reveal integration
assumptions.

**What can be claimed on a resume now?**

The defensible claim is implementation of a governed local knowledge lifecycle
with canonical source events, safe MIME/file admission, persistent revisions,
incremental computation reuse, immutable index publication, CAS activation,
active-index deletion verification, rollback, authenticated operation, and a
fictional exact-hash E2E evidence package. Do not attach unmeasured speedup,
real-customer, or production-scale numbers.

## G10 - How to Prove Incremental Lifecycle Value

### What was actually compared

The benchmark does not compare “rebuild the entire project from raw files”
with “update a few files.” That would be an unfair comparison because the two
arms would start at different business states.

Both arms start with the same accepted base snapshot:

```text
same base catalog
same base immutable index
same target ChangePlan
same target source bytes
same host and dependencies
```

The baseline has no target computation cache, so it recomputes every target
document's parse/normalize/chunk/embed stages. The intervention has the base
cache and can reuse stages whose complete correctness key is unchanged. Both
still build and validate a complete immutable target. This isolates the value
of computation reuse without weakening publication safety.

### Why a pair is rejected before timing matters

Faster wrong output has no engineering value. For each pair, the project first
requires:

- exact target catalog and artifact fingerprints;
- exact document/chunk/embedding order;
- authorized retrieval success;
- removed-group, wrong-tenant, and wrong-region retrieval denial;
- zero deleted-source representation in the active index.

Only a pair passing all correctness checks contributes to the performance
decision. This is called a correctness gate around a performance experiment.

### Why AB/BA order is alternated

The first process can pay cold-start costs, while the second can benefit from
operating-system file cache. If baseline always ran first, the experiment
could unfairly favor intervention.

```text
pair 1: baseline -> intervention
pair 2: intervention -> baseline
pair 3: baseline -> intervention
...
```

The result reports both order groups. Their median ratios, approximately 0.706
and 0.722, point in the same direction. This does not eliminate every host
effect, but it makes the major order bias visible.

### How to read the two main ratios

The median time ratio is:

```text
intervention wall time / baseline wall time = 0.7166
```

The intervention therefore used about 71.66 percent of baseline time. The
relative reduction is `1 - 0.7166 = 0.2834`, or about 28.34 percent.

The embedding-call ratio is:

```text
310 / 12170 = 0.02547
```

The intervention made about 2.55 percent as many embedding callbacks, a
reduction of about 97.45 percent. Wall time does not fall by the same amount
because complete validation, serialization, index assembly, publication, and
activation still run in both arms.

### Why commit binding matters

An experiment result applies to the code that produced it. If the runner or a
transitive measurement dependency changes afterward, the old number cannot be
silently claimed for the new code.

G10 registration hashes:

- the Git commit;
- every regular measurement source file;
- the source path list and count;
- `requirements.txt`;
- exact relevant installed dependency versions;
- pipeline, bundle, host, and model identities.

The run refuses a dirty measurement source. This is the same reason a database
migration, model evaluation, or security certification needs a versioned
artifact: reviewers must know exactly what was measured.

### Why the public package copies raw files

A checksum of an unavailable file proves nothing to an external reviewer.
The first public G10 summary referenced files under a Git-ignored run
directory. The v2 package copies all 45 bounded raw files and four dataset
descriptors, then binds them with a canonical manifest and checksum list.

The verifier does more than hash checking. It proves that aggregate rows equal
their child pair files, arm files belong to the expected pair, commands are
the frozen safe commands, timestamps and identities agree, thresholds are the
registered thresholds, and the recomputed decision is `SUPPORTED`.

### Interview questions

**Why did you keep failed or superseded experiments?**

Deleting them would hide the development history and make it impossible to
explain why the accepted protocol is stronger. `EXP-LC-001..006` remain
historical; only `EXP-LC-007..009` bind the accepted source and portable
evidence.

**Why not use average time?**

The primary statistic is the paired median ratio because it is less sensitive
to occasional host spikes. Mean, min, P95, faster-pair count, and AB/BA strata
remain visible as supporting diagnostics.

**Does 28.34 percent mean production requests are 28.34 percent faster?**

No. It means complete target builds from an accepted base were 28.34 percent
faster at the median in this deterministic local 1225-document workload. It
does not measure online answer latency, real embedding service latency, or
multi-user throughput.

**Why is only one local failure still open?**

An early test used the host default temporary directory and created a path
whose Windows ACL now prevents removal by the current token. It does not affect
runtime correctness or public evidence. The exact exception remains visible
as `FAIL-LC-076`, and all later Python/test temporary state is pinned to the
project D drive rather than pretending cleanup succeeded.
