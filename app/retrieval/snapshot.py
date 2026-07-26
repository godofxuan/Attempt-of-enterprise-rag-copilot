from __future__ import annotations

import json
import pickle
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from app.domain.documents import ChunkRecord, DocumentRecord
from app.indexing.store import LoadedIndexVersion, load_index_version


class _EmptyBM25:
    corpus_size = 0

    def get_scores(self, query_tokens: list[str]) -> np.ndarray:
        del query_tokens
        return np.zeros(0, dtype="float64")


@dataclass(frozen=True)
class V2IndexSnapshot:
    version: LoadedIndexVersion
    faiss_index: faiss.Index
    bm25: BM25Okapi | _EmptyBM25
    bm25_tokens: tuple[tuple[str, ...], ...]
    chunks: tuple[ChunkRecord, ...]
    parents_by_id: Mapping[str, ChunkRecord]
    documents_by_id: Mapping[str, DocumentRecord]
    chunk_index_by_id: Mapping[str, int]
    all_chunks_by_id: Mapping[str, ChunkRecord]

    @classmethod
    def load(
        cls,
        root: Path,
        run_id: str | None = None,
    ) -> V2IndexSnapshot:
        version = load_index_version(Path(root), run_id)
        manifest = version.manifest
        _validate_manifest_contract(version)
        path = version.path

        chunks = tuple(
            ChunkRecord.model_validate(item)
            for item in _load_json_array(path / "chunks.json", "chunks")
        )
        parents = tuple(
            ChunkRecord.model_validate(item)
            for item in _load_json_array(path / "parents.json", "parents")
        )
        documents = tuple(
            DocumentRecord.model_validate(item)
            for item in _load_json_array(path / "documents.json", "documents")
        )

        with (path / "bm25_tokens.pkl").open("rb") as handle:
            raw_tokens = pickle.load(handle)
        bm25_tokens = _validate_bm25_tokens(
            raw_tokens,
            expected_count=manifest.indexed_chunk_count,
        )
        bm25 = (
            BM25Okapi([list(tokens) for tokens in bm25_tokens])
            if bm25_tokens
            else _EmptyBM25()
        )
        faiss_index = faiss.deserialize_index(
            np.frombuffer((path / "faiss.index").read_bytes(), dtype=np.uint8).copy()
        )

        _validate_artifact_models(
            version=version,
            chunks=chunks,
            parents=parents,
            documents=documents,
            faiss_index=faiss_index,
        )

        parent_map = _unique_map(parents, "chunk_id", "parent chunk IDs")
        document_map = _unique_map(documents, "doc_id", "document IDs")
        chunk_index = _unique_index(chunks)
        all_chunks = {**parent_map, **{chunk.chunk_id: chunk for chunk in chunks}}
        if len(all_chunks) != len(parent_map) + len(chunks):
            raise ValueError("indexed and parent chunk IDs must not collide")
        for chunk in chunks:
            if chunk.doc_id not in document_map:
                raise ValueError(
                    f"chunk references missing document: {chunk.chunk_id}"
                )
            if chunk.kind == "child" and chunk.parent_chunk_id not in parent_map:
                raise ValueError(
                    f"child references missing parent: {chunk.chunk_id}"
                )

        return cls(
            version=version,
            faiss_index=faiss_index,
            bm25=bm25,
            bm25_tokens=bm25_tokens,
            chunks=chunks,
            parents_by_id=MappingProxyType(parent_map),
            documents_by_id=MappingProxyType(document_map),
            chunk_index_by_id=MappingProxyType(chunk_index),
            all_chunks_by_id=MappingProxyType(all_chunks),
        )


def _validate_manifest_contract(version: LoadedIndexVersion) -> None:
    manifest = version.manifest
    if manifest.faiss.index_type != "IndexFlatIP":
        raise ValueError(
            f"unsupported FAISS index type: {manifest.faiss.index_type}"
        )
    if manifest.faiss.metric != "inner_product":
        raise ValueError(f"unsupported FAISS metric: {manifest.faiss.metric}")
    if manifest.embedding.normalization != "l2":
        raise ValueError(
            f"unsupported embedding normalization: {manifest.embedding.normalization}"
        )
    if manifest.bm25.tokenizer != "jieba":
        raise ValueError(f"unsupported BM25 tokenizer: {manifest.bm25.tokenizer}")


def _load_json_array(path: Path, label: str) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{label} artifact must contain a JSON array")
    return payload


def _validate_bm25_tokens(
    payload,
    *,
    expected_count: int,
) -> tuple[tuple[str, ...], ...]:
    if not isinstance(payload, list) or len(payload) != expected_count:
        raise ValueError("BM25 token corpus count does not match manifest")
    result: list[tuple[str, ...]] = []
    for row in payload:
        if (
            not isinstance(row, list)
            or not row
            or any(not isinstance(token, str) or not token for token in row)
        ):
            raise ValueError("BM25 token corpus contains an invalid row")
        result.append(tuple(row))
    return tuple(result)


def _validate_artifact_models(
    *,
    version: LoadedIndexVersion,
    chunks: tuple[ChunkRecord, ...],
    parents: tuple[ChunkRecord, ...],
    documents: tuple[DocumentRecord, ...],
    faiss_index: faiss.Index,
) -> None:
    manifest = version.manifest
    if type(faiss_index).__name__ != manifest.faiss.index_type:
        raise ValueError("on-disk FAISS index type does not match manifest")
    if faiss_index.ntotal != len(chunks):
        raise ValueError("FAISS rows do not match indexed chunks")
    if faiss_index.d != manifest.embedding.dimension:
        raise ValueError("FAISS dimension does not match embedding manifest")
    if len(chunks) != manifest.indexed_chunk_count:
        raise ValueError("indexed chunk models do not match manifest")
    if len(parents) != manifest.chunk_count - manifest.indexed_chunk_count:
        raise ValueError("parent chunk models do not match manifest")
    if len(documents) != manifest.canonical_document_count:
        raise ValueError("document models do not match manifest")
    if any(not chunk.indexable for chunk in chunks):
        raise ValueError("chunks.json contains a non-indexable chunk")
    if any(parent.indexable or parent.kind != "parent" for parent in parents):
        raise ValueError("parents.json contains an invalid parent chunk")


def _unique_map(items, key_name: str, label: str) -> dict:
    result = {getattr(item, key_name): item for item in items}
    if len(result) != len(items):
        raise ValueError(f"{label} must be unique")
    return result


def _unique_index(chunks: tuple[ChunkRecord, ...]) -> dict[str, int]:
    result = {chunk.chunk_id: index for index, chunk in enumerate(chunks)}
    if len(result) != len(chunks):
        raise ValueError("indexed chunk IDs must be unique")
    return result


__all__ = ["V2IndexSnapshot"]
