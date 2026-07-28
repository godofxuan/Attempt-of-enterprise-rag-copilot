from __future__ import annotations

import hashlib
import json
import pickle
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import faiss
import numpy as np
from pydantic import BaseModel, ConfigDict

from app.domain.documents import ChunkRecord, DocumentRecord
from app.indexing.manifest import (
    ArtifactFile,
    BM25Spec,
    EmbeddingSpec,
    FaissSpec,
    IndexManifest,
    load_index_manifest,
    serialize_index_manifest,
)
from app.ingestion.chunking import ChunkerConfig, chunk_document
from app.ingestion.normalize import ingest_corpus, load_source_manifest
from app.ingestion.parsers import ParserRegistry
from app.ingestion.versions import GovernedCorpus, govern_documents
from app.utils import tokenize_for_bm25


EmbedText = Callable[[str], list[float]]
EmbedChunks = Callable[[list[ChunkRecord]], np.ndarray]
BuildPhase = Literal[
    "prepare",
    "embedding",
    "index_construction",
    "artifact_serialization",
    "artifact_write",
    "validation",
]
BuildPhaseObserver = Callable[[BuildPhase, float], None]


class BuildPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    corpus_manifest_hash: str
    source_document_count: int
    canonical_document_count: int
    duplicate_count: int
    chunk_count: int
    indexed_chunk_count: int
    parent_chunk_count: int
    table_chunk_count: int
    parser_versions: dict[str, str]
    chunker_config: dict[str, int | str]
    written: bool = False


@dataclass(frozen=True)
class _PreparedBuild:
    profile_id: str
    corpus_manifest_hash: str
    governed: GovernedCorpus
    chunks: list[ChunkRecord]
    parser_versions: dict[str, str]

    @property
    def indexed_chunks(self) -> list[ChunkRecord]:
        return [chunk for chunk in self.chunks if chunk.indexable]

    @property
    def parent_chunks(self) -> list[ChunkRecord]:
        return [chunk for chunk in self.chunks if not chunk.indexable]


def _profile_id(manifest) -> str:
    return getattr(manifest, "profile_id", None) or manifest.source_profile_id


def _prepare(
    input_dir: Path,
    chunker_config: ChunkerConfig,
    *,
    registry: ParserRegistry | None,
    ingested_at: datetime,
) -> _PreparedBuild:
    input_dir = Path(input_dir)
    manifest_path = input_dir / "manifest.json"
    source_manifest = load_source_manifest(manifest_path)
    records = ingest_corpus(
        input_dir,
        registry=registry,
        ingested_at=ingested_at,
    )
    governed = govern_documents(records)
    chunks = [
        chunk
        for document in governed.documents
        for chunk in chunk_document(document, chunker_config)
    ]
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise AssertionError("chunk IDs must be globally unique")
    parser_versions: dict[str, str] = {}
    for document in governed.documents:
        existing = parser_versions.get(document.parser_name)
        if existing is not None and existing != document.parser_version:
            raise ValueError(
                f"parser {document.parser_name!r} has mixed versions "
                f"{existing!r} and {document.parser_version!r}"
            )
        parser_versions[document.parser_name] = document.parser_version
    return _PreparedBuild(
        profile_id=_profile_id(source_manifest),
        corpus_manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        governed=governed,
        chunks=chunks,
        parser_versions=dict(sorted(parser_versions.items())),
    )


def _preview(prepared: _PreparedBuild, config: ChunkerConfig) -> BuildPreview:
    indexed = prepared.indexed_chunks
    return BuildPreview(
        profile_id=prepared.profile_id,
        corpus_manifest_hash=prepared.corpus_manifest_hash,
        source_document_count=prepared.governed.source_document_count,
        canonical_document_count=len(prepared.governed.documents),
        duplicate_count=len(prepared.governed.duplicate_aliases),
        chunk_count=len(prepared.chunks),
        indexed_chunk_count=len(indexed),
        parent_chunk_count=sum(chunk.kind == "parent" for chunk in prepared.chunks),
        table_chunk_count=sum(chunk.kind == "table" for chunk in prepared.chunks),
        parser_versions=prepared.parser_versions,
        chunker_config=config.model_dump(mode="json"),
        written=False,
    )


def preview_build(
    *,
    input_dir: Path,
    chunker_config: ChunkerConfig,
    registry: ParserRegistry | None = None,
    ingested_at: datetime | None = None,
) -> BuildPreview:
    prepared = _prepare(
        input_dir,
        chunker_config,
        registry=registry,
        ingested_at=ingested_at or datetime.now(timezone.utc),
    )
    return _preview(prepared, chunker_config)


def _json_bytes(models: list[BaseModel]) -> bytes:
    payload = [model.model_dump(mode="json") for model in models]
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / norms


def _validate_embedding_matrix(
    values: object,
    indexed_chunks: list[ChunkRecord],
) -> np.ndarray:
    try:
        vectors = np.asarray(values, dtype="float32")
    except (TypeError, ValueError) as exc:
        raise ValueError("embedding provider returned non-numeric values") from exc
    if vectors.ndim != 2:
        raise ValueError("embedding provider must return a two-dimensional matrix")
    expected_rows = len(indexed_chunks)
    if vectors.shape[0] != expected_rows:
        raise ValueError(
            "embedding row count does not match indexed chunks: "
            f"expected {expected_rows}, got {vectors.shape[0]}"
        )
    if vectors.shape[1] < 1 or vectors.shape[1] > 65_536:
        raise ValueError("embedding dimension is invalid")
    if not np.isfinite(vectors).all():
        raise ValueError("embedding values must be finite numbers")
    norms = np.linalg.norm(vectors, axis=1)
    zero_rows = np.flatnonzero(norms == 0)
    if zero_rows.size:
        chunk = indexed_chunks[int(zero_rows[0])]
        raise ValueError(f"embedding is zero for chunk {chunk.chunk_id!r}")
    return np.ascontiguousarray(vectors, dtype="float32")


def _build_artifact_bytes(
    prepared: _PreparedBuild,
    embed_text: EmbedText | None,
    *,
    embed_chunks: EmbedChunks | None = None,
    phase_observer: BuildPhaseObserver | None = None,
) -> tuple[dict[str, bytes], int]:
    indexed_chunks = prepared.indexed_chunks
    if not indexed_chunks:
        raise ValueError("build has no indexable chunks")
    embedding_started = time.perf_counter()
    if embed_chunks is not None:
        array = _validate_embedding_matrix(
            embed_chunks(indexed_chunks),
            indexed_chunks,
        )
    else:
        if embed_text is None:
            raise ValueError("an embedding provider is required")
        embeddings: list[list[float]] = []
        dimension: int | None = None
        for chunk in indexed_chunks:
            vector = list(embed_text(chunk.text))
            if not vector:
                raise ValueError(f"embedding is empty for chunk {chunk.chunk_id!r}")
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise ValueError(
                    f"embedding dimensions are inconsistent: expected {dimension}, "
                    f"got {len(vector)} for {chunk.chunk_id!r}"
                )
            embeddings.append(vector)
        array = _validate_embedding_matrix(embeddings, indexed_chunks)
    _observe_phase(phase_observer, "embedding", embedding_started)

    construction_started = time.perf_counter()
    array = _normalize_vectors(array)
    index = faiss.IndexFlatIP(array.shape[1])
    index.add(array)
    tokenized = [tokenize_for_bm25(chunk.text) for chunk in indexed_chunks]
    _observe_phase(phase_observer, "index_construction", construction_started)

    serialization_started = time.perf_counter()
    artifacts = {
        "documents.json": _json_bytes(prepared.governed.documents),
        "chunks.json": _json_bytes(indexed_chunks),
        "parents.json": _json_bytes(prepared.parent_chunks),
        "bm25_tokens.pkl": pickle.dumps(tokenized, protocol=pickle.HIGHEST_PROTOCOL),
        "faiss.index": faiss.serialize_index(index).tobytes(),
    }
    _observe_phase(
        phase_observer,
        "artifact_serialization",
        serialization_started,
    )
    return artifacts, int(array.shape[1])


def _artifact_records(artifacts: dict[str, bytes]) -> list[ArtifactFile]:
    return [
        ArtifactFile(
            path=path,
            sha256=hashlib.sha256(content).hexdigest(),
            byte_count=len(content),
        )
        for path, content in sorted(artifacts.items())
    ]


def _ensure_empty_output(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise FileExistsError(f"output path is not a directory: {output_dir}")
    if output_dir.is_dir() and next(output_dir.iterdir(), None) is not None:
        raise FileExistsError(f"output directory is not empty: {output_dir}")


def _observe_phase(
    observer: BuildPhaseObserver | None,
    phase: BuildPhase,
    started_at: float,
) -> None:
    if observer is not None:
        observer(phase, max(0.0, (time.perf_counter() - started_at) * 1000.0))


def build_index_artifacts(
    *,
    input_dir: Path,
    output_dir: Path,
    run_id: str,
    chunker_config: ChunkerConfig,
    embedding_model: str,
    embed_text: EmbedText | None = None,
    embed_chunks: EmbedChunks | None = None,
    registry: ParserRegistry | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    phase_observer: BuildPhaseObserver | None = None,
) -> IndexManifest:
    if (embed_text is None) == (embed_chunks is None):
        raise ValueError("provide exactly one of embed_text or embed_chunks")
    output_dir = Path(output_dir)
    _ensure_empty_output(output_dir)
    start = started_at or datetime.now(timezone.utc)
    prepare_started = time.perf_counter()
    prepared = _prepare(
        input_dir,
        chunker_config,
        registry=registry,
        ingested_at=start,
    )
    _observe_phase(phase_observer, "prepare", prepare_started)
    artifacts, dimension = _build_artifact_bytes(
        prepared,
        embed_text,
        embed_chunks=embed_chunks,
        phase_observer=phase_observer,
    )
    finish = finished_at or datetime.now(timezone.utc)
    preview = _preview(prepared, chunker_config)
    manifest = IndexManifest(
        schema_version="enterprise_index_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        index_version="v2",
        run_id=run_id,
        profile_id=prepared.profile_id,
        corpus_manifest_hash=prepared.corpus_manifest_hash,
        embedding=EmbeddingSpec(
            model=embedding_model,
            dimension=dimension,
            normalization="l2",
        ),
        faiss=FaissSpec(index_type="IndexFlatIP", metric="inner_product"),
        bm25=BM25Spec(
            tokenizer="jieba",
            parameters={"k1": 1.5, "b": 0.75, "epsilon": 0.25},
        ),
        chunker_config=chunker_config.model_dump(mode="json"),
        parser_versions=prepared.parser_versions,
        source_document_count=preview.source_document_count,
        canonical_document_count=preview.canonical_document_count,
        duplicate_count=preview.duplicate_count,
        chunk_count=preview.chunk_count,
        indexed_chunk_count=preview.indexed_chunk_count,
        parent_chunk_count=preview.parent_chunk_count,
        table_chunk_count=preview.table_chunk_count,
        started_at=start,
        finished_at=finish,
        duration_ms=max(0, round((finish - start).total_seconds() * 1000)),
        artifacts=_artifact_records(artifacts),
    )

    write_started = time.perf_counter()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    for relative_path, content in artifacts.items():
        (output_dir / relative_path).write_bytes(content)
    (output_dir / "manifest.json").write_bytes(serialize_index_manifest(manifest))
    _observe_phase(phase_observer, "artifact_write", write_started)

    validation_started = time.perf_counter()
    validate_index_directory(output_dir, manifest)
    _observe_phase(phase_observer, "validation", validation_started)
    return manifest


def validate_index_directory(output_dir: Path, manifest: IndexManifest) -> None:
    output_dir = Path(output_dir)
    loaded = load_index_manifest(output_dir / "manifest.json")
    if loaded != manifest:
        raise ValueError("on-disk manifest does not match expected manifest")
    required_artifacts = {
        "documents.json",
        "chunks.json",
        "parents.json",
        "bm25_tokens.pkl",
        "faiss.index",
    }
    declared_artifacts = {artifact.path for artifact in manifest.artifacts}
    missing = required_artifacts - declared_artifacts
    if missing:
        raise ValueError(
            "index manifest does not bind required runtime artifacts: "
            + ", ".join(sorted(missing))
        )
    for artifact in manifest.artifacts:
        path = output_dir / artifact.path
        if not path.is_file():
            raise FileNotFoundError(f"index artifact is missing: {artifact.path}")
        content = path.read_bytes()
        if len(content) != artifact.byte_count:
            raise ValueError(f"artifact byte count mismatch: {artifact.path}")
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ValueError(f"artifact hash mismatch: {artifact.path}")

    chunks = json.loads((output_dir / "chunks.json").read_text(encoding="utf-8"))
    parents = json.loads((output_dir / "parents.json").read_text(encoding="utf-8"))
    documents = json.loads((output_dir / "documents.json").read_text(encoding="utf-8"))
    with (output_dir / "bm25_tokens.pkl").open("rb") as handle:
        tokenized = pickle.load(handle)
    index = faiss.deserialize_index(
        np.frombuffer((output_dir / "faiss.index").read_bytes(), dtype=np.uint8).copy()
    )
    if len(chunks) != manifest.indexed_chunk_count:
        raise ValueError("chunks.json count does not match manifest")
    if len(parents) != manifest.chunk_count - manifest.indexed_chunk_count:
        raise ValueError("parents.json count does not match manifest")
    if len(documents) != manifest.canonical_document_count:
        raise ValueError("documents.json count does not match manifest")
    if len(tokenized) != manifest.indexed_chunk_count:
        raise ValueError("BM25 token count does not match manifest")
    if index.ntotal != manifest.indexed_chunk_count:
        raise ValueError("FAISS vector count does not match manifest")
    if index.d != manifest.embedding.dimension:
        raise ValueError("FAISS dimension does not match manifest")
