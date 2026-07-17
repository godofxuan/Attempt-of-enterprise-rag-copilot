from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ArtifactFile(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact path must be a confined relative path")
        return path.as_posix()


class EmbeddingSpec(StrictModel):
    model: str = Field(min_length=1)
    dimension: int = Field(ge=1)
    normalization: Literal["l2", "none"]


class FaissSpec(StrictModel):
    index_type: str = Field(min_length=1)
    metric: str = Field(min_length=1)


class BM25Spec(StrictModel):
    tokenizer: str = Field(min_length=1)
    parameters: dict[str, float | int | str]


class IndexManifest(StrictModel):
    schema_version: Literal["enterprise_index_manifest_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    index_version: str = Field(min_length=1)
    run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    profile_id: str = Field(min_length=1)
    corpus_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding: EmbeddingSpec
    faiss: FaissSpec
    bm25: BM25Spec
    chunker_config: dict[str, int | str]
    parser_versions: dict[str, str]
    source_document_count: int = Field(ge=0)
    canonical_document_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)
    parent_chunk_count: int = Field(ge=0)
    table_chunk_count: int = Field(ge=0)
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    artifacts: list[ArtifactFile] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> IndexManifest:
        for name, value in (
            ("started_at", self.started_at),
            ("finished_at", self.finished_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not be earlier than started_at")
        if self.canonical_document_count > self.source_document_count:
            raise ValueError("canonical_document_count exceeds source count")
        if self.duplicate_count != (
            self.source_document_count - self.canonical_document_count
        ):
            raise ValueError("duplicate_count does not match document counts")
        if self.indexed_chunk_count > self.chunk_count:
            raise ValueError("indexed_chunk_count exceeds chunk_count")
        if self.parent_chunk_count > self.chunk_count:
            raise ValueError("parent_chunk_count exceeds chunk_count")
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be unique")
        return self


def serialize_index_manifest(manifest: IndexManifest) -> bytes:
    payload = manifest.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def load_index_manifest(path: Path) -> IndexManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return IndexManifest.model_validate(payload)
