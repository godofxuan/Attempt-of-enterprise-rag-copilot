from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.domain.documents import ChunkRecord
from app.indexing.store import publication_lock
from app.ingestion.chunking import ChunkerConfig


class BatchEmbeddingClient(Protocol):
    model_identifier: str
    model_sha256: str
    dimension: int

    def embed_batch(self, texts: list[str]) -> np.ndarray: ...


class ResumableEmbeddingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["resumable_embedding_manifest_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_identifier: str = Field(min_length=1)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: int = Field(ge=1, le=65_536)
    normalization: Literal["l2"]
    corpus_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_versions: dict[str, str]
    chunker_config: dict[str, int | str]
    ordered_chunks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_count: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    max_batch_chars: int = Field(ge=1)
    batch_count: int = Field(ge=1)


class EmbeddingShardManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["resumable_embedding_shard_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    build_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_index: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    row_count: int = Field(ge=1)
    dimension: int = Field(ge=1, le=65_536)
    dtype: Literal["float32"]
    normalization: Literal["l2"]
    npy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1)


@dataclass(frozen=True)
class EmbeddingBatch:
    index: int
    start: int
    end: int
    character_count: int


@dataclass(frozen=True)
class EmbeddingProgress:
    event: Literal["cache_hit", "computed", "recomputed"]
    build_id: str
    batch_index: int
    completed_batches: int
    total_batches: int
    completed_rows: int
    total_rows: int


@dataclass(frozen=True)
class ResumableEmbeddingSummary:
    build_id: str
    cache_dir: Path
    total_batches: int
    cache_hit_batches: int
    computed_batches: int
    recomputed_batches: int
    vector_count: int
    dimension: int


ProgressObserver = Callable[[EmbeddingProgress], None]


class ResumableBatchEmbedder:
    def __init__(
        self,
        *,
        cache_root: Path,
        client: BatchEmbeddingClient,
        corpus_manifest_sha256: str,
        parser_versions: dict[str, str],
        chunker_config: ChunkerConfig,
        batch_size: int = 32,
        max_batch_chars: int = 48_000,
        progress_observer: ProgressObserver | None = None,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if max_batch_chars < 1:
            raise ValueError("max_batch_chars must be positive")
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self.cache_root = Path(cache_root).resolve()
        self.client = client
        self.corpus_manifest_sha256 = corpus_manifest_sha256
        self.parser_versions = dict(sorted(parser_versions.items()))
        self.chunker_config = chunker_config
        self.batch_size = batch_size
        self.max_batch_chars = max_batch_chars
        self.progress_observer = progress_observer
        self.lock_timeout_seconds = lock_timeout_seconds
        self.summary: ResumableEmbeddingSummary | None = None

    def __call__(self, chunks: list[ChunkRecord]) -> np.ndarray:
        if not chunks:
            raise ValueError("embedding input must contain at least one chunk")
        _verify_chunk_text_hashes(chunks)
        batches = _plan_batches(
            chunks,
            batch_size=self.batch_size,
            max_batch_chars=self.max_batch_chars,
        )
        manifest = self._manifest(chunks, batches)
        manifest_bytes = _canonical_json_bytes(manifest.model_dump(mode="json"))
        build_id = hashlib.sha256(manifest_bytes).hexdigest()
        cache_dir = self.cache_root / build_id
        vectors = np.empty(
            (len(chunks), self.client.dimension),
            dtype="float32",
        )
        cache_hits = 0
        computed = 0
        recomputed = 0
        completed_rows = 0

        with publication_lock(
            cache_dir,
            timeout_seconds=self.lock_timeout_seconds,
        ):
            _bind_manifest(cache_dir, manifest_bytes)
            for batch in batches:
                shard = _load_shard(
                    cache_dir,
                    build_id=build_id,
                    batch=batch,
                    dimension=self.client.dimension,
                )
                event: Literal["cache_hit", "computed", "recomputed"]
                if shard is not None:
                    cache_hits += 1
                    event = "cache_hit"
                else:
                    had_cache_files = _shard_paths(cache_dir, batch)[0].exists()
                    shard = self.client.embed_batch(
                        [chunk.text for chunk in chunks[batch.start : batch.end]]
                    )
                    shard = _normalize_and_validate_shard(
                        shard,
                        expected_rows=batch.end - batch.start,
                        dimension=self.client.dimension,
                    )
                    _store_shard(
                        cache_dir,
                        build_id=build_id,
                        batch=batch,
                        vectors=shard,
                    )
                    if had_cache_files:
                        recomputed += 1
                        event = "recomputed"
                    else:
                        computed += 1
                        event = "computed"
                vectors[batch.start : batch.end] = shard
                completed_rows = batch.end
                if self.progress_observer is not None:
                    self.progress_observer(
                        EmbeddingProgress(
                            event=event,
                            build_id=build_id,
                            batch_index=batch.index,
                            completed_batches=batch.index + 1,
                            total_batches=len(batches),
                            completed_rows=completed_rows,
                            total_rows=len(chunks),
                        )
                    )

        self.summary = ResumableEmbeddingSummary(
            build_id=build_id,
            cache_dir=cache_dir,
            total_batches=len(batches),
            cache_hit_batches=cache_hits,
            computed_batches=computed,
            recomputed_batches=recomputed,
            vector_count=len(chunks),
            dimension=self.client.dimension,
        )
        return vectors

    def _manifest(
        self,
        chunks: list[ChunkRecord],
        batches: list[EmbeddingBatch],
    ) -> ResumableEmbeddingManifest:
        return ResumableEmbeddingManifest(
            schema_version="resumable_embedding_manifest_v1",
            producer="enterprise_agentic_rag_v2",
            implementation_sha256=_implementation_sha256(),
            model_identifier=self.client.model_identifier,
            model_sha256=self.client.model_sha256,
            dimension=self.client.dimension,
            normalization="l2",
            corpus_manifest_sha256=self.corpus_manifest_sha256,
            parser_versions=self.parser_versions,
            chunker_config=self.chunker_config.model_dump(mode="json"),
            ordered_chunks_sha256=_ordered_chunks_sha256(chunks),
            chunk_count=len(chunks),
            batch_size=self.batch_size,
            max_batch_chars=self.max_batch_chars,
            batch_count=len(batches),
        )


def _plan_batches(
    chunks: list[ChunkRecord],
    *,
    batch_size: int,
    max_batch_chars: int,
) -> list[EmbeddingBatch]:
    batches: list[EmbeddingBatch] = []
    start = 0
    character_count = 0
    for index, chunk in enumerate(chunks):
        length = len(chunk.text)
        if length > max_batch_chars:
            raise ValueError(
                f"chunk {chunk.chunk_id!r} exceeds max_batch_chars "
                f"({length} > {max_batch_chars})"
            )
        current_rows = index - start
        if current_rows and (
            current_rows >= batch_size
            or character_count + length > max_batch_chars
        ):
            batches.append(
                EmbeddingBatch(
                    index=len(batches),
                    start=start,
                    end=index,
                    character_count=character_count,
                )
            )
            start = index
            character_count = 0
        character_count += length
    batches.append(
        EmbeddingBatch(
            index=len(batches),
            start=start,
            end=len(chunks),
            character_count=character_count,
        )
    )
    return batches


def _verify_chunk_text_hashes(chunks: list[ChunkRecord]) -> None:
    seen: set[str] = set()
    for chunk in chunks:
        actual = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        if actual != chunk.text_hash:
            raise ValueError(f"chunk text hash is invalid: {chunk.chunk_id!r}")
        if chunk.chunk_id in seen:
            raise ValueError(f"duplicate chunk ID: {chunk.chunk_id!r}")
        seen.add(chunk.chunk_id)


def _ordered_chunks_sha256(chunks: list[ChunkRecord]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        for value in (chunk.chunk_id, chunk.text_hash):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def _implementation_sha256() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative_path in (
        "indexing/resumable_embeddings.py",
        "runtime/ollama_embeddings.py",
    ):
        encoded_path = relative_path.encode("ascii")
        content = (root / relative_path).read_bytes()
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _bind_manifest(cache_dir: Path, expected: bytes) -> None:
    path = cache_dir / "manifest.json"
    if path.exists():
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError("embedding cache manifest does not match build identity")
        return
    _atomic_write_bytes(path, expected)


def _shard_paths(
    cache_dir: Path,
    batch: EmbeddingBatch,
) -> tuple[Path, Path]:
    stem = f"batch-{batch.index:06d}-{batch.start:08d}-{batch.end:08d}"
    return cache_dir / f"{stem}.npy", cache_dir / f"{stem}.json"


def _load_shard(
    cache_dir: Path,
    *,
    build_id: str,
    batch: EmbeddingBatch,
    dimension: int,
) -> np.ndarray | None:
    npy_path, manifest_path = _shard_paths(cache_dir, batch)
    if not npy_path.is_file() or not manifest_path.is_file():
        return None
    try:
        raw_manifest = manifest_path.read_bytes()
        payload = json.loads(raw_manifest)
        shard_manifest = EmbeddingShardManifest.model_validate(payload)
        if raw_manifest != _canonical_json_bytes(
            shard_manifest.model_dump(mode="json")
        ):
            return None
        content = npy_path.read_bytes()
        if (
            shard_manifest.build_id != build_id
            or shard_manifest.batch_index != batch.index
            or shard_manifest.start != batch.start
            or shard_manifest.end != batch.end
            or shard_manifest.row_count != batch.end - batch.start
            or shard_manifest.dimension != dimension
            or shard_manifest.byte_count != len(content)
            or shard_manifest.npy_sha256
            != hashlib.sha256(content).hexdigest()
        ):
            return None
        with npy_path.open("rb") as handle:
            values = np.load(handle, allow_pickle=False)
        return _validate_cached_shard(
            values,
            expected_rows=batch.end - batch.start,
            dimension=dimension,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _validate_cached_shard(
    values: object,
    *,
    expected_rows: int,
    dimension: int,
) -> np.ndarray:
    vectors = np.asarray(values)
    if vectors.dtype != np.dtype("float32"):
        raise ValueError("cached embedding shard dtype is invalid")
    if vectors.shape != (expected_rows, dimension):
        raise ValueError("cached embedding shard shape is invalid")
    if not np.isfinite(vectors).all():
        raise ValueError("cached embedding shard has non-finite values")
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms == 0) or not np.allclose(
        norms,
        1.0,
        rtol=1e-5,
        atol=1e-6,
    ):
        raise ValueError("cached embedding shard is not L2 normalized")
    return np.ascontiguousarray(vectors, dtype="float32")


def _normalize_and_validate_shard(
    values: object,
    *,
    expected_rows: int,
    dimension: int,
) -> np.ndarray:
    try:
        vectors = np.asarray(values, dtype="float32")
    except (TypeError, ValueError) as exc:
        raise ValueError("batch embedder returned non-numeric values") from exc
    if vectors.shape != (expected_rows, dimension):
        raise ValueError(
            "batch embedder returned an invalid shape: "
            f"expected {(expected_rows, dimension)}, got {vectors.shape}"
        )
    if not np.isfinite(vectors).all():
        raise ValueError("batch embedder returned non-finite values")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("batch embedder returned a zero vector")
    return np.ascontiguousarray(vectors / norms, dtype="float32")


def _store_shard(
    cache_dir: Path,
    *,
    build_id: str,
    batch: EmbeddingBatch,
    vectors: np.ndarray,
) -> None:
    npy_path, manifest_path = _shard_paths(cache_dir, batch)
    content = _npy_bytes(vectors)
    shard_manifest = EmbeddingShardManifest(
        schema_version="resumable_embedding_shard_v1",
        producer="enterprise_agentic_rag_v2",
        build_id=build_id,
        batch_index=batch.index,
        start=batch.start,
        end=batch.end,
        row_count=batch.end - batch.start,
        dimension=int(vectors.shape[1]),
        dtype="float32",
        normalization="l2",
        npy_sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
    )
    _atomic_write_bytes(npy_path, content)
    _atomic_write_bytes(
        manifest_path,
        _canonical_json_bytes(shard_manifest.model_dump(mode="json")),
    )


def _npy_bytes(vectors: np.ndarray) -> bytes:
    import io

    handle = io.BytesIO()
    np.save(handle, vectors, allow_pickle=False)
    return handle.getvalue()


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "BatchEmbeddingClient",
    "EmbeddingProgress",
    "ResumableBatchEmbedder",
    "ResumableEmbeddingSummary",
]
