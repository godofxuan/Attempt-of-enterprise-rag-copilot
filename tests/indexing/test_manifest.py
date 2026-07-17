from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.indexing.manifest import (
    ArtifactFile,
    BM25Spec,
    EmbeddingSpec,
    FaissSpec,
    IndexManifest,
)


START = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def manifest(**updates) -> IndexManifest:
    values = {
        "schema_version": "enterprise_index_manifest_v1",
        "producer": "enterprise_agentic_rag_v2",
        "index_version": "v2",
        "run_id": "test-run",
        "profile_id": "demo",
        "corpus_manifest_hash": "a" * 64,
        "embedding": EmbeddingSpec(
            model="fake-4d",
            dimension=4,
            normalization="l2",
        ),
        "faiss": FaissSpec(index_type="IndexFlatIP", metric="inner_product"),
        "bm25": BM25Spec(tokenizer="jieba", parameters={"k1": 1.5, "b": 0.75}),
        "chunker_config": {
            "mode": "fixed",
            "chunk_size": 500,
            "overlap": 80,
            "parent_size": 1000,
            "child_size": 250,
            "table_rows_per_chunk": 5,
        },
        "parser_versions": {"markdown": "1.0"},
        "source_document_count": 72,
        "canonical_document_count": 64,
        "duplicate_count": 8,
        "chunk_count": 64,
        "indexed_chunk_count": 64,
        "parent_chunk_count": 0,
        "table_chunk_count": 0,
        "started_at": START,
        "finished_at": START + timedelta(seconds=2),
        "duration_ms": 2000,
        "artifacts": [
            ArtifactFile(
                path="faiss.index",
                sha256="b" * 64,
                byte_count=100,
            )
        ],
    }
    values.update(updates)
    return IndexManifest(**values)


def test_manifest_accepts_complete_provenance() -> None:
    value = manifest()

    assert value.embedding.dimension == 4
    assert value.indexed_chunk_count == 64


def test_manifest_rejects_finished_time_before_start() -> None:
    with pytest.raises(ValidationError, match="finished_at"):
        manifest(finished_at=START - timedelta(seconds=1))


def test_manifest_rejects_impossible_counts() -> None:
    with pytest.raises(ValidationError, match="indexed_chunk_count"):
        manifest(chunk_count=3, indexed_chunk_count=4)


def test_manifest_rejects_duplicate_artifact_paths() -> None:
    artifact = ArtifactFile(path="faiss.index", sha256="b" * 64, byte_count=100)

    with pytest.raises(ValidationError, match="artifact paths"):
        manifest(artifacts=[artifact, artifact])
