from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from threading import get_ident
from typing import Iterator, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.documents import (
    ChunkKind,
    ChunkRecord,
    DocumentRecord,
    ParseResult,
    ParseWarning,
    ParsedSection,
    ParsedTable,
    SourceLocator,
)
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.path_security import absolute_path_has_redirect, stat_is_redirect
from app.security.private_fs import (
    PrivatePathError,
    capture_private_directory_identity,
    harden_held_private_directory,
    harden_private_directory,
    hold_private_directory,
    private_directory_permissions_are_secure,
    private_directory_identity_is_current,
    replace_private_file,
)


_DEFAULT_MAX_ENTRY_BYTES = 16 * 1024 * 1024
_DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.02
_LOCK_FILE = ".cache.lock"
_TEMP_PATTERN = re.compile(r"^\.cache\.tmp-[0-9a-f]{16}$")


class ComputationCacheModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


class ComponentFingerprint(ComputationCacheModel):
    schema_version: Literal["component_fingerprint_v1"] = "component_fingerprint_v1"
    name: str = Field(min_length=1, max_length=128)
    semantic_version: str = Field(min_length=1, max_length=64)
    implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_versions: tuple[str, ...] = Field(default_factory=tuple, max_length=100)

    @field_validator("name", "semantic_version")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("component identifiers must be printable")
        return value

    @field_validator("dependency_versions")
    @classmethod
    def validate_dependencies(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if (
            values != tuple(sorted(values))
            or len(values) != len(set(values))
            or any(
                not value
                or len(value) > 256
                or "=" not in value
                or _has_control_character(value)
                for value in values
            )
        ):
            raise ValueError(
                "dependency versions must be unique canonical name=value strings"
            )
        names = [value.split("=", 1)[0] for value in values]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("dependency names must be non-empty and unique")
        return values


class ParsedContentArtifact(ComputationCacheModel):
    schema_version: Literal["parsed_content_artifact_v1"] = (
        "parsed_content_artifact_v1"
    )
    text: str
    sections: tuple[ParsedSection, ...] = ()
    headings: tuple[str, ...] = ()
    tables: tuple[ParsedTable, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()
    parse_warnings: tuple[ParseWarning, ...] = ()

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        values: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...]:
        keys = [key for key, _ in values]
        if (
            values != tuple(sorted(values))
            or len(keys) != len(set(keys))
            or any(
                not key
                or len(key) > 256
                or len(value) > 4096
                or _has_control_character(key)
                for key, value in values
            )
        ):
            raise ValueError("parsed metadata must use unique canonical keys")
        return values

    @model_validator(mode="after")
    def validate_content(self) -> ParsedContentArtifact:
        if not self.text.strip() and not self.tables and not self.parse_warnings:
            raise ValueError("parsed content artifact is empty")
        return self

    @classmethod
    def from_parse_result(cls, result: ParseResult) -> ParsedContentArtifact:
        return cls(
            text=result.text,
            sections=tuple(result.sections),
            headings=tuple(result.headings),
            tables=tuple(result.tables),
            metadata=tuple(sorted(result.metadata.items())),
            parse_warnings=tuple(result.parse_warnings),
        )

    def to_parse_result(
        self,
        *,
        source_location: str,
        parser: ComponentFingerprint,
    ) -> ParseResult:
        return ParseResult(
            text=self.text,
            sections=list(self.sections),
            headings=list(self.headings),
            tables=list(self.tables),
            metadata=dict(self.metadata),
            source_location=source_location,
            parse_warnings=list(self.parse_warnings),
            parser_name=parser.name,
            parser_version=parser.semantic_version,
        )


class ParsedArtifactKey(ComputationCacheModel):
    schema_version: Literal["parsed_artifact_key_v1"] = "parsed_artifact_key_v1"
    stage: Literal["parsed"] = "parsed"
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_media_type: str = Field(min_length=1, max_length=128)
    parser: ComponentFingerprint

    @field_validator(
        "tenant_id",
        "source_system",
        "source_key",
        "document_id",
        "declared_media_type",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("parsed cache key identifiers must be printable")
        return value


class NormalizedContentArtifact(ComputationCacheModel):
    schema_version: Literal["normalized_content_artifact_v1"] = (
        "normalized_content_artifact_v1"
    )
    title: str = Field(min_length=1, max_length=1024)
    text: str
    sections: tuple[ParsedSection, ...] = ()
    tables: tuple[ParsedTable, ...] = ()
    parse_warnings: tuple[ParseWarning, ...] = ()
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content(self) -> NormalizedContentArtifact:
        if not self.text.strip() and not self.tables:
            raise ValueError("normalized content artifact is empty")
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.normalized_sha256 != expected:
            raise ValueError("normalized content hash does not match text")
        return self


class NormalizedArtifactKey(ComputationCacheModel):
    schema_version: Literal["normalized_artifact_key_v1"] = (
        "normalized_artifact_key_v1"
    )
    stage: Literal["normalized"] = "normalized"
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parsed_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser: ComponentFingerprint
    normalizer: ComponentFingerprint

    @field_validator(
        "tenant_id",
        "source_system",
        "source_key",
        "document_id",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("normalized cache key identifiers must be printable")
        return value


class ChunkLayoutItem(ComputationCacheModel):
    ordinal: int = Field(ge=1)
    chunk_id: str = Field(min_length=1, max_length=512)
    parent_chunk_id: str | None = Field(default=None, max_length=512)
    kind: ChunkKind
    indexable: bool
    text: str = Field(min_length=1)
    section_path: tuple[str, ...] = Field(min_length=1, max_length=100)
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_relationship(self) -> ChunkLayoutItem:
        if self.kind == "child" and self.parent_chunk_id is None:
            raise ValueError("child chunk layout requires parent_chunk_id")
        if self.kind == "parent" and self.indexable:
            raise ValueError("parent chunk layout must not be indexable")
        return self

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class ChunkLayoutArtifact(ComputationCacheModel):
    schema_version: Literal["chunk_layout_artifact_v1"] = (
        "chunk_layout_artifact_v1"
    )
    chunks: tuple[ChunkLayoutItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_layout(self) -> ChunkLayoutArtifact:
        ordinals = [item.ordinal for item in self.chunks]
        identifiers = [item.chunk_id for item in self.chunks]
        if ordinals != list(range(1, len(self.chunks) + 1)):
            raise ValueError("chunk layout ordinals must be contiguous")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("chunk layout identifiers must be unique")
        known = set(identifiers)
        if any(
            item.parent_chunk_id is not None
            and item.parent_chunk_id not in known
            for item in self.chunks
        ):
            raise ValueError("chunk layout parent must exist in the same artifact")
        return self

    @classmethod
    def from_chunk_records(
        cls,
        chunks: list[ChunkRecord],
    ) -> ChunkLayoutArtifact:
        return cls(
            chunks=tuple(
                ChunkLayoutItem(
                    ordinal=ordinal,
                    chunk_id=chunk.chunk_id,
                    parent_chunk_id=chunk.parent_chunk_id,
                    kind=chunk.kind,
                    indexable=chunk.indexable,
                    text=chunk.text,
                    section_path=tuple(chunk.section_path),
                    locator=chunk.locator,
                )
                for ordinal, chunk in enumerate(chunks, start=1)
            )
        )

    def materialize(self, document: DocumentRecord) -> list[ChunkRecord]:
        version = document.document_version
        return [
            ChunkRecord(
                chunk_id=item.chunk_id,
                doc_id=document.doc_id,
                parent_chunk_id=item.parent_chunk_id,
                kind=item.kind,
                indexable=item.indexable,
                text=item.text,
                section_path=list(item.section_path),
                locator=item.locator,
                source_path=document.source_path,
                format=document.format,
                source_type=document.source_type,
                policy_id=document.policy_id,
                department=document.department,
                filed_department=document.filed_department,
                tenant_id=document.tenant_id,
                region=document.region,
                acl_groups=list(document.acl_groups),
                version_id=version.version_id,
                version=version.version,
                status=version.status,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                supersedes_doc_id=version.supersedes_doc_id,
                authority_level=document.authority_level,
                fact_ids=list(document.fact_ids),
                variant=document.variant,
                checksum=document.checksum,
                text_hash=item.text_sha256,
            )
            for item in self.chunks
        ]


class ChunkArtifactKey(ComputationCacheModel):
    schema_version: Literal["chunk_artifact_key_v1"] = "chunk_artifact_key_v1"
    stage: Literal["chunks"] = "chunks"
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser: ComponentFingerprint
    normalizer: ComponentFingerprint
    chunker: ComponentFingerprint
    chunker_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "tenant_id",
        "source_system",
        "source_key",
        "document_id",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("chunk cache key identifiers must be printable")
        return value


class EmbeddingFingerprint(ComputationCacheModel):
    schema_version: Literal["embedding_fingerprint_v1"] = "embedding_fingerprint_v1"
    component: ComponentFingerprint
    backend: str = Field(min_length=1, max_length=128)
    model_identifier: str = Field(min_length=1, max_length=256)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: int = Field(ge=1, le=65536)
    normalization: Literal["l2", "none"]

    @field_validator("backend", "model_identifier")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("embedding identifiers must be printable")
        return value


class EmbeddingArtifactKey(ComputationCacheModel):
    schema_version: Literal["embedding_artifact_key_v1"] = (
        "embedding_artifact_key_v1"
    )
    stage: Literal["embedding"] = "embedding"
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    chunk_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding: EmbeddingFingerprint

    @field_validator(
        "tenant_id",
        "source_system",
        "source_key",
        "document_id",
    )
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if _has_control_character(value):
            raise ValueError("embedding cache key identifiers must be printable")
        return value


class EmbeddingVectorArtifact(ComputationCacheModel):
    schema_version: Literal["embedding_vector_artifact_v1"] = (
        "embedding_vector_artifact_v1"
    )
    vector: tuple[float, ...] = Field(min_length=1, max_length=65536)

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in values):
            raise ValueError("embedding vector values must be finite")
        if not any(value != 0.0 for value in values):
            raise ValueError("embedding vector must be non-zero")
        return values


class CacheWriteResult(ComputationCacheModel):
    status: Literal["STORED", "REUSED"]
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    serialization_seconds: float = Field(ge=0.0)


class ParsedCacheEnvelope(ComputationCacheModel):
    schema_version: Literal["computation_cache_envelope_v1"] = (
        "computation_cache_envelope_v1"
    )
    stage: Literal["parsed"] = "parsed"
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key: ParsedArtifactKey
    payload: ParsedContentArtifact

    @model_validator(mode="after")
    def validate_hashes(self) -> ParsedCacheEnvelope:
        if cache_key_sha256(self.key) != self.key_sha256:
            raise ValueError("cache envelope key checksum mismatch")
        if cache_payload_sha256(self.payload) != self.payload_sha256:
            raise ValueError("cache envelope payload checksum mismatch")
        return self


class NormalizedCacheEnvelope(ComputationCacheModel):
    schema_version: Literal["computation_cache_envelope_v1"] = (
        "computation_cache_envelope_v1"
    )
    stage: Literal["normalized"] = "normalized"
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key: NormalizedArtifactKey
    payload: NormalizedContentArtifact

    @model_validator(mode="after")
    def validate_hashes(self) -> NormalizedCacheEnvelope:
        if cache_key_sha256(self.key) != self.key_sha256:
            raise ValueError("cache envelope key checksum mismatch")
        if cache_payload_sha256(self.payload) != self.payload_sha256:
            raise ValueError("cache envelope payload checksum mismatch")
        if self.key.expected_normalized_sha256 != self.payload.normalized_sha256:
            raise ValueError("normalized cache payload does not match expected hash")
        return self


class ChunkCacheEnvelope(ComputationCacheModel):
    schema_version: Literal["computation_cache_envelope_v1"] = (
        "computation_cache_envelope_v1"
    )
    stage: Literal["chunks"] = "chunks"
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key: ChunkArtifactKey
    payload: ChunkLayoutArtifact

    @model_validator(mode="after")
    def validate_hashes(self) -> ChunkCacheEnvelope:
        if cache_key_sha256(self.key) != self.key_sha256:
            raise ValueError("cache envelope key checksum mismatch")
        if cache_payload_sha256(self.payload) != self.payload_sha256:
            raise ValueError("cache envelope payload checksum mismatch")
        return self


class EmbeddingCacheEnvelope(ComputationCacheModel):
    schema_version: Literal["computation_cache_envelope_v1"] = (
        "computation_cache_envelope_v1"
    )
    stage: Literal["embedding"] = "embedding"
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key: EmbeddingArtifactKey
    payload: EmbeddingVectorArtifact

    @model_validator(mode="after")
    def validate_hashes_and_shape(self) -> EmbeddingCacheEnvelope:
        if cache_key_sha256(self.key) != self.key_sha256:
            raise ValueError("cache envelope key checksum mismatch")
        if cache_payload_sha256(self.payload) != self.payload_sha256:
            raise ValueError("cache envelope payload checksum mismatch")
        if len(self.payload.vector) != self.key.embedding.dimension:
            raise ValueError("embedding cache payload dimension mismatch")
        if self.key.embedding.normalization == "l2":
            norm = math.sqrt(sum(value * value for value in self.payload.vector))
            if not math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("l2 embedding cache payload is not normalized")
        return self


class ComputationCacheError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def __reduce__(
        self,
    ) -> tuple[type[ComputationCacheError], tuple[str, str]]:
        return (type(self), (self.code, self.message))


CacheModelT = TypeVar("CacheModelT", bound=BaseModel)


def _validated_request(
    value: BaseModel,
    model: type[CacheModelT],
) -> CacheModelT:
    try:
        return model.model_validate(value.model_dump(mode="json"))
    except Exception:
        raise ComputationCacheError(
            "cache_request_invalid",
            "computation cache request failed strict validation",
        ) from None


def _canonical_json_bytes(value: BaseModel | object) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def cache_key_sha256(
    key: (
        ParsedArtifactKey
        | NormalizedArtifactKey
        | ChunkArtifactKey
        | EmbeddingArtifactKey
    ),
) -> str:
    return hashlib.sha256(_canonical_json_bytes(key)).hexdigest()


def cache_payload_sha256(
    payload: (
        ParsedContentArtifact
        | NormalizedContentArtifact
        | ChunkLayoutArtifact
        | EmbeddingVectorArtifact
    ),
) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def canonical_parsed_cache_envelope_bytes(
    envelope: ParsedCacheEnvelope,
) -> bytes:
    validated = ParsedCacheEnvelope.model_validate(envelope.model_dump(mode="json"))
    return _canonical_json_bytes(validated)


def canonical_normalized_cache_envelope_bytes(
    envelope: NormalizedCacheEnvelope,
) -> bytes:
    validated = NormalizedCacheEnvelope.model_validate(
        envelope.model_dump(mode="json")
    )
    return _canonical_json_bytes(validated)


def canonical_chunk_cache_envelope_bytes(
    envelope: ChunkCacheEnvelope,
) -> bytes:
    validated = ChunkCacheEnvelope.model_validate(envelope.model_dump(mode="json"))
    return _canonical_json_bytes(validated)


def canonical_embedding_cache_envelope_bytes(
    envelope: EmbeddingCacheEnvelope,
) -> bytes:
    validated = EmbeddingCacheEnvelope.model_validate(
        envelope.model_dump(mode="json")
    )
    return _canonical_json_bytes(validated)


def chunker_config_sha256(config: ChunkerConfig) -> str:
    validated = ChunkerConfig.model_validate(config.model_dump(mode="json"))
    return hashlib.sha256(_canonical_json_bytes(validated)).hexdigest()


def pipeline_fingerprint_sha256(
    *,
    parser: ComponentFingerprint,
    normalizer: ComponentFingerprint,
    chunker: ComponentFingerprint,
    chunker_config: ChunkerConfig,
) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "schema_version": "content_pipeline_fingerprint_v1",
                "parser": parser.model_dump(mode="json"),
                "normalizer": normalizer.model_dump(mode="json"),
                "chunker": chunker.model_dump(mode="json"),
                "chunker_config": ChunkerConfig.model_validate(
                    chunker_config.model_dump(mode="json")
                ).model_dump(mode="json"),
            }
        )
    ).hexdigest()


class PersistentComputationCache:
    def __init__(
        self,
        root: Path,
        *,
        max_entry_bytes: int = _DEFAULT_MAX_ENTRY_BYTES,
        lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        candidate = Path(root)
        if not candidate.is_absolute():
            raise ValueError("computation cache root must be absolute")
        if max_entry_bytes < 1:
            raise ValueError("max_entry_bytes must be positive")
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self.root = candidate.absolute()
        self.max_entry_bytes = max_entry_bytes
        self.lock_timeout_seconds = lock_timeout_seconds
        self._transaction_owner: int | None = None
        self._transaction_depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        owner = get_ident()
        if self._transaction_owner is not None:
            if self._transaction_owner != owner:
                raise ComputationCacheError(
                    "cache_transaction_thread_conflict",
                    "computation cache transaction belongs to another thread",
                )
            self._transaction_depth += 1
            try:
                yield
            finally:
                self._transaction_depth -= 1
            return

        with self._locked():
            self._transaction_owner = owner
            self._transaction_depth = 1
            try:
                yield
            finally:
                try:
                    if not private_directory_permissions_are_secure(
                        self.root
                    ):
                        harden_private_directory(self.root)
                    _sync_cache_directory(self.root)
                except (OSError, PrivatePathError) as exc:
                    raise ComputationCacheError(
                        "cache_transaction_finalize_failed",
                        "computation cache transaction could not be hardened",
                    ) from exc
                finally:
                    self._transaction_depth = 0
                    self._transaction_owner = None

    def entry_path(
        self,
        key: (
            ParsedArtifactKey
            | NormalizedArtifactKey
            | ChunkArtifactKey
            | EmbeddingArtifactKey
        ),
    ) -> Path:
        return self.root / f"{key.stage}-{cache_key_sha256(key)}.json"

    def _read_entry_bytes(
        self,
        key: (
            ParsedArtifactKey
            | NormalizedArtifactKey
            | ChunkArtifactKey
            | EmbeddingArtifactKey
        ),
    ) -> bytes | None:
        with self._locked():
            path = self.entry_path(key)
            if _lstat_optional(path) is None:
                return None
            return _read_safe_regular_file(
                path,
                byte_limit=self.max_entry_bytes,
            )

    def load_parsed(
        self,
        key: ParsedArtifactKey,
    ) -> ParsedContentArtifact | None:
        key = _validated_request(key, ParsedArtifactKey)
        content = self._read_entry_bytes(key)
        if content is None:
            return None
        try:
            envelope = ParsedCacheEnvelope.model_validate_json(content)
        except Exception:
            raise ComputationCacheError(
                "cache_entry_invalid",
                "parsed cache entry failed schema or checksum validation",
            ) from None
        canonical = canonical_parsed_cache_envelope_bytes(envelope)
        if canonical != content:
            raise ComputationCacheError(
                "cache_entry_noncanonical",
                "parsed cache entry is not canonical",
            )
        if envelope.key != key:
            raise ComputationCacheError(
                "cache_key_mismatch",
                "parsed cache entry does not match the requested key",
            )
        return envelope.payload

    def load_embedding(
        self,
        key: EmbeddingArtifactKey,
    ) -> EmbeddingVectorArtifact | None:
        key = _validated_request(key, EmbeddingArtifactKey)
        content = self._read_entry_bytes(key)
        if content is None:
            return None
        try:
            envelope = EmbeddingCacheEnvelope.model_validate_json(content)
        except Exception:
            raise ComputationCacheError(
                "cache_entry_invalid",
                "embedding cache entry failed schema or checksum validation",
            ) from None
        if canonical_embedding_cache_envelope_bytes(envelope) != content:
            raise ComputationCacheError(
                "cache_entry_noncanonical",
                "embedding cache entry is not canonical",
            )
        if envelope.key != key:
            raise ComputationCacheError(
                "cache_key_mismatch",
                "embedding cache entry does not match the requested key",
            )
        return envelope.payload

    def load_chunks(
        self,
        key: ChunkArtifactKey,
    ) -> ChunkLayoutArtifact | None:
        key = _validated_request(key, ChunkArtifactKey)
        content = self._read_entry_bytes(key)
        if content is None:
            return None
        try:
            envelope = ChunkCacheEnvelope.model_validate_json(content)
        except Exception:
            raise ComputationCacheError(
                "cache_entry_invalid",
                "chunk cache entry failed schema or checksum validation",
            ) from None
        if canonical_chunk_cache_envelope_bytes(envelope) != content:
            raise ComputationCacheError(
                "cache_entry_noncanonical",
                "chunk cache entry is not canonical",
            )
        if envelope.key != key:
            raise ComputationCacheError(
                "cache_key_mismatch",
                "chunk cache entry does not match the requested key",
            )
        return envelope.payload

    def load_normalized(
        self,
        key: NormalizedArtifactKey,
    ) -> NormalizedContentArtifact | None:
        key = _validated_request(key, NormalizedArtifactKey)
        content = self._read_entry_bytes(key)
        if content is None:
            return None
        try:
            envelope = NormalizedCacheEnvelope.model_validate_json(content)
        except Exception:
            raise ComputationCacheError(
                "cache_entry_invalid",
                "normalized cache entry failed schema or checksum validation",
            ) from None
        if canonical_normalized_cache_envelope_bytes(envelope) != content:
            raise ComputationCacheError(
                "cache_entry_noncanonical",
                "normalized cache entry is not canonical",
            )
        if envelope.key != key:
            raise ComputationCacheError(
                "cache_key_mismatch",
                "normalized cache entry does not match the requested key",
            )
        return envelope.payload

    def store_parsed(
        self,
        key: ParsedArtifactKey,
        payload: ParsedContentArtifact,
    ) -> CacheWriteResult:
        key = _validated_request(key, ParsedArtifactKey)
        payload = _validated_request(payload, ParsedContentArtifact)
        serialization_started = time.perf_counter()
        envelope = ParsedCacheEnvelope(
            key_sha256=cache_key_sha256(key),
            payload_sha256=cache_payload_sha256(payload),
            key=key,
            payload=payload,
        )
        content = canonical_parsed_cache_envelope_bytes(envelope)
        serialization_seconds = time.perf_counter() - serialization_started
        return self._store_envelope(
            key=key,
            content=content,
            envelope=envelope,
            serialization_seconds=serialization_seconds,
        )

    def store_normalized(
        self,
        key: NormalizedArtifactKey,
        payload: NormalizedContentArtifact,
    ) -> CacheWriteResult:
        key = _validated_request(key, NormalizedArtifactKey)
        payload = _validated_request(payload, NormalizedContentArtifact)
        serialization_started = time.perf_counter()
        envelope = NormalizedCacheEnvelope(
            key_sha256=cache_key_sha256(key),
            payload_sha256=cache_payload_sha256(payload),
            key=key,
            payload=payload,
        )
        content = canonical_normalized_cache_envelope_bytes(envelope)
        serialization_seconds = time.perf_counter() - serialization_started
        return self._store_envelope(
            key=key,
            content=content,
            envelope=envelope,
            serialization_seconds=serialization_seconds,
        )

    def store_chunks(
        self,
        key: ChunkArtifactKey,
        payload: ChunkLayoutArtifact,
    ) -> CacheWriteResult:
        key = _validated_request(key, ChunkArtifactKey)
        payload = _validated_request(payload, ChunkLayoutArtifact)
        serialization_started = time.perf_counter()
        envelope = ChunkCacheEnvelope(
            key_sha256=cache_key_sha256(key),
            payload_sha256=cache_payload_sha256(payload),
            key=key,
            payload=payload,
        )
        content = canonical_chunk_cache_envelope_bytes(envelope)
        serialization_seconds = time.perf_counter() - serialization_started
        return self._store_envelope(
            key=key,
            content=content,
            envelope=envelope,
            serialization_seconds=serialization_seconds,
        )

    def store_embedding(
        self,
        key: EmbeddingArtifactKey,
        payload: EmbeddingVectorArtifact,
    ) -> CacheWriteResult:
        key = _validated_request(key, EmbeddingArtifactKey)
        payload = _validated_request(payload, EmbeddingVectorArtifact)
        serialization_started = time.perf_counter()
        envelope = EmbeddingCacheEnvelope(
            key_sha256=cache_key_sha256(key),
            payload_sha256=cache_payload_sha256(payload),
            key=key,
            payload=payload,
        )
        content = canonical_embedding_cache_envelope_bytes(envelope)
        serialization_seconds = time.perf_counter() - serialization_started
        return self._store_envelope(
            key=key,
            content=content,
            envelope=envelope,
            serialization_seconds=serialization_seconds,
        )

    def _store_envelope(
        self,
        *,
        key: (
            ParsedArtifactKey
            | NormalizedArtifactKey
            | ChunkArtifactKey
            | EmbeddingArtifactKey
        ),
        content: bytes,
        envelope: (
            ParsedCacheEnvelope
            | NormalizedCacheEnvelope
            | ChunkCacheEnvelope
            | EmbeddingCacheEnvelope
        ),
        serialization_seconds: float,
    ) -> CacheWriteResult:
        with self._locked():
            if len(content) > self.max_entry_bytes:
                raise ComputationCacheError(
                    "cache_entry_too_large",
                    f"{key.stage} cache entry exceeds the configured byte limit",
                )
            target = self.entry_path(key)
            if _lstat_optional(target) is not None:
                existing_content = _read_safe_regular_file(
                    target,
                    byte_limit=self.max_entry_bytes,
                )
                if existing_content != content:
                    raise ComputationCacheError(
                        "cache_key_collision",
                        f"{key.stage} cache key already contains different content",
                    )
                return CacheWriteResult(
                    status="REUSED",
                    key_sha256=envelope.key_sha256,
                    payload_sha256=envelope.payload_sha256,
                    serialization_seconds=serialization_seconds,
                )
            self._publish_content(target=target, content=content, stage=key.stage)
            if (
                _read_safe_regular_file(
                    target,
                    byte_limit=self.max_entry_bytes,
                )
                != content
            ):
                raise ComputationCacheError(
                    "cache_publish_unconfirmed",
                    f"{key.stage} cache publication could not be confirmed",
                )
            return CacheWriteResult(
                status="STORED",
                key_sha256=envelope.key_sha256,
                payload_sha256=envelope.payload_sha256,
                serialization_seconds=serialization_seconds,
            )

    def _publish_content(
        self,
        *,
        target: Path,
        content: bytes,
        stage: str,
    ) -> None:
        temporary = self.root / f".cache.tmp-{secrets.token_hex(8)}"
        descriptor: int | None = None
        replaced = False
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            replace_private_file(temporary, target)
            replaced = True
            if self._transaction_owner is None:
                harden_private_directory(self.root)
            _sync_cache_directory(self.root)
        except (OSError, PrivatePathError) as exc:
            raise ComputationCacheError(
                (
                    "cache_commit_outcome_unknown"
                    if replaced
                    else "cache_publish_failed"
                ),
                (
                    f"{stage} cache publication requires retry confirmation"
                    if replaced
                    else f"{stage} cache entry could not be published"
                ),
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @contextmanager
    def _held_root(self) -> Iterator[None]:
        try:
            with hold_private_directory(self.root) as held:
                expected = capture_private_directory_identity(self.root, held)
                if not private_directory_permissions_are_secure(self.root):
                    harden_held_private_directory(
                        self.root,
                        held,
                        expected_identity=expected,
                    )
                try:
                    yield
                finally:
                    if not private_directory_identity_is_current(
                        self.root,
                        held,
                        expected,
                    ):
                        raise PrivatePathError(
                            "computation cache root changed during operation"
                        )
        except PrivatePathError as exc:
            raise ComputationCacheError(
                "cache_root_changed",
                "computation cache root identity changed during operation",
            ) from exc

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self._transaction_owner is not None:
            if self._transaction_owner != get_ident():
                raise ComputationCacheError(
                    "cache_transaction_thread_conflict",
                    "computation cache transaction belongs to another thread",
                )
            yield
            return
        self._prepare_root()
        lock_path = self.root / _LOCK_FILE
        descriptor = _open_safe_lock_file(lock_path)
        acquired = False
        try:
            _lock_descriptor(
                descriptor,
                timeout_seconds=self.lock_timeout_seconds,
            )
            acquired = True
            _initialize_open_lock_file(descriptor)
            self._validate_root_structure()
            with self._held_root():
                _validate_open_lock_identity(descriptor, lock_path)
                self._cleanup_orphan_temps()
                yield
        except TimeoutError:
            raise ComputationCacheError(
                "cache_lock_timeout",
                "computation cache lock acquisition timed out",
            ) from None
        finally:
            try:
                if acquired:
                    _unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)

    def _cleanup_orphan_temps(self) -> None:
        for candidate in self.root.iterdir():
            if not _TEMP_PATTERN.fullmatch(candidate.name):
                continue
            metadata = candidate.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat_is_redirect(metadata)
                or metadata.st_nlink != 1
            ):
                raise ComputationCacheError(
                    "cache_orphan_unsafe",
                    "owned cache temporary entry is unsafe",
                )
            candidate.unlink()

    def _prepare_root(self) -> None:
        try:
            if absolute_path_has_redirect(self.root):
                raise PrivatePathError("cache root contains a redirected path")
            self.root.mkdir(parents=True, exist_ok=True)
            metadata = self.root.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat_is_redirect(metadata)
            ):
                raise PrivatePathError("cache root is not a regular directory")
        except (OSError, PrivatePathError) as exc:
            raise ComputationCacheError(
                "cache_root_unsafe",
                "computation cache root is unsafe",
            ) from exc

    def _validate_root_structure(self) -> None:
        try:
            # Serialize the scan with cache publication so owned temp files cannot
            # disappear between directory enumeration and metadata validation.
            _validate_cache_root_structure(self.root)
        except (OSError, PrivatePathError) as exc:
            raise ComputationCacheError(
                "cache_root_unsafe",
                "computation cache root is unsafe",
            ) from exc


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _validate_cache_root_structure(root: Path) -> None:
    try:
        entries = tuple(root.iterdir())
        metadata = tuple(entry.lstat() for entry in entries)
    except OSError as exc:
        raise PrivatePathError(
            "computation cache root contents are unavailable"
        ) from exc
    if any(
        not stat.S_ISREG(item.st_mode)
        or stat_is_redirect(item)
        or item.st_nlink != 1
        for item in metadata
    ):
        raise PrivatePathError(
            "computation cache root contains an unsafe entry"
        )


def _read_safe_regular_file(path: Path, *, byte_limit: int) -> bytes:
    metadata = _lstat_optional(path)
    if metadata is None:
        raise FileNotFoundError(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat_is_redirect(metadata)
        or metadata.st_nlink != 1
        or metadata.st_size > byte_limit
    ):
        raise ComputationCacheError(
            "cache_entry_unsafe",
            "cache entry is not a bounded single-link regular file",
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ComputationCacheError(
            "cache_entry_unsafe",
            "cache entry could not be opened safely",
        ) from exc
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat_is_redirect(current)
            or opened.st_nlink != 1
            or opened.st_size > byte_limit
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ComputationCacheError(
                "cache_entry_unsafe",
                "cache entry changed during validation",
            )
        content = b""
        while len(content) <= byte_limit:
            block = os.read(descriptor, min(1024 * 1024, byte_limit + 1 - len(content)))
            if not block:
                break
            content += block
        if len(content) > byte_limit or len(content) != opened.st_size:
            raise ComputationCacheError(
                "cache_entry_unsafe",
                "cache entry exceeded its validated byte size",
            )
        return content
    finally:
        os.close(descriptor)


def _open_safe_lock_file(path: Path) -> int:
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat_is_redirect(current)
            or metadata.st_nlink != 1
            or (metadata.st_dev, metadata.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            raise ComputationCacheError(
                "cache_lock_unsafe",
                "computation cache lock file is unsafe",
            )
        return descriptor
    except Exception:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


def _initialize_open_lock_file(descriptor: int) -> None:
    if os.fstat(descriptor).st_size != 0:
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, b"\0")
    os.fsync(descriptor)


def _validate_open_lock_identity(descriptor: int, path: Path) -> None:
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
    except OSError as exc:
        raise ComputationCacheError(
            "cache_lock_unsafe",
            "computation cache lock identity is unavailable",
        ) from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or stat_is_redirect(current)
        or opened.st_nlink != 1
        or current.st_nlink != 1
        or (opened.st_dev, opened.st_ino)
        != (current.st_dev, current.st_ino)
    ):
        raise ComputationCacheError(
            "cache_lock_unsafe",
            "computation cache lock identity changed before use",
        )


def _lock_descriptor(descriptor: int, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError
            time.sleep(_LOCK_POLL_SECONDS)


def _unlock_descriptor(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _sync_cache_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CacheWriteResult",
    "ChunkArtifactKey",
    "ChunkLayoutArtifact",
    "ChunkLayoutItem",
    "ComponentFingerprint",
    "ComputationCacheError",
    "EmbeddingArtifactKey",
    "EmbeddingFingerprint",
    "EmbeddingVectorArtifact",
    "NormalizedArtifactKey",
    "NormalizedContentArtifact",
    "ParsedArtifactKey",
    "ParsedContentArtifact",
    "PersistentComputationCache",
    "cache_key_sha256",
    "cache_payload_sha256",
    "canonical_chunk_cache_envelope_bytes",
    "canonical_embedding_cache_envelope_bytes",
    "canonical_normalized_cache_envelope_bytes",
    "canonical_parsed_cache_envelope_bytes",
    "chunker_config_sha256",
    "pipeline_fingerprint_sha256",
]
