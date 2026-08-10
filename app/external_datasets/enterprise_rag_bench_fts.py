from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.enterprise_rag_bench import (
    ENTERPRISE_RAG_BENCH_DATASET_REVISION,
    iter_enterprise_rag_bench_documents,
)
from app.external_datasets.wixqa import canonical_json_bytes


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EnterpriseRAGBenchFTSArtifact(_StrictModel):
    path: Literal["index.sqlite3"] = "index.sqlite3"
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1)


class EnterpriseRAGBenchFTSManifest(_StrictModel):
    schema_version: Literal["enterprise_rag_bench_fts5_v1"] = (
        "enterprise_rag_bench_fts5_v1"
    )
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    dataset_revision: Literal[
        "69916e31c68aa5963c00248fd7f0bc12d04fd235"
    ] = ENTERPRISE_RAG_BENCH_DATASET_REVISION
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_row_count: int = Field(ge=1)
    unique_source_id_count: int = Field(ge=1)
    ordered_records_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_counts: dict[str, int]
    sqlite_version: str = Field(min_length=1)
    tokenizer: Literal["porter unicode61 remove_diacritics 2"] = (
        "porter unicode61 remove_diacritics 2"
    )
    title_bm25_weight: float = Field(default=3.0, gt=0)
    content_bm25_weight: float = Field(default=1.0, gt=0)
    commit_interval: int = Field(ge=1)
    resumed_from_document: int = Field(ge=0)
    active_build_duration_ms: float = Field(ge=0)
    build_peak_rss_bytes: int = Field(ge=0)
    artifact: EnterpriseRAGBenchFTSArtifact

    @model_validator(mode="after")
    def validate_counts(self) -> "EnterpriseRAGBenchFTSManifest":
        if sum(self.source_counts.values()) != self.document_row_count:
            raise ValueError("source counts do not equal document row count")
        if self.unique_source_id_count > self.document_row_count:
            raise ValueError("unique source count exceeds document rows")
        return self


class EnterpriseRAGBenchFTSHit(_StrictModel):
    rank: int = Field(ge=1)
    record_id: str = Field(min_length=1)
    source_native_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    raw_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    score: float


class LoadedEnterpriseRAGBenchFTS:
    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        manifest: EnterpriseRAGBenchFTSManifest,
    ) -> None:
        self.connection = connection
        self.manifest = manifest

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "LoadedEnterpriseRAGBenchFTS":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def search(self, query: str, *, top_k: int = 5) -> list[EnterpriseRAGBenchFTSHit]:
        if top_k < 1 or top_k > 100:
            raise ValueError("top_k must be between 1 and 100")
        compiled = compile_fts_query(query)
        candidate_k = min(max(top_k * 4, top_k), 400)
        rows = self.connection.execute(
            """
            SELECT r.record_id, r.source_native_id, r.source_type,
                   r.raw_record_sha256,
                   bm25(documents_fts, ?, ?) AS score
            FROM documents_fts
            JOIN records AS r ON r.source_row = documents_fts.rowid
            WHERE documents_fts MATCH ?
            ORDER BY score ASC, r.record_id ASC
            LIMIT ?
            """,
            (
                self.manifest.title_bm25_weight,
                self.manifest.content_bm25_weight,
                compiled,
                candidate_k,
            ),
        ).fetchall()
        hits: list[EnterpriseRAGBenchFTSHit] = []
        seen_source_ids: set[str] = set()
        for row in rows:
            if row[1] in seen_source_ids:
                continue
            seen_source_ids.add(row[1])
            hits.append(
                EnterpriseRAGBenchFTSHit(
                    rank=len(hits) + 1,
                    record_id=row[0],
                    source_native_id=row[1],
                    source_type=row[2],
                    raw_record_sha256=row[3],
                    score=float(row[4]),
                )
            )
            if len(hits) == top_k:
                break
        return hits


def compile_fts_query(query: str) -> str:
    tokens = list(dict.fromkeys(_TOKEN_PATTERN.findall(query.lower())))
    if not tokens:
        raise ValueError("query contains no searchable tokens")
    filtered = [token for token in tokens if token not in _QUERY_STOPWORDS]
    selected = filtered or tokens
    return " OR ".join(f'"{token}"' for token in selected)


def build_enterprise_rag_bench_fts(
    *,
    documents_path: Path,
    output_root: Path,
    run_id: str,
    corpus_sha256: str,
    dataset_manifest_sha256: str,
    expected_document_count: int,
    commit_interval: int = 5000,
    interrupt_after_documents: int | None = None,
) -> EnterpriseRAGBenchFTSManifest:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid FTS run_id")
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _single_writer_build_lock(root, run_id=run_id):
        return _build_enterprise_rag_bench_fts(
            documents_path=documents_path,
            output_root=root,
            run_id=run_id,
            corpus_sha256=corpus_sha256,
            dataset_manifest_sha256=dataset_manifest_sha256,
            expected_document_count=expected_document_count,
            commit_interval=commit_interval,
            interrupt_after_documents=interrupt_after_documents,
        )


def _build_enterprise_rag_bench_fts(
    *,
    documents_path: Path,
    output_root: Path,
    run_id: str,
    corpus_sha256: str,
    dataset_manifest_sha256: str,
    expected_document_count: int,
    commit_interval: int,
    interrupt_after_documents: int | None,
) -> EnterpriseRAGBenchFTSManifest:
    if expected_document_count < 1:
        raise ValueError("expected document count must be positive")
    if commit_interval < 1 or commit_interval > 50_000:
        raise ValueError("commit interval must be between 1 and 50000")
    root = Path(output_root).resolve()
    versions = root / "versions"
    target = versions / run_id
    stage = versions / f".{run_id}.building"
    if target.exists():
        raise FileExistsError(f"FTS index version already exists: {run_id}")
    versions.mkdir(parents=True, exist_ok=True)
    stage.mkdir(exist_ok=True)
    database_path = stage / "index.sqlite3"
    connection = _connect_builder(database_path)
    started = time.perf_counter()
    try:
        _initialize_schema(connection)
        _validate_or_initialize_build(
            connection,
            corpus_sha256=corpus_sha256,
            dataset_manifest_sha256=dataset_manifest_sha256,
            expected_document_count=expected_document_count,
        )
        resumed_from = int(_get_meta(connection, "processed_documents"))
        pending = 0
        for document in iter_enterprise_rag_bench_documents(
            documents_path, batch_size=min(commit_interval, 10_000)
        ):
            source_row = document.raw_provenance.source_row
            if source_row <= resumed_from:
                continue
            connection.execute(
                """
                INSERT INTO records(
                    source_row, record_id, source_native_id, source_type,
                    raw_record_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    source_row,
                    document.document_id,
                    document.source_native_id,
                    document.source_type,
                    document.raw_provenance.raw_record_sha256,
                ),
            )
            connection.execute(
                "INSERT INTO documents_fts(rowid, title, content) VALUES (?, ?, ?)",
                (source_row, document.title, document.text),
            )
            pending += 1
            should_interrupt = (
                interrupt_after_documents is not None
                and source_row >= interrupt_after_documents
            )
            if pending >= commit_interval or should_interrupt:
                _set_meta(connection, "processed_documents", str(source_row))
                connection.commit()
                pending = 0
                print(
                    f"indexed {source_row}/{expected_document_count}", flush=True
                )
            if should_interrupt:
                raise InterruptedError(
                    f"injected interruption after source row {source_row}"
                )
        if pending:
            _set_meta(connection, "processed_documents", str(expected_document_count))
            connection.commit()
        processed = int(_get_meta(connection, "processed_documents"))
        if processed != expected_document_count:
            raise ValueError(
                f"document count mismatch: {processed} != {expected_document_count}"
            )
        connection.execute(
            "INSERT INTO documents_fts(documents_fts) VALUES ('optimize')"
        )
        _set_meta(connection, "build_status", "COMPLETE")
        connection.commit()
        source_counts = {
            row[0]: int(row[1])
            for row in connection.execute(
                "SELECT source_type, COUNT(*) FROM records GROUP BY source_type "
                "ORDER BY source_type"
            )
        }
        unique_source_ids = int(
            connection.execute(
                "SELECT COUNT(DISTINCT source_native_id) FROM records"
            ).fetchone()[0]
        )
        ordered_hash = _ordered_records_sha256(connection)
    finally:
        connection.close()

    database_bytes = database_path.stat().st_size
    database_sha256 = _sha256(database_path)
    manifest = EnterpriseRAGBenchFTSManifest(
        run_id=run_id,
        corpus_sha256=corpus_sha256,
        dataset_manifest_sha256=dataset_manifest_sha256,
        document_row_count=expected_document_count,
        unique_source_id_count=unique_source_ids,
        ordered_records_sha256=ordered_hash,
        source_counts=source_counts,
        sqlite_version=sqlite3.sqlite_version,
        commit_interval=commit_interval,
        resumed_from_document=resumed_from,
        active_build_duration_ms=(time.perf_counter() - started) * 1000,
        build_peak_rss_bytes=_peak_working_set_bytes(),
        artifact=EnterpriseRAGBenchFTSArtifact(
            sha256=database_sha256,
            byte_count=database_bytes,
        ),
    )
    (stage / "manifest.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    verify_enterprise_rag_bench_fts(stage)
    os.replace(stage, target)
    _activate(root, manifest)
    return manifest


@contextmanager
def _single_writer_build_lock(root: Path, *, run_id: str) -> Iterator[None]:
    lock_path = root / ".single-writer-build.lock"
    token = secrets.token_hex(16)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        opened = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (opened.st_dev, opened.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            raise RuntimeError("EnterpriseRAG FTS build lock is unsafe")
        _lock_fts_descriptor(descriptor)
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise RuntimeError(
            "EnterpriseRAG FTS is a single-writer offline builder; "
            "another build lock is already held"
        ) from exc
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        raise
    try:
        owner = canonical_json_bytes(
            {
                "pid": os.getpid(),
                "run_id": run_id,
                "token": token,
            }
        )
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, owner)
        os.fsync(descriptor)
        yield
    finally:
        try:
            _unlock_fts_descriptor(descriptor)
        finally:
            os.close(descriptor)


def _lock_fts_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fts_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def verify_enterprise_rag_bench_fts(path: Path) -> EnterpriseRAGBenchFTSManifest:
    root = Path(path).resolve()
    manifest_bytes = (root / "manifest.json").read_bytes()
    manifest = EnterpriseRAGBenchFTSManifest.model_validate_json(manifest_bytes)
    database_path = root / manifest.artifact.path
    if database_path.stat().st_size != manifest.artifact.byte_count:
        raise ValueError("FTS database byte count mismatch")
    if _sha256(database_path) != manifest.artifact.sha256:
        raise ValueError("FTS database SHA-256 mismatch")
    connection = _connect_reader(database_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"FTS database integrity check failed: {integrity}")
        record_count = int(connection.execute("SELECT COUNT(*) FROM records").fetchone()[0])
        fts_count = int(
            connection.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
        )
        if record_count != manifest.document_row_count or fts_count != record_count:
            raise ValueError("FTS row count mismatch")
        if _ordered_records_sha256(connection) != manifest.ordered_records_sha256:
            raise ValueError("FTS ordered record hash mismatch")
    finally:
        connection.close()
    return manifest


def load_enterprise_rag_bench_fts(output_root: Path) -> LoadedEnterpriseRAGBenchFTS:
    root = Path(output_root).resolve()
    active = json.loads((root / "active.json").read_text(encoding="utf-8"))
    version = root / "versions" / active["run_id"]
    manifest_bytes = (version / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != active["manifest_sha256"]:
        raise ValueError("active FTS manifest SHA-256 mismatch")
    manifest = verify_enterprise_rag_bench_fts(version)
    return LoadedEnterpriseRAGBenchFTS(
        connection=_connect_reader(version / manifest.artifact.path),
        manifest=manifest,
    )


def _connect_builder(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=60)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-131072")
    return connection


def _connect_reader(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=60)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-65536")
    return connection


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS build_metadata(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS records(
            source_row INTEGER PRIMARY KEY,
            record_id TEXT NOT NULL UNIQUE,
            source_native_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_record_sha256 TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS records_source_native_id
            ON records(source_native_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            title,
            content,
            content='',
            tokenize='porter unicode61 remove_diacritics 2'
        );
        """
    )
    connection.commit()


def _validate_or_initialize_build(
    connection: sqlite3.Connection,
    *,
    corpus_sha256: str,
    dataset_manifest_sha256: str,
    expected_document_count: int,
) -> None:
    expected = {
        "dataset_revision": ENTERPRISE_RAG_BENCH_DATASET_REVISION,
        "corpus_sha256": corpus_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "expected_document_count": str(expected_document_count),
    }
    existing = dict(connection.execute("SELECT key, value FROM build_metadata"))
    if existing:
        for key, value in expected.items():
            if existing.get(key) != value:
                raise ValueError(f"resumable FTS build metadata mismatch: {key}")
        return
    for key, value in expected.items():
        _set_meta(connection, key, value)
    _set_meta(connection, "processed_documents", "0")
    _set_meta(connection, "build_status", "BUILDING")
    connection.commit()


def _get_meta(connection: sqlite3.Connection, key: str) -> str:
    row = connection.execute(
        "SELECT value FROM build_metadata WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        raise ValueError(f"missing FTS build metadata: {key}")
    return str(row[0])


def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO build_metadata(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _ordered_records_sha256(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in connection.execute(
        "SELECT source_row, record_id, raw_record_sha256 FROM records "
        "ORDER BY source_row"
    ):
        digest.update(canonical_json_bytes(list(row)))
    return digest.hexdigest()


def _activate(root: Path, manifest: EnterpriseRAGBenchFTSManifest) -> None:
    manifest_path = root / "versions" / manifest.run_id / "manifest.json"
    payload = canonical_json_bytes(
        {
            "run_id": manifest.run_id,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }
    )
    active = root / "active.json"
    temporary = root / ".active.json.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, active)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _peak_working_set_bytes() -> int:
    try:
        import psutil

        memory = psutil.Process(os.getpid()).memory_info()
        return int(getattr(memory, "peak_wset", memory.rss))
    except ImportError:
        if os.name != "nt":
            return 0

    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    get_process_memory_info.restype = wintypes.BOOL
    succeeded = get_process_memory_info(
        get_current_process(), ctypes.byref(counters), counters.cb
    )
    return int(counters.PeakWorkingSetSize) if succeeded else 0


def discard_incomplete_fts_build(output_root: Path, run_id: str) -> None:
    stage = Path(output_root).resolve() / "versions" / f".{run_id}.building"
    if stage.exists():
        shutil.rmtree(stage)


__all__ = [
    "EnterpriseRAGBenchFTSHit",
    "EnterpriseRAGBenchFTSManifest",
    "LoadedEnterpriseRAGBenchFTS",
    "build_enterprise_rag_bench_fts",
    "compile_fts_query",
    "discard_incomplete_fts_build",
    "load_enterprise_rag_bench_fts",
    "verify_enterprise_rag_bench_fts",
]
