# E2 Parser and Index Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 legacy `glob text -> four-field dict -> overwrite active files` 升级为七格式 Parser Registry、规范化 Document/Chunk contracts、可比较 chunking、去重/版本治理和带 manifest/active pointer 的安全全量索引生命周期。

**Architecture:** Parser 只处理文件结构并输出 `ParseResult`，normalizer 将 E1 corpus manifest 治理字段合并为 `DocumentRecord`。Chunker 保留 fixed baseline，并实现 heading/parent-child/table；index builder 通过注入 embedder 在 staging 构建版本目录，验证后切换 `active.json`，legacy search 默认路径在 E3 前保持不变。

**Tech Stack:** Python 3.11、Pydantic v2、stdlib HTML/CSV/JSON/zip/pathlib/hashlib、pypdf 6.x、python-docx 1.2.x、FAISS、rank-bm25、pytest。

## Global Constraints

- 所有 production 行为先有一个已观察到正确失败原因的测试。
- `--help`、`--dry-run` 和自动测试不得调用 Ollama。
- E1 frozen test、facts、profiles 和 corpus generator 不因 E2 调整。
- parser 空文本/结构化失败不得进入 normalization/index。
- PDF 不做 OCR，扫描图片页必须产生 warning 或 empty-document failure。
- parent chunks 默认 `indexable=false`；children/table chunks 进入索引。
- legacy `hybrid_search()` 默认仍加载 `data/indexes`，E3 前不切生产读取路径。
- R1 E2 只实现 versioned full rebuild；不做增量 upsert/delete。
- 不引入 BeautifulSoup/lxml、reranker、向量数据库或任务队列。
- 未经本人确认不执行 git add/commit/push/merge/tag。

---

### Task 1: Domain Contracts and Structured Parse Errors

**Files:**
- Create: `app/domain/__init__.py`
- Create: `app/domain/documents.py`
- Create: `tests/ingestion/test_document_models.py`

**Interfaces:**
- Consumes: E1 `ManifestDocument` governance metadata concepts.
- Produces: `SourceLocator`, `ParseWarning`, `ParsedSection`, `ParsedTable`, `ParseResult`, `DocumentVersion`, `DocumentRecord`, `ChunkRecord`, `DocumentParseError`.

- [ ] **Step 1: Write failing model tests**

Tests must request these behaviors:

```python
def test_parse_result_rejects_empty_text_without_warning(): ...
def test_document_record_requires_timezone_aware_ingested_at(): ...
def test_document_version_rejects_invalid_interval(): ...
def test_chunk_record_requires_parent_for_child_kind(): ...
def test_document_parse_error_serializes_code_parser_and_path(): ...
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ingestion\test_document_models.py -q
```

Expected: collection error because `app.domain.documents` does not exist.

- [ ] **Step 3: Implement minimal strict Pydantic models**

Required fields:

```python
class ParseResult(StrictModel):
    text: str
    sections: list[ParsedSection]
    headings: list[str]
    tables: list[ParsedTable]
    metadata: dict[str, str]
    source_location: str
    parse_warnings: list[ParseWarning]
    parser_name: str
    parser_version: str

class DocumentRecord(StrictModel):
    doc_id: str
    title: str
    source_type: str
    source_path: str
    format: str
    department: str
    project_id: str | None
    policy_id: str | None
    region: str
    tenant_id: str
    acl_groups: list[str]
    document_version: DocumentVersion
    authority_level: int
    checksum: str
    normalized_text_hash: str
    ingested_at: datetime
    parser_name: str
    parser_version: str
    text: str
    sections: list[ParsedSection]
    tables: list[ParsedTable]
    parse_warnings: list[ParseWarning]
```

`ChunkRecord` includes stable ID, doc metadata, section path, locator, kind, `parent_chunk_id`, `indexable`, text and hashes.

- [ ] **Step 4: Run GREEN and record E2-C01**

Expected: all model tests pass. Update E2 journal with RED command/failure scope and GREEN result.

### Task 2: Five Standard-Library Parsers and Registry

**Files:**
- Create: `app/ingestion/__init__.py`
- Create: `app/ingestion/parsers.py`
- Create: `tests/ingestion/test_parsers_text.py`
- Reuse: `data/v2/fixtures/smoke/documents/*.{md,txt,html,csv,jsonl}`

**Interfaces:**
- Consumes: local file `Path`.
- Produces: `ParserRegistry.parse(path) -> ParseResult` or `DocumentParseError`.

- [ ] **Step 1: Write one failing test per format and registry failure**

Required assertions:

```text
Markdown keeps heading level/path and line locator.
TXT returns one General section.
HTML extracts h1/h2/p and table rows without markup.
CSV preserves headers and row locator.
JSONL preserves union headers and line locator.
Unknown extension returns structured unsupported_format error.
Malformed UTF-8/CSV/JSONL returns structured parse error.
Empty parsed content is rejected.
```

- [ ] **Step 2: Verify RED because parser module is missing**

- [ ] **Step 3: Implement `DocumentParser` protocol and explicit suffix registry**

No parser guesses by file content. Registry keys are lowercase suffixes, duplicate registration is rejected, and exceptions are wrapped with parser/path/code while preserving cause.

- [ ] **Step 4: Implement Markdown/TXT/HTML/CSV/JSONL parsers with stdlib**

HTML uses a small `HTMLParser` subclass. CSV uses `csv.DictReader`; JSONL parses each nonblank line independently and reports exact line on failure.

- [ ] **Step 5: Run targeted tests and update E2-C02 partial record**

### Task 3: PDF/DOCX Dependency Gate and Fixtures

**Files:**
- Modify: `requirements.txt`
- Create: `app/ingestion/parsers_pdf.py`
- Create: `app/ingestion/parsers_docx.py`
- Create: `tests/fixtures/ingestion/sample_policy.pdf`
- Create: `tests/fixtures/ingestion/sample_policy.docx`
- Create: `tests/fixtures/ingestion/empty_page.pdf`
- Create: `tests/ingestion/test_parsers_office.py`

**Interfaces:**
- Consumes: PDF/DOCX paths.
- Produces: page/paragraph/table-aware `ParseResult`.

- [ ] **Step 1: Write failing tests before installing dependencies**

Tests assert:

```text
PDF text includes expected policy sentence and page locator.
Blank PDF page emits empty_page warning.
All-empty PDF fails before indexing.
DOCX preserves document-order paragraphs/headings/tables.
DOCX table headers and rows are structured.
Malformed PDF/DOCX becomes DocumentParseError.
```

- [ ] **Step 2: Run RED and save missing dependency/module failure**

- [ ] **Step 3: Add bounded dependency ranges and install**

```text
pypdf>=6.14,<7
python-docx>=1.2,<2
```

Install only these packages into `.venv`, then record exact installed versions.

- [ ] **Step 4: Generate deterministic checked-in fixtures**

PDF fixture may be generated once with the already available local PDF writer, but parser tests must read with pypdf. DOCX fixture is generated with python-docx. Record fixture SHA256.

- [ ] **Step 5: Implement parsers and registry entries**

PDF iterates pages and calls `extract_text()`; no OCR. DOCX uses `iter_inner_content()` and heading style levels; tables preserve headers/rows.

- [ ] **Step 6: Run GREEN and all parser tests**

Update E2-D02/E2-I01 with dependency evidence and limitations.

### Task 4: Manifest Normalization and Corpus Ingestion

**Files:**
- Create: `app/ingestion/normalize.py`
- Create: `tests/ingestion/test_normalize.py`

**Interfaces:**
- Consumes: E1 `CorpusManifest`, file bytes and `ParseResult`.
- Produces: `normalize_document(entry, path, result, ingested_at) -> DocumentRecord`; `ingest_corpus(root, registry, ingested_at) -> list[DocumentRecord]`.

- [ ] **Step 1: Write failing tests**

Test governance mapping:

```text
actual_department -> department
tenant -> tenant_id
version/status/effective dates/supersedes -> DocumentVersion
authority -> authority_level
relative manifest path remains relative source_path
file checksum must equal manifest sha256
DocumentRecord checksum/normalized hash are stable
missing file/hash mismatch/path traversal/empty parse all fail closed
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement normalization and manifest-root confinement**

Use resolved path containment, not string prefix. Parser warnings remain attached. `ingested_at` is injectable for deterministic tests.

- [ ] **Step 4: Run GREEN and ingest all five E1 smoke documents**

Update E2-C03.

### Task 5: Fixed, Heading, Parent-Child and Table Chunking

**Files:**
- Create: `app/ingestion/chunking.py`
- Create: `tests/ingestion/test_chunking_v2.py`

**Interfaces:**
- Consumes: `DocumentRecord`, `ChunkerConfig(mode, child_size, parent_size, overlap, table_rows_per_chunk)`.
- Produces: stable `list[ChunkRecord]`.

- [ ] **Step 1: Write failing tests for each mode**

Required behaviors:

```text
fixed reproduces configured windows and overlap.
heading never crosses section boundary unless source has no sections.
long heading section splits with overlap and keeps section path/locator.
parent_child creates one non-indexable parent plus indexable children.
each child references an existing parent.
table chunks repeat headers and preserve row range.
same input/config produces byte-identical IDs; changed text/config changes affected IDs.
all chunk IDs are unique across documents.
invalid overlap >= size is rejected.
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement deterministic window and ID helpers**

ID input must include doc ID, mode, kind, section path/locator, ordinal and text hash. It must not include `ingested_at` or absolute path.

- [ ] **Step 4: Implement modes and table row groups**

- [ ] **Step 5: Run GREEN and update E2-C04**

### Task 6: Exact/Normalized Dedup and Version Governance

**Files:**
- Create: `app/ingestion/versions.py`
- Create: `tests/ingestion/test_versions.py`

**Interfaces:**
- Consumes: `list[DocumentRecord]`.
- Produces: `GovernedCorpus(documents, duplicate_aliases, version_heads, retired_doc_ids)`.

- [ ] **Step 1: Write failing tests**

Test:

```text
same checksum collapses exact duplicate.
different bytes but same normalized text collapses near duplicate.
canonical selection prefers active, then higher authority, then stable doc_id.
duplicates with incompatible tenant/ACL are not collapsed across security boundary.
version graph rejects missing supersedes/cycle/overlap/multiple active heads.
retired documents remain available for history but marked non-current.
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement security-aware dedup and version graph**

Dedup key includes tenant/region/ACL security domain before text hash. Keep aliases for provenance.

- [ ] **Step 4: Run GREEN and govern demo corpus in memory**

Record input count, canonical count, duplicate aliases and version heads without claiming retrieval improvement.

### Task 7: Index Manifest and Staging Builder

**Files:**
- Create: `app/indexing/__init__.py`
- Create: `app/indexing/manifest.py`
- Create: `app/indexing/builder.py`
- Create: `tests/indexing/test_manifest.py`
- Create: `tests/indexing/test_builder.py`

**Interfaces:**
- Consumes: governed documents, chunker config, embed callable, build profile.
- Produces: validated version directory and `IndexManifest`.

- [ ] **Step 1: Write manifest and fake-embedder failing tests**

Manifest requires:

```text
schema/index/run versions
corpus manifest hash
embedding model/dimension/normalization
FAISS index type/metric
BM25 tokenizer/parameters
chunker config
parser versions
source/canonical document counts
chunk/indexed/parent/table counts
dedup counts
build start/end/duration
artifact SHA256/byte counts
```

Builder tests assert fake embedder call count equals indexable chunks, uniform dimension, FAISS ntotal, file hashes and no target writes on failure.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement in-memory preparation and `preview_build()`**

Dry-run parses/governs/chunks and returns measured counts but does not embed or write.

- [ ] **Step 4: Implement staging build and post-write validation**

Write `documents.json`, `chunks.json`, `bm25_tokens.pkl`, `faiss.index`, manifest last. Reopen FAISS and all files, verify counts/hashes before returning success.

- [ ] **Step 5: Run GREEN and update E2-C06**

### Task 8: Version Store, Active Switch and Rollback

**Files:**
- Create: `app/indexing/store.py`
- Create: `tests/indexing/test_store.py`

**Interfaces:**
- Consumes: validated version directories/manifests.
- Produces: `activate_version(root, run_id)`, `load_active_manifest(root)`, `load_index_version(root, run_id | None)`.

- [ ] **Step 1: Write failing lifecycle tests**

Test:

```text
invalid/missing version cannot become active.
active pointer contains run ID and manifest hash.
pointer replacement never exposes partial JSON.
second build retains first version.
rollback switches pointer to first version without rebuilding.
force refuses unowned version directory.
failed second activation keeps old pointer.
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement version-root confinement and atomic pointer replace**

Use temp file in output root, flush/fsync when supported, then `Path.replace(active.json)`. Validate manifest producer and artifact hashes before switch.

- [ ] **Step 4: Run GREEN and update E2-C07**

### Task 9: Safe CLI, Config and Legacy Adapter

**Files:**
- Create: `scripts/build_indexes_v2.py`
- Modify: `app/config.py`
- Modify: `app/retriever.py`
- Create: `tests/indexing/test_cli.py`
- Create: `tests/indexing/test_legacy_adapter.py`

**Interfaces:**
- CLI flags: `--input-dir`, `--output-dir`, `--profile`, `--run-id`, `--chunker`, `--dry-run`, `--force`, `--activate-existing`.
- Legacy wrapper: v2 load functions available but `hybrid_search` behavior unchanged.

- [ ] **Step 1: Write failing CLI tests**

Test help/no writes, required paths, invalid run ID/path traversal, dry-run no Ollama/no writes, default overwrite refusal, owned force, activate-existing rollback and UTF-8 JSON output.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Add v2 config fields without changing legacy defaults**

Add `v2_indexes_dir` and parser/index profile defaults. Do not point `indexes_dir` at v2.

- [ ] **Step 4: Implement CLI and thin legacy adapter**

Actual build imports existing `_embed_text` only after argument validation and only on non-dry-run build path.

- [ ] **Step 5: Run GREEN, help and demo dry-run**

Update E2-C08.

### Task 10: Chunking Ablation, Documentation and Stage Gate

**Files:**
- Create: `scripts/eval_chunking_ablation.py`
- Create: `tests/indexing/test_chunking_ablation.py`
- Modify: `docs/roadmap/e2_parser_index_lifecycle_implementation.md`
- Modify: `docs/roadmap/engineering_decision_failure_ledger.md`
- Create: private E2 audit and learning card

**Interfaces:**
- Consumes: demo corpus, v2 dev cases, fixed/heading/parent-child chunks.
- Produces: JSON summary/details for BM25-only doc retrieval, plus stage evidence.

- [ ] **Step 1: Write failing ablation tests**

Metric contract: evaluate only answered dev cases with gold docs; same tokenizer/top-k; report case count, Hit@k, Recall@k, MRR, chunk counts and per-task failures for each mode.

- [ ] **Step 2: Verify RED, then implement evaluator**

No output path means print JSON only; explicit output creates a new run directory and refuses overwrite.

- [ ] **Step 3: Run actual demo dev ablation**

Record all numbers, including regressions. Explain that BM25-only does not prove dense/Agent quality.

- [ ] **Step 4: Run E2 verification gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ingestion tests\indexing -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --help
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --profile demo --input-dir data\generated\demo --output-dir data\indexes_v2 --dry-run
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
git diff --check
```

- [ ] **Step 5: Complete beginner record and stop before E3**

Document every Change/Incident/Experiment, exact files, RED/GREEN, good/bad results, limitations, interview answers and one hands-on learning acceptance. Do not enter E3 without `批准E2，执行E3检索与Agent工作流`.
