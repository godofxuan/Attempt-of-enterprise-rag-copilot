# R2-S7 Accepted Results

## G0 Current Full-Rebuild Baseline

Status: Accepted on 2026-07-26

Baseline and current Git commit:
`d465eedb80cae4bc7b2e3be71b782ad565cc188e`

Branch: `codex/rag-eval-system`

The worktree is intentionally dirty because the G0 implementation and evidence
have not been committed. No optimization, incremental lifecycle path, or
production-readiness claim is accepted by this result.

### Correctness Baseline

- Initial focused baseline: 107 passed, 0 failed, 3 warnings.
- Corrected pre-change full baseline: 1941 passed, 23 skipped, 0 failed,
  3 warnings.
- Final focused regression: 124 passed, 0 failed, 3 warnings.
- Final full regression: 1953 passed, 23 skipped, 0 failed, 3 warnings.
- Final full pytest time: 126.66 seconds; command time: 128.706 seconds.
- Pre-close public audit: 543 candidates, 0 findings.
- First post-documentation public audit: 546 candidates, 0 findings.

The three warnings are unchanged SWIG `DeprecationWarning` records. The first
full-suite attempt with `.tmp/lifecycle` is retained as `FAIL-LC-002`; it had 6
failures because the command changed the trust class of security fixtures.

### Frozen Inputs

| Profile | Source documents | Canonical/indexed | Manifest SHA-256 |
| --- | ---: | ---: | --- |
| `expanded` | 240 | 216 | `5d96338e4d637c207c381323fc6919f575983992e553a06f548a7e7e0fc24e57` |
| `expanded_benchmark` | 2000 | 1225 | `833338d8472a1da652134d5b23c100a08cc5e76db785154e8609314b2be1f834` |

The configured local model resolved to `bge-m3:latest`, digest
`7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`,
F16, with 1024-dimensional embeddings.

### Repeated Full-Rebuild Measurements

P50/P95 use nearest rank. RSS values are process peak working set. Times are
milliseconds.

| Corpus/backend | Repetitions | Calls/run | Total P50/P95 | Prepare P50 | Embedding P50 | Serialization P50 | Peak RSS P50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 240 / deterministic-128 | 10 | 216 | 983.24 / 1134.97 | 498.87 | 1.66 | 21.13 | 148.64 MiB |
| 2000 / deterministic-128 | 10 | 1225 | 3681.09 / 3997.29 | 2729.19 | 9.95 | 134.73 | 192.26 MiB |
| 240 / local BGE-1024 | 5 | 216 | 39630.71 / 39951.19 | 532.95 | 38603.67 | 22.59 | 164.75 MiB |
| 2000 / local BGE-1024 | 5 | 1225 | 220025.26 / 222078.45 | 2630.06 | 216477.87 | 190.51 | 250.52 MiB |

Every run used a distinct worker process. Every repetition made exactly one
embedding call per indexed chunk. Each configuration produced exactly one
artifact-set hash across repetitions. All 80 entries in the four evidence
package checksum files recomputed exactly.

### Accepted Interpretation

1. With deterministic embeddings, 2000-document preparation is the largest
   measured phase at about 74% of total P50. This supports measuring selective
   parsing and chunking later; it does not prove that reuse is faster.
2. With the real local BGE model, embedding is about 98% of 2000-document total
   P50. This provides a concrete reason to test embedding reuse later.
3. Serialization is measurable but is not the leading G0 bottleneck in either
   2000-document configuration.
4. Deterministic and BGE measurements answer different questions and must not
   be averaged into one performance number.

### Evidence

| Evidence | Summary SHA-256 | Checksums SHA-256 |
| --- | --- | --- |
| `g0-expanded-deterministic-20260726-01` | `3d8db3c48c39de0add4c927a70eb8ea7b93671a4921893cecfddbfaeffce8f8e` | `e160e4c22baad61bbd5e4b8ea321a6664252bbffac060061bf88dc02d39d8772` |
| `g0-expanded-benchmark-deterministic-20260726-01` | `dc3ef26f27657967d54254ef537f65a5ed4dff0fc0ccad3d81e8f5f00880da26` | `d5d02c7e6b32c77de73b2877ad022ab013c0bd89f8e6af1155f08052e8d0a18d` |
| `g0-expanded-bge-m3-20260726-01` | `a06904a707e39e703b0330487b663889ae1e3b4e34cda40e4d71faed16fdd9a1` | `5bd5f6d27884fcde1da673823f74aa26d66a3e1f89e22fb84e10f48794a2b80b` |
| `g0-expanded-benchmark-bge-m3-20260726-01` | `5cedae0242b6be0323352072103f7815fe4f3d631acb86a8a0b4fb0f7b2580de` | `e8845216ebeffb18c27bf50bd1184f2b3be0cfe087fbe1c94d8d0b04e6e5caaf` |

Final focused log SHA-256:
`abc3e4559761d70871ddeca4313ff8a43dd5c6e70a58fdf01048481e39712e2e`.

Final full log SHA-256:
`bd03b69a5df1eb3f60a212c29033b642c9a7c518338c48aee435fd10a1a614a4`.

### Limitations

- Corpora are generated fictional fixtures, not private enterprise data.
- Performance runs were executed on one Windows 11 machine with an AMD Ryzen 5
  7500F and local Ollama.
- Ubuntu CI performance was not measured in G0.
- Process peak RSS includes Python imports and measurement infrastructure.
- The BGE path uses the current serial one-request-per-chunk implementation.
- No A/B incremental implementation exists yet, so no speedup, cache-hit, or
  reduced-call claim is permitted.
- Owner-only private pilot and human review remain not run.

## G1 Evidence Infrastructure

### Implemented Boundary

G1 adds deterministic evidence governance only. It does not ingest enterprise
documents or modify an index:

```text
typed record
  -> strict schema and state validation
  -> duplicate-ID and revision-history validation
  -> exclusive append lock
  -> canonical one-line JSON
  -> O_APPEND write and fsync

accepted evidence file
  -> repository-relative bounded path
  -> accepted byte prefix + logical record count
  -> SHA-256 anchor
  -> future prefix equality check
  -> optional suffix append

repository evidence
  -> required-file check
  -> JSONL + CSV + handoff validation
  -> cross-file reference consistency
  -> anchor and artifact-hash verification
  -> public candidate audit
  -> bounded count-only result
```

### G1 Test Results

| Scope | Result | Evidence SHA-256 |
| --- | --- | --- |
| Schema GREEN | 4 passed | `6fc2c202b3e40698553304bf488dcfade7c5691ba3f2183b50e220db3a2b0e83` |
| Prefix/hash GREEN | 3 passed, 1 skipped | `3f2fc78745c2c47ec6187e6b5ee0f53036f4ef4fd921431550fb5353ddea0ca5` |
| Consistency GREEN | 5 passed | `deede7747c11a913426a83a3916596ed17ddd348d57ff3ff0eececb9d7beba02` |
| Related regression | 114 passed, 1 skipped | `624c04e0f4817bc6845fbcdbca1a1392d2a63fd474b1aef2a2a2ad93548666be` |
| Hardened G1 | 12 passed, 2 skipped | `120a984570349ce6b3b7bf96a100d1c6f1369b0dc4acd375b8b4535e50bbe605` |
| Final full regression | 1965 passed, 25 skipped | `3bb404182d90e8fa1a23ae5c6860a8ebbe8349286ba61b8ace1ec6116e564daa` |

The RED JUnit artifacts are retained for all three vertical slices. Their
failures were the expected missing package/symbol/module failures before each
implementation, not post-implementation regressions.

### Accepted Interpretation

G1 proves that malformed evidence states, duplicate IDs, changed
preregistration fields, accepted-prefix mutation, truncation, unsafe paths,
inconsistent handoff projections, unknown traceability references, and a
synthetic credential fixture are detected by deterministic tests. It does not
prove business lifecycle correctness, production durability, multi-process
transactional storage, or private-enterprise performance.

### G1 Closeout

- Required lifecycle files: 10.
- Accepted append-only prefixes: 6.
- Current evidence artifact hashes: 9.
- Traceability rows: 6.
- Failure records: 4 resolved, 0 open.
- Experiment records: 0.
- Research requests: 0.
- Final public audit: 557 candidates, 0 findings.
- Final full regression: 1965 passed, 25 skipped, 3 warnings.

G1 is accepted. G2 lifecycle business behavior has not started.

## G2 Canonical SourceEvent and Idempotency Ledger

### Implemented Boundary

G2 introduces one deterministic domain boundary:

```text
untrusted lifecycle fields
  -> strict SourceEvent schema
  -> UTC / ACL / media / metadata normalization
  -> canonical JSON bytes
  -> payload SHA-256
  -> replay and conflict checks
  -> immutable revision receipt
  -> deterministic process-local snapshot
```

It deliberately performs no source-byte read, parser call, durable write,
authorization change, index build, active-pointer mutation, or rollback.

### Canonical Contract

- UPSERT requires a relative content path, media type, lowercase content hash,
  and non-empty ACL.
- DELETE requires an expected revision and has no content or ACL fields.
- Unknown fields, naive timestamps, unsafe paths, malformed hashes, non-finite
  metadata values, protected metadata aliases, and overlong values fail
  validation.
- UTC timestamps, sorted unique ACL values, sorted JSON keys, compact
  separators, ASCII escaping, and explicit nulls make canonical bytes stable.
- The fixed UPSERT test witness hashes to
  `42121ffe7e15d087618afa55991b82ebc33f0bd4c105369279b13e013a9fed8e`.

### Ledger Outcomes

| Input state | Outcome | State mutation |
| --- | --- | --- |
| New valid UPSERT, no expected revision | `APPLIED` receipt | Yes |
| Accepted event ID, same canonical payload | `REPLAYED` original receipt | No |
| Accepted event ID, another payload | `event_payload_conflict` | No |
| Existing source, stale/missing expected revision | `expected_revision_conflict` | No |
| Same source identity, another tenant | `source_tenant_conflict` | No |
| Same lineage, another region | `source_region_conflict` | No |
| Valid DELETE of live source | tombstone `APPLIED` | Yes |
| DELETE of missing/already deleted source | explicit state conflict | No |

### G2 Test Results

| Scope | Result | JUnit SHA-256 |
| --- | --- | --- |
| Focused SourceEvent | 51 passed | `af8f49608b84658f57f2a5c40816cc7ebc714bb6b0609694fc11905506cd1310` |
| Ingestion regression | 96 passed | `c4f25449f0bfdb3a9b687c359ba6528933e95689af2547ba6e6b27ae89a29430` |
| Related lifecycle/index/security regression | 223 passed, 2 skipped | `30da7ad2f54d086d07ea0b13b90dd1af4d83c20edb7328c901178d88047f7592` |
| Final full regression | 2016 passed, 25 skipped | `eb85c4a6671f8da6507cc18b1d84b157eff4546e851fd3273fb8fa13bad07464` |

The three warnings are the unchanged SWIG deprecation warnings. All selected
RED artifacts and every GREEN JUnit file remain under
`artifacts/lifecycle/g2-*-20260726-01/`.

### Accepted Interpretation

G2 proves deterministic canonicalization, idempotent replay, explicit
same-ID/different-payload conflict, expected-revision conflict, tenant and
region ownership, content-free deletes, immutable accepted facts, and
tamper-rejecting snapshot import for the process-local domain object.

G2 does not prove crash recovery, database transactions, multi-process
serialization, source-file safety, parser safety, persisted revision lineage,
incremental index correctness, activation, or rollback. Those remain explicit
later-Gate work and cannot be used as current resume claims.

### Closeout State

G2 is accepted:

- Focused SourceEvent tests: 51 passed.
- Related lifecycle/index/security regression: 223 passed, 2 skipped.
- Final full regression: 2016 passed, 25 skipped.
- Required lifecycle files: 10.
- Accepted append-only prefixes: 6.
- Current evidence artifact hashes: 9.
- Traceability rows: 7.
- Failure records: 3 resolved, 0 open.
- Experiment records: 0.
- Research requests: 0.
- Final public audit: 559 candidates, 0 findings.

G3 file validation, staging, quarantine, and parser boundaries have not started.

## G3 Bounded Asset Admission, Staging, and Quarantine

### Implemented Boundary

```text
strict SourceEvent + trusted Principal
  -> object revalidation
  -> operator / tenant / region check
  -> physical path-component and root-separation checks
  -> no-follow open + fstat identity
  -> bounded one-pass application copy
  -> SHA-256 and type decision
  -> STAGED or QUARANTINED redacted receipt
  -> atomic complete-directory publication
```

No parser, revision catalog, ChangePlan, index builder, active pointer, or
ingestion API is called by this flow.

### Accepted Type Matrix

| Family | Staged suffix | Admission witness |
| --- | --- | --- |
| Plain text | `.txt` | bounded UTF-8, no NUL |
| Markdown | `.md`, `.markdown` | bounded UTF-8 text compatibility |
| HTML | `.html`, `.htm` | HTML doctype or root element |
| CSV | `.csv` | consistent multi-column sample |
| JSONL | `.jsonl` | non-empty JSON-object lines |
| PDF | `.pdf` | `%PDF-` |
| DOCX | `.docx` | ZIP plus bounded OOXML directory witnesses |
| EML | `.eml` | bounded RFC-style header block witnesses |

ZIP, RAR, and 7z are quarantined without extraction. Quarantine payloads always
use `.blob`.

### Failure and Quarantine Outcomes

| Condition | Outcome |
| --- | --- |
| No operator role, tenant/region mismatch | safe admission error before path access |
| Invalid/redirected/linked path or root overlap | safe admission error, no copy |
| Empty or oversized input | rejected, no persisted payload |
| Event hash mismatch | quarantined |
| Archive or unknown binary | quarantined |
| Extension/MIME/signature disagreement | quarantined |
| Invalid bounded DOCX structure | quarantined |
| Copy, receipt, or final publication failure | no incoming or final partial asset |

### G3 Test Results

| Scope | Result | JUnit SHA-256 |
| --- | --- | --- |
| Final focused G3 | 34 passed, 1 skipped | `79cef997df411691181c1d2848e33383a965089a544eb500f2cb90242fb7f2a0` |
| Complete ingestion | 130 passed, 1 skipped | `cd2213978a115a20b02f9f7f48dd2824b1caceaa67dba0ef3656a28a9d957282` |
| Related security/index/API | 334 passed, 5 skipped | `ac649d0a4de35947f128a838a293a68abf34b8f6a4ec0fec62e494857eb9b8e3` |
| Final full regression | 2050 passed, 26 skipped | `4925a6d385658690255480e107187d249faf41be17d1bcf367c935d6f4bce348` |

The focused skip is symbolic-link creation when local Windows privileges do
not permit it. A real Windows junction fixture and a hardlink fixture both
executed and passed. Linux/CI runs the symbolic-link behavior where supported.
The three warnings remain the existing SWIG deprecation warnings.

### Accepted Interpretation

G3 proves that the local public operation cannot reach a parser before trusted
identity checks, canonical event revalidation, bounded path/file identity
checks, one bounded application copy, and an explicit disposition. It also
proves that quarantine cannot be selected by the existing suffix registry and
that failure does not mutate the tested index state.

It does not prove attachment limits, MIME recursion, parser safety, malware
scanning, production filesystem ACLs, a kernel sandbox, distributed
transactions, or end-to-end enterprise ingestion. `max_event_files` is a
frozen policy input; G4 must consume it when child MIME assets exist.

### Closeout State

G3 is accepted:

- Final focused G3: 34 passed, 1 skipped.
- Complete ingestion: 130 passed, 1 skipped.
- Related security/index/API: 334 passed, 5 skipped.
- Final full regression: 2050 passed, 26 skipped.
- Required lifecycle files: 10.
- Accepted append-only prefixes: 6.
- Current evidence artifact hashes: 9.
- Traceability rows: 9.
- Failure records: 4 resolved, 0 open.
- Experiment records: 0.
- Research requests: 0.
- Final public audit: 563 candidates, 0 findings.

At the G3 closeout point, G4 EML body parsing, attachment decoding,
child-asset budgets, and nested-message handling had not started.

## G4 Safe EML Parsing Final Results

G4 implements the `REQ-LC-004` code and test contract. Functional acceptance
is complete; repository evidence validation and handoff hashes are regenerated
after this result record.

### Implemented behavior

| Capability | Result |
| --- | --- |
| Root input | Authorized UPSERT plus matching, untampered STAGED EML receipt |
| MIME engine | Python stdlib `BytesParser` and `EmailMessage` |
| Body | Plain preferred; bounded non-executing HTML fallback |
| Headers | Internal bounded subject/date; redacted From/To/Cc |
| Attachments | Strict decode, shared budget, G3 child admission, immutable-byte parser dispatch |
| Nested email | New child asset plus shared-session recursive G4 parse |
| `.msg` | Explicit `msg_not_supported` quarantine |
| Archive/encrypted | No extraction or decryption; quarantine |
| Defects | Unknown/structural fail closed; allowlisted recoverable become codes |
| Failure cleanup | Root and every published staged child become non-parseable |
| Public trace | Pseudonymous ID, counts, versions, status, and codes; no content hash |

### Final verification

- G4/child/parser focused: 70 passed.
- Complete ingestion: 185 passed, 1 skipped.
- Related lifecycle/identity/API/index/public: 474 passed, 8 skipped.
- Full deterministic repository suite: 2105 passed, 26 skipped in 140.98
  seconds.
- Static EML fixtures: 6, all fictional and SHA-256 bound.
- LLM calls in parser, validator, budget, and disposition decisions: 0.
- Network calls in HTML extraction: 0.
- Automatic archive extraction or decryption: 0.
- Fault injection covers failure before quarantine publication and cleanup
  failure after publication.
- A known-over-limit root is quarantined through a streaming 1 MiB copy with
  byte-count and SHA-256 verification; it is not read into MIME parser memory.

### Security interpretation

The result does not mean "the email is trusted." It means:

1. root bytes still match an authorized admitted event;
2. MIME structure remained within deterministic limits;
3. every decoded child obtained an independent G3 disposition;
4. only staged children reached a parser;
5. document instructions never entered the control plane;
6. public trace contains no raw mail or attachment content.
7. public trace contains no stable content hash that correlates equal mail
   across tenants.

### Current limitations

- MIME bytes remain inside a bounded-memory root envelope; this is not an
  arbitrary-size streaming mail parser.
- Local filesystem publication is not a distributed transaction.
- Malware scanning, sandboxed rendering, archive extraction, passwords,
  S/MIME/PGP decryption, `.msg`, and OCR remain unsupported.
- Internal result models contain subject/body data by design. Only the
  dedicated public trace is safe for public evidence.
- Successful G4 output is not yet a governed revision or index change.

## G5 Durable Revision Catalog and ChangePlan Final Results

G5 closes `REQ-LC-005` for the local prototype and prepares, but does not
implement, `REQ-LC-006` and `REQ-LC-007`.

### Implemented behavior

| Capability | Result |
| --- | --- |
| Durable event state | G2 ledger, receipts, heads, and revisions in one canonical snapshot |
| UPSERT provenance | Event-bound asset/document, parser, normalizer, content, and normalized hashes |
| DELETE | Content-free inherited-governance tombstone; history retained |
| Replay | Same event/payload returns the original revision without a write |
| Concurrency | Native cross-process lock; stale competing writer conflicts |
| Publication | Private temporary file, `fsync`, atomic replace, platform directory durability |
| Recovery | Owned orphan cleanup and one-generation anchor reconciliation |
| Rollback detection | Missing initialized catalog, older generation, and same-generation divergence rejected |
| ChangePlan | Canonical forward diff with event-level exclusions and deterministic `plan_id` |
| Index isolation | No chunk, embedding, FAISS, BM25, version, or `active.json` mutation |

### Final verification

| Scope | Result | JUnit SHA-256 |
| --- | --- | --- |
| G5 focused | 35 passed, 1 skipped | `95e7cd34c8c770ef50f83c6db3d2fb192ee076136bc61481cd1f0fd779292a30` |
| G5 related | 324 passed, 9 skipped | `b0f0205de25ffd00925e59afe7127e58728a482dcac22dad7ad034d0c5cf461a` |
| Full repository | 2140 passed, 27 skipped | `1b7aba881b566ba27c36e19a813b02d6756ef9f39efc7c081c013ab4e98a9626` |

The final public audit inspected 576 candidates and found 0 findings. The three
warnings in every pytest run are the unchanged SWIG deprecation warnings.

### Failure semantics

Before-replace failures preserve the previous catalog byte-for-byte.
After-replace confirmation failure is not reported as an ordinary failure; it
is `catalog_commit_outcome_unknown`. Replaying the exact event resolves the
outcome without duplicate history.

ChangePlan refuses a removed or rewritten history, a missing base run for a
non-empty catalog, and a target run equal to its base. Conflict or quarantine
attempts make the plan non-executable and remain event-level evidence.

### Limitations

- The complete catalog snapshot is rewritten per accepted event. This is a
  bounded single-node design, not an unbounded event database.
- The local anchor cannot detect a same-user attacker replacing both anchor and
  catalog. An external append-only audit sink remains production work.
- Fault injection covers Python-visible failures. No destructive power-loss
  or kill-at-instruction campaign was performed.
- G5 classifies invalidation but does not yet reuse parse, chunk, or embedding
  computation.
- G5 does not bind a base index manifest to a catalog hash; G6/G7 must add and
  revalidate that contract.

## G6 Exact Computation Reuse Final Results

G6 closes `REQ-LC-006` for the local prototype and produces validated
computation evidence for, but does not complete, `REQ-LC-007`.

### Implemented behavior

| Capability | Result |
| --- | --- |
| Parsed cache | Tenant/source/document/content/media/parser-bound canonical artifact |
| Normalized cache | Parsed-output, expected-hash, parser, and normalizer-bound artifact |
| Chunk cache | Content-only layout bound to normalized output and full upstream chunk pipeline |
| Embedding cache | Tenant-scoped text/pipeline/model/digest/dimension/normalization key |
| Persistent boundary | Private flat root, held identity, bounded no-follow reads, native process lock, atomic immutable writes |
| Governance | Fresh target documents, complete-corpus governance, current ACL/version chunk projection |
| Non-empty plan | Exact base catalog plus deterministic G5 plan reconstruction |
| Deletion | Explicit tombstone binding with zero live document/chunk/vector artifacts |
| Manifest | Canonical hashes for governance, final documents, chunks, embeddings, source bindings, and tombstones |
| Measurements | Stage hits/misses, real callback counts, canonical serialization time, successful-call wall time |
| Index isolation | No FAISS, BM25, version directory, manifest v1, or `active.json` write |

### Final verification

| Scope | Result | JUnit SHA-256 |
| --- | --- | --- |
| G5+G6 focused | 59 passed, 1 skipped | `764ba7ba78486bf76c6953fb4fba3ee6f438f144ec31877ffba7245800ba3421` |
| Related ingestion/indexing/identity code | 336 passed, 7 skipped | `015a672a4385eac250a63bd55b05e3bdc47a96ebb917f76c464a2bd8a582756d` |
| Lifecycle pre-close | 12 passed, 2 skipped | `08a486e65e83421213dda3ae8a788a5ad4aee48b7b626f870b6e22357900cf9f` |
| Full repository | 2164 passed, 27 skipped | `90eb21005f53fa6881a9805d884c4c913086f97a93b878c2f2330ca08f05b249` |

The full suite completed in 184.28 seconds. The three warnings are unchanged
SWIG deprecation warnings. The final public audit inspected 580 candidate
files and found zero findings.

Two read-only review rounds were performed. The final round reported zero P0
and four P1 findings. All four P1 findings have direct GREEN regressions:
canonical-byte replay, result/manifest cross-validation, successful-call timer
boundary, and the complete frozen invalidation matrix. G6 contains 17 resolved
failure records (`FAIL-LC-023` through `FAIL-LC-039`) and zero open failures.

### Selective computation evidence

The deterministic 100-source matrix ran isolated 0%, 1%, 5%, and 20% content
change conditions. For N changed sources:

- parse callbacks: N;
- normalize callbacks: N;
- chunk computations: N;
- embedding callbacks: N;
- every unchanged source: a hit at all four stages.

This supports exact callback-count reuse. It is not a paired performance
experiment. `EXPERIMENTS.jsonl` remains empty, so no wall-time improvement,
cache-speedup percentage, P50/P95 benefit, or real-model acceleration claim is
accepted.

### Correctness and security interpretation

Cached payloads never carry ACL, region, revision, authority, or observation
time. The tenant/source/document namespace prevents cross-tenant or
cross-source hits, while fresh target materialization and whole-corpus
governance determine current visibility.

An existing key is reusable only when its stored canonical envelope bytes
equal the requested bytes. Checksums detect accidental corruption,
non-canonical content, and path/key mismatch; they are not authentication
against a same-user attacker who can rewrite both payload and checksum.

`IncrementalComputationResult` rejects final artifacts that do not match its
manifest hashes, counts, document/chunk relationships, indexable
chunk/embedding order, or vector dimensions. G7 must still strict-revalidate
persisted results and bind the actual immutable base `IndexManifest`.

### Limitations

- G6 does not assemble, validate, install, activate, delete from, or roll back
  an index snapshot.
- `base_index_run_id` is plan provenance only in G6. G7 must load the actual
  immutable base manifest and prove its catalog binding.
- The local cache has no sharding, eviction, retention, backup, remote
  coherence, or multi-host writer protocol.
- Private-directory hardening scans the flat cache; its scaling cost is not
  yet measured.
- Whole-corpus document materialization and governance still run on every
  computation.
- No destructive power-loss campaign, Linux local run, distributed storage,
  real enterprise corpus, or owner-only human review was performed.
- No performance or resume speedup claim is permitted before the
  pre-registered G10 paired experiments.

## G7 Immutable Publication, Delete, and Rollback Results

G7 closes `REQ-LC-007` and `REQ-LC-008` for the local single-host prototype.

| Scope | Result | JUnit SHA-256 |
| --- | --- | --- |
| G7 focused snapshot/store/retrieval | 57 passed | `31dcaaacb9dbaae08c193ba9974a90ead5754a763fa1f8123b9ed443893ca28e` |
| Related indexing/retrieval/ingestion/lifecycle/security | 589 passed, 11 skipped | `626d2200081dcaaff1276c2574d0905750deb5c82c4879a8886bc8a1277513a7` |
| Complete repository | 2194 passed, 27 skipped | `055fdea5b76b1532fad6ffc07696d0fea3a817238008242817602d69e244270d` |

The complete suite finished in 163.81 seconds. Three unchanged SWIG
deprecation warnings remain.

### Accepted correctness claims

- The target is a complete independent snapshot, not an in-place patch.
- The actual base run, manifest hash, lifecycle sidecar, and revision catalog
  are loaded and cross-bound before a non-empty incremental publication.
- Target manifest artifacts include canonical revision catalog, ChangePlan,
  computation manifest, and ordered embedding-row evidence.
- Documents, chunks, parent links, BM25 tokens, and reconstructed normalized
  FAISS vectors are validated before installation.
- A single publication lock plus expected-active-base CAS permits one
  concurrent winner; an existing run is replay only for identical identity.
- Deleting the last source creates a loadable zero-row snapshot with no live
  document, chunk, vector, parent, or search mapping.
- Rollback validates the candidate and fixed-query result/citation fingerprint
  before activation and records a hash-chained local audit event.
- Fourteen failure points across ten attempts each produced 140 isolated
  failures with unchanged old pointer, loadable old snapshot, no failed target,
  cleaned staging, and successful retry.

### Engineering hardening discovered by broad validation

Windows intermittently denied directory rename immediately after staging
writes. A shared bounded publication primitive now covers ingestion, index,
evaluation, and load-profile directory publishers. It does not retry target
collision, non-Windows errors, `winerror=32`, missing source, or an existing
target. `FAIL-LC-045` records the failed runs and correction.

### Claims not accepted

G7 does not prove distributed activation, object-store transactionality,
power-loss atomicity, remote signed audit, multi-host locking, production
throughput, or incremental wall-time speedup. `EXPERIMENTS.jsonl` remains
empty.

Current-model closeout recheck: the exact EML/file-admission reproduction
suite passed 81 tests with 1 platform skip. Integrated evidence validation
covered 584 public candidates with zero findings. The independent review's
only P1 described the already superseded raw-rename implementation; current
business paths and full-suite evidence use the shared bounded primitive.

## G8 Authenticated Operator Surface Results

G8 closes `REQ-LC-009` for the local single-host prototype and exposes the
accepted G2-G7 workflow through one synchronous service, CLI, and HTTP API.

| Capability | Accepted result |
| --- | --- |
| Identity order | Operator role, tenant, and region are checked before event-file, source, catalog, cache, index, pointer, or audit access |
| Transport | Strict event input excludes actor identity and private roots; actor is derived from the verified principal |
| Preview | New UPSERT is `PROPOSED/materialization_pending`; replay and DELETE may return exact deterministic plans |
| Replay | Durable payload/revision receipt returned without reopening source or creating another asset |
| Build | Real G3 admission, G4 parser, G5 catalog/plan, G6 computation, and G7 immutable target publication |
| EML restart | First parse publishes child assets once; later cache misses parse the root read-only |
| Activation | Installed targets are validated, catalog-current, and activated under expected-current CAS |
| Rollback | Canonical pre-pointer intent plus deterministic recovery for post-pointer audit uncertainty |
| Status | Restart-derived EMPTY, INDEX_UPDATE_PENDING, or SYNCHRONIZED with hashes/counts only |
| CLI | One JSON object and stable exit codes 2-10; bounded no-follow JSONL read after authentication |
| API | Five exact operator-only synchronous routes; no fake job or caller-selected filesystem root |
| Model identity | Local literal loopback, no proxy/redirect, exact digest, finite values, and fixed dimension |

### Final verification

| Scope | Result | Artifact |
| --- | --- | --- |
| G8 lifecycle/API/CLI/runtime/G7 focused | 217 passed, 2 skipped | `artifacts/lifecycle/g8-focused-final-20260727-01.xml` |
| Trusted identity correction | 41 passed | D-drive local verification; public derived result updated |
| Complete repository | 2261 passed, 27 skipped | `artifacts/lifecycle/g8-full-final-20260727-02.xml` |

The first complete run had one failure after 2260 passes because the public
trusted-identity result still bound pre-G8 route-policy source hashes. The
frozen 20-case matrix remained 20/20 passing. Regenerating only through the
existing evaluator and rerunning the complete repository resolved the mismatch;
`FAIL-LC-053` preserves the diagnosis.

### Failure evidence

G8 added eight resolved records, `FAIL-LC-046` through `FAIL-LC-053`. They cover
an unmaterialized preview claim, validation after storage mutation, missing
observability allowlists, rollback pointer/audit split outcome, EML
republication risk, incomplete embedding identity pinning, over-broad lock
error mapping, and stale derived identity evidence. No G8 failure remains open.

### Limits

- Operations are synchronous and serialized on one host.
- Catalog acceptance and index publication are intentionally not one atomic
  cross-store transaction; status exposes catalog-ahead-of-index for retry.
- Local hashes and locks do not defend against a same-user host compromise or
  provide distributed consensus.
- No real enterprise data, human relevance labels, Linux local run, live-model
  performance comparison, or production traffic is claimed.
- `EXPERIMENTS.jsonl` is still empty; G8 makes no latency or speedup claim.

## G9 Fictional Enterprise End-to-End Results

G9 converts the accepted G2-G8 components into one inspectable local operator
scenario. The bundle is wholly fictional and independently verifiable without
Ollama, JWT, network access, or a private corpus.

| Evidence | Result |
| --- | --- |
| Canonical manifest | 5 assets, 2041 bytes, 6 events, 4 domains |
| Initial target | 4 UPSERTs applied, 4 live documents, activated |
| Restart replay | 4/4 replayed with no source files and no asset mutation |
| Replay equivalence | catalog/document/chunk/embedding/order hashes and fixed-query fingerprint equal |
| Change target | 1 policy update, 1 vendor deletion, 3 live documents, installed but not initially active |
| Exact change retry | same plan and publication IDs inside the accepted state |
| CAS | expected-current activation succeeds; stale expected current is rejected |
| Delete | computed active-index residual set is empty |
| Rollback | initial manifest and query fingerprint restored; 1 audit event |
| Public audit | 608 candidates, 0 findings before final documentation |

The deterministic query fingerprints are:

- initial:
  `c26196ad8829d865fa74b5b30a31dd9d136e50351aecfe6feccdcae551ea9f17`;
- changed:
  `13c1c922a01a91b3ead2ca1ed6917edb1521392c144dec930b89e16536d506e5`;
- restored: exactly equal to initial.

### Test evidence

| Scope | Result | JUnit SHA-256 |
| --- | --- | --- |
| G9 final focused | 109 passed, 1 skipped | `670f119f065df9ea2ee0e88d03965cd9953df698f44992f8520d15126a13e8c6` |
| Lifecycle/API/index related before cache hardening | 348 passed, 4 skipped | `f0c73b3ebfb4f451f52e1dcd9508ad11c26dcdda22ddf486053f566b45de2069` |
| Windows cache/publication correction | 111 passed, 1 skipped | `a50aa52de030276ecffc4b541b4cbbbace1c356ca18220f88e9cc84ec1be71b5` |
| Complete repository final | 2281 passed, 28 skipped | `0eecd32e834c3f5fe487127ae2a701b13cc877775a89ef1a9391908e54bfd2bc` |

The complete run finished in 189.54 seconds with three unchanged SWIG
deprecation warnings.

### Independent review outcome

The independent review initially found two P1 and four P2 issues. All six were
converted into tests and resolved before the final suite:

- complete canonical event validation now happens at the concrete transport;
- decoded Base64/MIME identity surfaces are inspected;
- original path components are checked before symlink resolution;
- replay compares semantic artifact hashes and query behavior;
- fixed queries are bound to exactly one initial source;
- deletion residue is computed and explicitly scoped to the active index.

### Additional engineering result

Full-suite validation found a previously intermittent four-process cache
bootstrap race. Root ACL hardening had occurred before the interprocess lock
existed. Reads and writes now serialize lock creation, held-directory identity,
ACL hardening, structure checks, and entry access. The exact cold-start
scenario passed 20 consecutive iterations after correction.

### Limitations

- The embedding backend is deterministic test code and is not quality or
  latency evidence.
- The fixture is public synthetic data, not an enterprise pilot.
- Active-index zero residue does not erase immutable old versions, catalog
  history, tombstones, admitted assets, or private computation cache.
- The local lock and pointer protocol is single-host, not distributed.
- One symlink test is skipped on this Windows account because it cannot create
  links; the same test executes on a capable CI host.
- No G10 performance claim is accepted until experiments are preregistered and
  run.

## G10 Paired Lifecycle Performance and Provenance Results

G10 closes `REQ-LC-010` for reproducible local performance evidence and adds
measured support for the G6 reuse claim under the exact G10 boundary.

### Formal experiment identity

| Field | Accepted value |
| --- | --- |
| Registration | `EXP-LC-007` |
| Running transition | `EXP-LC-008` |
| Completion | `EXP-LC-009` |
| Frozen source commit | `5570d022cd0be73625748a07a9fcea26eaa97630` |
| Dataset | `expanded_benchmark_lifecycle_v4`, 1225 base documents |
| Pairs | 10, alternating AB/BA |
| Raw artifacts | 45, all SHA-256 bound |
| Public package | `data/v2/public/lifecycle_g10_v2` |

### Result

| Metric | Observed |
| --- | ---: |
| Correctness-equivalent pairs | 10/10 |
| Faster intervention pairs | 10/10 |
| Median intervention/baseline wall-time ratio | 0.716599 |
| P95 wall-time ratio | 0.743191 |
| Baseline-first median ratio | 0.706155 |
| Intervention-first median ratio | 0.721557 |
| Baseline embedding callbacks | 12,170 |
| Intervention embedding callbacks | 310 |
| Embedding-call ratio | 0.025472 |
| Baseline peak RSS | 381,550,592 bytes |
| Intervention peak RSS | 379,273,216 bytes |
| Active-index deleted residual count | 0 |
| Frozen decision | `SUPPORTED` |

The accepted resume/project statement is:

> On a frozen 1225-document deterministic local lifecycle workload, a
> preregistered 10-pair AB/BA experiment found that production computation
> reuse preserved exact target, ACL, query, and deletion correctness while
> reducing median complete target-build wall time by 28.34% and embedding
> callbacks by 97.45%.

The statement must retain “deterministic local lifecycle workload.” It must not
be shortened into a real-model, production-QPS, or customer-data claim.

### Verification evidence

Before the formal source commit, the hardened focused suite passed 175 tests
with 7 skips, and the complete repository passed 2356 tests with 30 skips.
The public audit inspected 622 candidates and found zero findings.

The final public package has 52 files and 3,196,456 bytes. The standalone
verifier recomputed `10 pairs, SUPPORTED` from the package alone. Final
post-package focused/full JUnit, audit, and integrated lifecycle validation
results are recorded in the G10 handoff.

### Remaining limits

- Base-template construction and raw file admission are outside timing.
- Deterministic embeddings measure lifecycle overhead, not Ollama latency.
- Synthetic data does not establish semantic relevance, answer faithfulness,
  or enterprise-user acceptance.
- The benchmark is local and single-host; it is not a distributed throughput
  or concurrency-capacity result.
- `FAIL-LC-076` remains open for an old host-temp ACL residue. Subsequent
  commands use only the project D-drive temporary root.
