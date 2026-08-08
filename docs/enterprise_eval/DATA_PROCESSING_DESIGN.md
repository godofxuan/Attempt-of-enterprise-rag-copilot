# Enterprise Data Processing Design

## Non-negotiable boundary

Adapters preserve official fields and raw provenance. They may normalize names,
types, and deterministic IDs, but they must not infer authors, timestamps,
threads, freshness, relevance, or ACL metadata that the source does not provide.
Raw benchmark data and indexes live under `.private/external/` on `D:` and are
never committed.

## Canonical envelope

The existing `DocumentRecord` remains the production policy-document contract.
External heterogeneous adapters should use an additive `EnterpriseDocument`
envelope and convert to index records only at the boundary.

Required core fields:

- `document_id`, `source_type`, `source_native_id`, `title`, `text`
- `sections`, `source_metadata`, `raw_provenance`

Optional fields copied only when official data provides them:

- `author`, `participants`, `timestamp`, `thread_id`, `parent_id`
- `project_id`, `status`, `version`, `freshness`

Every transformed record must bind dataset name, source revision, source file,
source row/native ID, and raw-record SHA-256. Unknown values remain null.

EnterpriseRAG-Bench demonstrates why `source_native_id` is not assumed to be a
primary key. Four IDs are reused by distinct official records, including the
conflicting evidence referenced by `qst_0413`. Its adapter therefore identifies
an internal record as `source_native_id + raw-record hash`, while retaining the
unmodified source ID for gold matching. Empty raw titles/bodies are preserved in
the raw hash; normalization uses only another official field or the source ID and
emits explicit `raw_*_was_empty` metadata.

The full-corpus lexical control is document-level FTS5 rather than an in-memory
list of Python tokens. Its `records` table keeps row identity, source identity,
source type, and raw hash; the contentless FTS table keeps searchable postings.
This separation lowers memory and duplicate storage while preserving the ability
to map every hit back to an immutable Parquet row. Search never uses benchmark
`source_types` as an oracle filter.

## Source-preserving adapters

| Source | Preserve when present | Source-aware candidate boundary |
|---|---|---|
| Slack | channel, thread, message, author, timestamp | keep a thread together where budgets permit; attach channel/thread identity |
| Gmail | subject, thread, sender, recipients, timestamp, message order | chunk by message/thread; do not merge unrelated mail with the same subject |
| Linear/Jira | title, description, status, assignee, comments | keep ticket body and bounded comment windows with ticket identity |
| GitHub | repository, issue/PR, comments, file references | preserve issue/PR conversation and repository identity |
| Confluence/Drive/Wix KB | title, heading hierarchy, sections, lists, links | section/procedure-aware chunks with document identity |
| Meeting transcript | speaker, turn, timestamp | contiguous speaker-turn windows; preserve meeting identity |
| CRM | record type and official fields | field-aware serialization without guessing business semantics |

## Controls and candidates

### Flat control

Use the current deterministic fixed-window chunker. This is deliberately simple
and remains the control even if it performs poorly.

### Source-aware candidate

Use only the structure actually present in a selected benchmark. For WixQA this
means preserving article ID, title, heading/section hierarchy, ordered steps,
unordered lists, notes/warnings, links, and section boundaries when present in
the official corpus representation. It must not degrade into a single
`BeautifulSoup.get_text()` blob.

For heterogeneous data, thread-, ticket-, speaker-, or procedure-aware chunking
is implemented one source at a time and only after a failure category justifies
it. The candidate and flat control share corpus rows, embedding model, retrieval
parameters, query set, and metric code.

## WixQA frozen processing protocol

1. Acquire files only from the official dataset repository at the manifest pin.
2. Verify every downloaded file hash before parsing.
3. Count and schema-check rows without printing question text or labels.
4. Freeze local consumption roles by official question ID before candidate
   optimization.
5. Build both `WIX_FLAT` and `WIX_STRUCTURE_AWARE` representations from the same
   raw article rows.
6. Preserve official article IDs end-to-end so retrieval metrics require no
   fuzzy title matching.
7. Record parser/chunker version and canonical artifact hash.
8. Build BM25, dense, and hybrid arms from the same canonical artifact.

## Agent comparison contract

- A: single-shot BM25+dense+RRF.
- B: current bounded `search -> conditional open`, using the exact A retriever.
- C: `search -> find -> open` is not a current baseline because the default
  controller does not emit `find`. It may become a candidate only after a
  measured within-document search failure and an explicit bounded policy.

Each arm records retrieval/tool calls per query, documents opened, input/output
tokens when available, latency distribution, answer/retrieval success, and stop
reason. If Agent quality is equivalent and latency is at least 3x, the decision
is `AGENTIC_ROUTE_REJECTED`.

The WixQA B3 adapter does not rebuild or replace retrieval. It maps a frozen RRF
article ranking into the production typed search contract, chooses a query-linked
representative chunk from each ranked article, and represents the short matched
preview plus full chunk as child/parent evidence for the retrieved-content Guard.
The Agent's first original-question search reuses the exact B2 ranking cache;
only controller-generated subqueries may add retrieval/model calls.

## What this design does not claim

It does not claim source-aware chunks improve quality, that a 500k-document
index fits locally, that the current Agent outperforms RAG, or that benchmark
metadata provides real ACLs/version truth. Those are experiment outcomes.
