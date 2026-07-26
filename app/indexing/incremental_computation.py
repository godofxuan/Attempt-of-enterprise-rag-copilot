from __future__ import annotations

import hashlib
import json
import math
import time
from contextlib import nullcontext
from typing import Callable, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.documents import ChunkRecord, DocumentRecord
from app.indexing.change_plan import (
    ChangePlan,
    ChangePlanError,
    build_change_plan,
)
from app.indexing.computation_cache import (
    ChunkArtifactKey,
    ChunkLayoutArtifact,
    ComponentFingerprint,
    EmbeddingArtifactKey,
    EmbeddingFingerprint,
    EmbeddingVectorArtifact,
    NormalizedArtifactKey,
    NormalizedContentArtifact,
    ParsedArtifactKey,
    ParsedContentArtifact,
    PersistentComputationCache,
    cache_key_sha256,
    cache_payload_sha256,
    chunker_config_sha256,
    pipeline_fingerprint_sha256,
)
from app.ingestion.chunking import ChunkerConfig, chunk_document
from app.ingestion.revision_catalog import (
    DocumentRevision,
    RevisionCatalogSnapshot,
    empty_revision_catalog_snapshot,
    revision_catalog_sha256,
)
from app.ingestion.versions import govern_documents


EmbedText = Callable[[str], list[float]]
ComputationFailurePoint = Literal[
    "parser",
    "normalizer",
    "chunker",
    "embedding",
    "cache_read",
    "cache_write",
]
ComputationCheckpoint = Callable[[ComputationFailurePoint], None]


class IncrementalComputationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class PipelineConfiguration(IncrementalComputationModel):
    schema_version: Literal["pipeline_configuration_v1"] = (
        "pipeline_configuration_v1"
    )
    materializer: ComponentFingerprint
    governance: ComponentFingerprint
    normalizer: ComponentFingerprint
    chunker: ComponentFingerprint
    chunker_config: ChunkerConfig
    embedding: EmbeddingFingerprint


class CacheStatistics(IncrementalComputationModel):
    parsed_hits: int = Field(ge=0)
    parsed_misses: int = Field(ge=0)
    normalized_hits: int = Field(ge=0)
    normalized_misses: int = Field(ge=0)
    chunk_hits: int = Field(ge=0)
    chunk_misses: int = Field(ge=0)
    embedding_hits: int = Field(ge=0)
    embedding_misses: int = Field(ge=0)


class ComputationMeasurements(IncrementalComputationModel):
    parse_calls: int = Field(ge=0)
    normalize_calls: int = Field(ge=0)
    chunk_calls: int = Field(ge=0)
    embedding_calls: int = Field(ge=0)
    artifact_serialization_seconds: float = Field(ge=0.0)
    total_wall_seconds: float = Field(ge=0.0)


class SourceArtifactBinding(IncrementalComputationModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    parser_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parsed_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_document: bool
    chunk_key_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    chunk_artifact_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    embedding_artifact_sha256: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_canonical_shape(self) -> SourceArtifactBinding:
        if self.canonical_document:
            if self.chunk_key_sha256 is None or self.chunk_artifact_sha256 is None:
                raise ValueError("canonical source binding requires chunk artifacts")
        elif (
            self.chunk_key_sha256 is not None
            or self.chunk_artifact_sha256 is not None
            or self.embedding_artifact_sha256
        ):
            raise ValueError("non-canonical source binding cannot reference chunks")
        return self


class TombstoneArtifactBinding(IncrementalComputationModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")


class ComputationArtifactManifest(IncrementalComputationModel):
    schema_version: Literal["computation_artifact_manifest_v1"] = (
        "computation_artifact_manifest_v1"
    )
    artifact_set_id: str = Field(pattern=r"^compute_[0-9a-f]{64}$")
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{64}$")
    base_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_index_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    base_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    target_index_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    governance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embeddings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bindings: tuple[SourceArtifactBinding, ...]
    tombstone_bindings: tuple[TombstoneArtifactBinding, ...] = ()
    canonical_document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    indexed_chunk_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_manifest(self) -> ComputationArtifactManifest:
        identities = [
            (item.source_system, item.source_key) for item in self.source_bindings
        ]
        if identities != sorted(identities) or len(identities) != len(
            set(identities)
        ):
            raise ValueError("source artifact bindings must use canonical order")
        tombstones = [
            (item.source_system, item.source_key)
            for item in self.tombstone_bindings
        ]
        if tombstones != sorted(tombstones) or len(tombstones) != len(
            set(tombstones)
        ):
            raise ValueError("tombstone bindings must use canonical order")
        if set(identities) & set(tombstones):
            raise ValueError("live and tombstone source bindings must not overlap")
        if self.canonical_document_count != sum(
            item.canonical_document for item in self.source_bindings
        ):
            raise ValueError("canonical document count does not match bindings")
        if self.indexed_chunk_count > self.chunk_count:
            raise ValueError("indexed chunk count exceeds total chunks")
        expected = _content_id(
            "compute",
            self.model_dump(mode="json", exclude={"artifact_set_id"}),
        )
        if self.artifact_set_id != expected:
            raise ValueError("computation artifact set ID does not match payload")
        return self


class ComputedEmbedding(IncrementalComputationModel):
    chunk_id: str = Field(min_length=1, max_length=512)
    vector: tuple[float, ...] = Field(min_length=1, max_length=65536)

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in values):
            raise ValueError("computed embedding values must be finite")
        if not any(value != 0.0 for value in values):
            raise ValueError("computed embedding must be non-zero")
        return values


class IncrementalComputationResult(IncrementalComputationModel):
    artifact_manifest: ComputationArtifactManifest
    stats: CacheStatistics
    measurements: ComputationMeasurements
    documents: tuple[DocumentRecord, ...]
    chunks: tuple[ChunkRecord, ...]
    embeddings: tuple[ComputedEmbedding, ...]

    @model_validator(mode="after")
    def validate_artifact_manifest(self) -> IncrementalComputationResult:
        document_payload = [
            document.model_dump(mode="json") for document in self.documents
        ]
        chunk_payload = [chunk.model_dump(mode="json") for chunk in self.chunks]
        embedding_payload = [
            embedding.model_dump(mode="json") for embedding in self.embeddings
        ]
        if (
            self.artifact_manifest.documents_sha256
            != _canonical_payload_sha256(document_payload)
        ):
            raise ValueError("documents do not match computation manifest")
        if (
            self.artifact_manifest.chunks_sha256
            != _canonical_payload_sha256(chunk_payload)
        ):
            raise ValueError("chunks do not match computation manifest")
        if (
            self.artifact_manifest.embeddings_sha256
            != _canonical_payload_sha256(embedding_payload)
        ):
            raise ValueError("embeddings do not match computation manifest")

        document_ids = [document.doc_id for document in self.documents]
        if (
            len(document_ids) != len(set(document_ids))
            or len(document_ids)
            != self.artifact_manifest.canonical_document_count
        ):
            raise ValueError("document count or identity does not match manifest")
        canonical_binding_ids = {
            binding.document_id
            for binding in self.artifact_manifest.source_bindings
            if binding.canonical_document
        }
        if canonical_binding_ids != set(document_ids):
            raise ValueError("canonical source bindings do not match documents")

        if (
            len(self.chunks) != self.artifact_manifest.chunk_count
            or sum(chunk.indexable for chunk in self.chunks)
            != self.artifact_manifest.indexed_chunk_count
            or any(chunk.doc_id not in canonical_binding_ids for chunk in self.chunks)
        ):
            raise ValueError("chunk count or document binding does not match manifest")
        indexed_chunk_ids = [
            chunk.chunk_id for chunk in self.chunks if chunk.indexable
        ]
        embedding_chunk_ids = [
            embedding.chunk_id for embedding in self.embeddings
        ]
        if (
            embedding_chunk_ids != indexed_chunk_ids
            or len(embedding_chunk_ids) != len(set(embedding_chunk_ids))
        ):
            raise ValueError("embeddings do not match indexable chunks")
        dimensions = {len(embedding.vector) for embedding in self.embeddings}
        if len(dimensions) > 1:
            raise ValueError("computed embedding dimensions are inconsistent")
        if sum(
            len(binding.embedding_artifact_sha256)
            for binding in self.artifact_manifest.source_bindings
        ) != len(self.embeddings):
            raise ValueError("embedding artifact bindings do not match embeddings")
        return self


class RevisionContentMaterializer(Protocol):
    def parser_fingerprint(
        self,
        revision: DocumentRevision,
    ) -> ComponentFingerprint: ...

    def parse_content(
        self,
        revision: DocumentRevision,
    ) -> ParsedContentArtifact: ...

    def normalize_content(
        self,
        revision: DocumentRevision,
        parsed: ParsedContentArtifact,
    ) -> NormalizedContentArtifact: ...

    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord: ...


class IncrementalComputationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _content_id(prefix: str, payload: object) -> str:
    return f"{prefix}_{hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}"


def _canonical_payload_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def pipeline_configuration_sha256(config: PipelineConfiguration) -> str:
    validated = PipelineConfiguration.model_validate(config.model_dump(mode="json"))
    return hashlib.sha256(
        _canonical_json_bytes(validated.model_dump(mode="json"))
    ).hexdigest()


def _validate_base_catalog_and_plan(
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None,
    target_catalog: RevisionCatalogSnapshot,
) -> None:
    if base_catalog is None:
        if plan.base_event_count != 0:
            raise IncrementalComputationError(
                "base_catalog_required",
                "a non-empty ChangePlan requires its exact base catalog",
            )
        base_catalog = empty_revision_catalog_snapshot()
    else:
        try:
            base_catalog = RevisionCatalogSnapshot.model_validate(
                base_catalog.model_dump(mode="json")
            )
        except Exception:
            raise IncrementalComputationError(
                "base_catalog_invalid",
                "base catalog failed strict validation",
            ) from None
    if (
        revision_catalog_sha256(base_catalog) != plan.base_catalog_sha256
        or len(base_catalog.ledger.receipts) != plan.base_event_count
    ):
        raise IncrementalComputationError(
            "base_catalog_mismatch",
            "base catalog does not match the ChangePlan",
        )
    try:
        expected = build_change_plan(
            base=base_catalog,
            target=target_catalog,
            base_index_run_id=plan.base_index_run_id,
            target_index_run_id=plan.target_index_run_id,
            conflicts=plan.conflicts,
            quarantined=plan.quarantined,
        )
    except ChangePlanError as exc:
        raise IncrementalComputationError(
            "plan_lineage_invalid",
            "base and target catalogs do not form the declared forward plan",
        ) from exc
    if expected != plan:
        raise IncrementalComputationError(
            "plan_semantics_mismatch",
            "ChangePlan does not match deterministic base-to-target planning",
        )


def _live_revisions(
    snapshot: RevisionCatalogSnapshot,
) -> list[DocumentRevision]:
    revisions = {item.revision_id: item for item in snapshot.revisions}
    live: list[DocumentRevision] = []
    for head in snapshot.ledger.source_heads:
        revision = revisions[head.current_revision_id]
        if not revision.deleted:
            live.append(revision)
    return sorted(live, key=lambda item: (item.source_system, item.source_key))


def _tombstone_bindings(
    snapshot: RevisionCatalogSnapshot,
) -> tuple[TombstoneArtifactBinding, ...]:
    revisions = {item.revision_id: item for item in snapshot.revisions}
    return tuple(
        TombstoneArtifactBinding(
            tenant_id=revisions[head.current_revision_id].tenant_id,
            source_system=head.source_system,
            source_key=head.source_key,
            revision_id=head.current_revision_id,
        )
        for head in sorted(
            snapshot.ledger.source_heads,
            key=lambda item: (item.source_system, item.source_key),
        )
        if head.deleted
    )


def _validate_plan_target(
    plan: ChangePlan,
    target: RevisionCatalogSnapshot,
) -> None:
    if not plan.executable:
        raise IncrementalComputationError(
            "plan_not_executable",
            "ChangePlan contains conflict or quarantine exclusions",
        )
    if revision_catalog_sha256(target) != plan.target_catalog_sha256:
        raise IncrementalComputationError(
            "target_catalog_mismatch",
            "target catalog does not match the ChangePlan",
        )
    planned = {
        (item.source_system, item.source_key)
        for group in (
            plan.upserts,
            plan.deletes,
            plan.unchanged,
            plan.retained_tombstones,
        )
        for item in group
    }
    actual = {
        (head.source_system, head.source_key)
        for head in target.ledger.source_heads
    }
    if (
        planned != actual
        or plan.target_event_count != len(target.ledger.receipts)
    ):
        raise IncrementalComputationError(
            "plan_source_set_mismatch",
            "ChangePlan source set does not match target catalog heads",
        )
    heads = {
        (head.source_system, head.source_key): head
        for head in target.ledger.source_heads
    }
    revisions = {revision.revision_id: revision for revision in target.revisions}
    groups = (
        ("upserts", plan.upserts, False),
        ("deletes", plan.deletes, True),
        ("unchanged", plan.unchanged, False),
        ("retained_tombstones", plan.retained_tombstones, True),
    )
    allowed_reasons = {
        "upserts": {
            "content_changed",
            "governance_changed",
            "materialization_changed",
            "new_source",
            "source_restored",
        },
        "deletes": {"source_deleted"},
        "unchanged": {"revision_only", "unchanged"},
        "retained_tombstones": {"tombstone_retained"},
    }
    for group_name, items, deleted in groups:
        for item in items:
            identity = (item.source_system, item.source_key)
            head = heads[identity]
            revision = revisions[head.current_revision_id]
            if (
                item.target_revision_id != head.current_revision_id
                or item.tenant_id != revision.tenant_id
                or item.region != revision.region
                or revision.deleted != deleted
                or item.reason_code not in allowed_reasons[group_name]
            ):
                raise IncrementalComputationError(
                    "plan_target_binding_mismatch",
                    "ChangePlan item does not match its target catalog head",
                )
            if (
                item.reason_code == "unchanged"
                and item.previous_revision_id != item.target_revision_id
            ):
                raise IncrementalComputationError(
                    "plan_target_binding_mismatch",
                    "unchanged ChangePlan item does not bind the target head",
                )


def _validate_component_bindings(
    revision: DocumentRevision,
    parser: ComponentFingerprint,
    pipeline: PipelineConfiguration,
) -> None:
    materialization = revision.materialization
    if materialization is None:
        raise IncrementalComputationError(
            "live_revision_unmaterialized",
            "live target revision is missing materialization provenance",
        )
    if (
        parser.name != materialization.parser_name
        or parser.semantic_version != materialization.parser_version
    ):
        raise IncrementalComputationError(
            "parser_fingerprint_mismatch",
            "parser fingerprint does not match accepted revision provenance",
        )
    if pipeline.normalizer.semantic_version != materialization.normalizer_version:
        raise IncrementalComputationError(
            "normalizer_fingerprint_mismatch",
            "normalizer fingerprint does not match accepted revision provenance",
        )


def _validate_document_binding(
    revision: DocumentRevision,
    document: DocumentRecord,
    normalized: NormalizedContentArtifact,
) -> None:
    materialization = revision.materialization
    if materialization is None or revision.content_sha256 is None:
        raise IncrementalComputationError(
            "live_revision_unmaterialized",
            "live target revision is missing content provenance",
        )
    if (
        document.doc_id != materialization.document_id
        or document.tenant_id != revision.tenant_id
        or document.region != revision.region
        or tuple(document.acl_groups) != revision.acl_groups
        or document.checksum != revision.content_sha256
        or document.normalized_text_hash != materialization.normalized_sha256
        or normalized.normalized_sha256 != materialization.normalized_sha256
        or document.parser_name != materialization.parser_name
        or document.parser_version != materialization.parser_version
        or document.ingested_at != revision.occurred_at
        or document.title != normalized.title
        or document.text != normalized.text
        or tuple(document.sections) != normalized.sections
        or tuple(document.tables) != normalized.tables
        or tuple(document.parse_warnings) != normalized.parse_warnings
    ):
        raise IncrementalComputationError(
            "document_binding_mismatch",
            "materialized document does not match target revision governance",
        )


def _embedding_payload(
    vector: list[float],
    fingerprint: EmbeddingFingerprint,
) -> EmbeddingVectorArtifact:
    if len(vector) != fingerprint.dimension:
        raise IncrementalComputationError(
            "embedding_dimension_mismatch",
            "embedding callback returned an unexpected dimension",
        )
    if any(not math.isfinite(value) for value in vector) or not any(
        value != 0.0 for value in vector
    ):
        raise IncrementalComputationError(
            "embedding_vector_invalid",
            "embedding callback returned a non-finite or zero vector",
        )
    if fingerprint.normalization == "l2":
        norm = math.sqrt(sum(value * value for value in vector))
        vector = [value / norm for value in vector]
    return EmbeddingVectorArtifact(vector=tuple(vector))


def _strict_computation_inputs(
    *,
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None,
    target_catalog: RevisionCatalogSnapshot,
    pipeline: PipelineConfiguration,
) -> tuple[ChangePlan, RevisionCatalogSnapshot, PipelineConfiguration]:
    try:
        strict_plan = ChangePlan.model_validate(plan.model_dump(mode="json"))
    except Exception:
        raise IncrementalComputationError(
            "plan_invalid",
            "ChangePlan failed strict validation",
        ) from None
    try:
        strict_target = RevisionCatalogSnapshot.model_validate(
            target_catalog.model_dump(mode="json")
        )
    except Exception:
        raise IncrementalComputationError(
            "target_catalog_invalid",
            "target catalog failed strict validation",
        ) from None
    try:
        strict_pipeline = PipelineConfiguration.model_validate(
            pipeline.model_dump(mode="json")
        )
    except Exception:
        raise IncrementalComputationError(
            "pipeline_invalid",
            "pipeline configuration failed strict validation",
        ) from None
    _validate_plan_target(strict_plan, strict_target)
    _validate_base_catalog_and_plan(
        strict_plan,
        base_catalog,
        strict_target,
    )
    return strict_plan, strict_target, strict_pipeline


def _execute_incremental_computation(
    *,
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None = None,
    target_catalog: RevisionCatalogSnapshot,
    cache: PersistentComputationCache,
    pipeline: PipelineConfiguration,
    materializer: RevisionContentMaterializer,
    embed_text: EmbedText,
    checkpoint: ComputationCheckpoint | None = None,
    _inputs_validated: bool = False,
) -> IncrementalComputationResult:
    execution_started = time.perf_counter()
    artifact_serialization_seconds = 0.0
    if not _inputs_validated:
        plan, target_catalog, pipeline = _strict_computation_inputs(
            plan=plan,
            base_catalog=base_catalog,
            target_catalog=target_catalog,
            pipeline=pipeline,
        )
    stats = {
        "parsed_hits": 0,
        "parsed_misses": 0,
        "normalized_hits": 0,
        "normalized_misses": 0,
        "chunk_hits": 0,
        "chunk_misses": 0,
        "embedding_hits": 0,
        "embedding_misses": 0,
    }
    work: dict[
        str,
        tuple[
            DocumentRevision,
            ComponentFingerprint,
            ParsedArtifactKey,
            ParsedContentArtifact,
            NormalizedArtifactKey,
            NormalizedContentArtifact,
            DocumentRecord,
        ],
    ] = {}

    for revision in _live_revisions(target_catalog):
        materialization = revision.materialization
        if materialization is None or revision.content_sha256 is None:
            raise IncrementalComputationError(
                "live_revision_unmaterialized",
                "live target revision is missing materialization provenance",
            )
        try:
            parser = ComponentFingerprint.model_validate(
                materializer.parser_fingerprint(revision).model_dump(mode="json")
            )
        except Exception:
            raise IncrementalComputationError(
                "parser_fingerprint_invalid",
                "parser fingerprint failed strict validation",
            ) from None
        _validate_component_bindings(revision, parser, pipeline)
        parsed_key = ParsedArtifactKey(
            tenant_id=revision.tenant_id,
            source_system=revision.source_system,
            source_key=revision.source_key,
            document_id=materialization.document_id,
            content_sha256=revision.content_sha256,
            declared_media_type=revision.declared_media_type,
            parser=parser,
        )
        _checkpoint(checkpoint, "cache_read")
        parsed = cache.load_parsed(parsed_key)
        if parsed is None:
            stats["parsed_misses"] += 1
            _checkpoint(checkpoint, "parser")
            try:
                parsed = ParsedContentArtifact.model_validate(
                    materializer.parse_content(revision)
                )
            except Exception:
                raise IncrementalComputationError(
                    "parse_failed",
                    "revision content parsing failed",
                ) from None
            _checkpoint(checkpoint, "cache_write")
            write = cache.store_parsed(parsed_key, parsed)
            artifact_serialization_seconds += write.serialization_seconds
        else:
            stats["parsed_hits"] += 1

        normalized_key = NormalizedArtifactKey(
            tenant_id=revision.tenant_id,
            source_system=revision.source_system,
            source_key=revision.source_key,
            document_id=materialization.document_id,
            content_sha256=revision.content_sha256,
            expected_normalized_sha256=materialization.normalized_sha256,
            parsed_artifact_sha256=cache_payload_sha256(parsed),
            parser=parser,
            normalizer=pipeline.normalizer,
        )
        _checkpoint(checkpoint, "cache_read")
        normalized = cache.load_normalized(normalized_key)
        if normalized is None:
            stats["normalized_misses"] += 1
            _checkpoint(checkpoint, "normalizer")
            try:
                normalized = NormalizedContentArtifact.model_validate(
                    materializer.normalize_content(revision, parsed)
                )
            except Exception:
                raise IncrementalComputationError(
                    "normalization_failed",
                    "revision content normalization failed",
                ) from None
            if normalized.normalized_sha256 != materialization.normalized_sha256:
                raise IncrementalComputationError(
                    "normalized_hash_mismatch",
                    "normalized artifact does not match accepted revision hash",
                )
            _checkpoint(checkpoint, "cache_write")
            write = cache.store_normalized(normalized_key, normalized)
            artifact_serialization_seconds += write.serialization_seconds
        else:
            stats["normalized_hits"] += 1

        try:
            document = DocumentRecord.model_validate(
                materializer.materialize_document(revision, normalized)
            )
        except Exception:
            raise IncrementalComputationError(
                "document_materialization_failed",
                "target document materialization failed",
            ) from None
        _validate_document_binding(revision, document, normalized)
        if document.doc_id in work:
            raise IncrementalComputationError(
                "duplicate_document_binding",
                "multiple live revisions materialized the same document ID",
            )
        work[document.doc_id] = (
            revision,
            parser,
            parsed_key,
            parsed,
            normalized_key,
            normalized,
            document,
        )

    try:
        governed = govern_documents([item[-1] for item in work.values()])
    except Exception:
        raise IncrementalComputationError(
            "target_governance_failed",
            "complete target document governance failed",
        ) from None

    chunks: list[ChunkRecord] = []
    embeddings: list[ComputedEmbedding] = []
    chunk_artifacts: dict[
        str,
        tuple[ChunkArtifactKey, ChunkLayoutArtifact, tuple[str, ...]],
    ] = {}

    for document in governed.documents:
        revision, parser, _, _, _, normalized, _ = work[document.doc_id]
        materialization = revision.materialization
        assert materialization is not None
        chunk_key = ChunkArtifactKey(
            tenant_id=revision.tenant_id,
            source_system=revision.source_system,
            source_key=revision.source_key,
            document_id=document.doc_id,
            normalized_sha256=normalized.normalized_sha256,
            normalized_artifact_sha256=cache_payload_sha256(normalized),
            parser=parser,
            normalizer=pipeline.normalizer,
            chunker=pipeline.chunker,
            chunker_config_sha256=chunker_config_sha256(
                pipeline.chunker_config
            ),
        )
        _checkpoint(checkpoint, "cache_read")
        layout = cache.load_chunks(chunk_key)
        if layout is None:
            stats["chunk_misses"] += 1
            _checkpoint(checkpoint, "chunker")
            layout = ChunkLayoutArtifact.from_chunk_records(
                chunk_document(document, pipeline.chunker_config)
            )
            _checkpoint(checkpoint, "cache_write")
            write = cache.store_chunks(chunk_key, layout)
            artifact_serialization_seconds += write.serialization_seconds
        else:
            stats["chunk_hits"] += 1
        document_chunks = layout.materialize(document)
        chunks.extend(document_chunks)

        embedding_hashes: list[str] = []
        for chunk in document_chunks:
            if not chunk.indexable:
                continue
            embedding_key = EmbeddingArtifactKey(
                tenant_id=revision.tenant_id,
                source_system=revision.source_system,
                source_key=revision.source_key,
                document_id=document.doc_id,
                chunk_text_sha256=chunk.text_hash,
                content_pipeline_sha256=pipeline_fingerprint_sha256(
                    parser=parser,
                    normalizer=pipeline.normalizer,
                    chunker=pipeline.chunker,
                    chunker_config=pipeline.chunker_config,
                ),
                embedding=pipeline.embedding,
            )
            _checkpoint(checkpoint, "cache_read")
            vector = cache.load_embedding(embedding_key)
            if vector is None:
                stats["embedding_misses"] += 1
                _checkpoint(checkpoint, "embedding")
                try:
                    vector = _embedding_payload(
                        list(embed_text(chunk.text)),
                        pipeline.embedding,
                    )
                except IncrementalComputationError:
                    raise
                except Exception:
                    raise IncrementalComputationError(
                        "embedding_failed",
                        "embedding callback failed",
                    ) from None
                _checkpoint(checkpoint, "cache_write")
                write = cache.store_embedding(embedding_key, vector)
                artifact_serialization_seconds += write.serialization_seconds
            else:
                stats["embedding_hits"] += 1
            embeddings.append(
                ComputedEmbedding(
                    chunk_id=chunk.chunk_id,
                    vector=vector.vector,
                )
            )
            embedding_hashes.append(cache_payload_sha256(vector))
        chunk_artifacts[document.doc_id] = (
            chunk_key,
            layout,
            tuple(embedding_hashes),
        )

    canonical_ids = {document.doc_id for document in governed.documents}
    bindings: list[SourceArtifactBinding] = []
    for document_id, item in sorted(
        work.items(),
        key=lambda pair: (pair[1][0].source_system, pair[1][0].source_key),
    ):
        revision, _, parsed_key, parsed, normalized_key, normalized, _ = item
        canonical = document_id in canonical_ids
        chunk_key = None
        layout = None
        embedding_hashes: tuple[str, ...] = ()
        if canonical:
            chunk_key, layout, embedding_hashes = chunk_artifacts[document_id]
        bindings.append(
            SourceArtifactBinding(
                tenant_id=revision.tenant_id,
                source_system=revision.source_system,
                source_key=revision.source_key,
                document_id=document_id,
                revision_id=revision.revision_id,
                parser_key_sha256=cache_key_sha256(parsed_key),
                parsed_artifact_sha256=cache_payload_sha256(parsed),
                normalized_key_sha256=cache_key_sha256(normalized_key),
                normalized_artifact_sha256=cache_payload_sha256(normalized),
                canonical_document=canonical,
                chunk_key_sha256=(
                    cache_key_sha256(chunk_key) if chunk_key is not None else None
                ),
                chunk_artifact_sha256=(
                    cache_payload_sha256(layout) if layout is not None else None
                ),
                embedding_artifact_sha256=embedding_hashes,
            )
        )

    manifest_serialization_started = time.perf_counter()
    manifest_payload = {
        "schema_version": "computation_artifact_manifest_v1",
        "plan_id": plan.plan_id,
        "base_catalog_sha256": plan.base_catalog_sha256,
        "target_catalog_sha256": plan.target_catalog_sha256,
        "base_index_run_id": plan.base_index_run_id,
        "base_manifest_sha256": None,
        "target_index_run_id": plan.target_index_run_id,
        "pipeline_sha256": pipeline_configuration_sha256(pipeline),
        "governance_sha256": _canonical_payload_sha256(
            {
                "source_document_count": governed.source_document_count,
                "duplicate_aliases": governed.duplicate_aliases,
                "version_heads": governed.version_heads,
                "retired_doc_ids": governed.retired_doc_ids,
            }
        ),
        "documents_sha256": _canonical_payload_sha256(
            [
                document.model_dump(mode="json")
                for document in governed.documents
            ]
        ),
        "chunks_sha256": _canonical_payload_sha256(
            [chunk.model_dump(mode="json") for chunk in chunks]
        ),
        "embeddings_sha256": _canonical_payload_sha256(
            [embedding.model_dump(mode="json") for embedding in embeddings]
        ),
        "source_bindings": [
            binding.model_dump(mode="json") for binding in bindings
        ],
        "tombstone_bindings": [
            binding.model_dump(mode="json")
            for binding in _tombstone_bindings(target_catalog)
        ],
        "canonical_document_count": len(governed.documents),
        "chunk_count": len(chunks),
        "indexed_chunk_count": sum(chunk.indexable for chunk in chunks),
    }
    manifest = ComputationArtifactManifest(
        artifact_set_id=_content_id("compute", manifest_payload),
        **manifest_payload,
    )
    artifact_serialization_seconds += (
        time.perf_counter() - manifest_serialization_started
    )
    provisional_result = IncrementalComputationResult(
        artifact_manifest=manifest,
        stats=CacheStatistics(**stats),
        measurements=ComputationMeasurements(
            parse_calls=stats["parsed_misses"],
            normalize_calls=stats["normalized_misses"],
            chunk_calls=stats["chunk_misses"],
            embedding_calls=stats["embedding_misses"],
            artifact_serialization_seconds=artifact_serialization_seconds,
            total_wall_seconds=0.0,
        ),
        documents=tuple(governed.documents),
        chunks=tuple(chunks),
        embeddings=tuple(embeddings),
    )
    final_measurements = ComputationMeasurements(
        **provisional_result.measurements.model_dump(
            exclude={"total_wall_seconds"}
        ),
        total_wall_seconds=time.perf_counter() - execution_started,
    )
    return provisional_result.model_copy(
        update={"measurements": final_measurements}
    )


def execute_incremental_computation(
    *,
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None = None,
    target_catalog: RevisionCatalogSnapshot,
    cache: PersistentComputationCache,
    pipeline: PipelineConfiguration,
    materializer: RevisionContentMaterializer,
    embed_text: EmbedText,
    checkpoint: ComputationCheckpoint | None = None,
) -> IncrementalComputationResult:
    execution_started = time.perf_counter()
    plan, target_catalog, pipeline = _strict_computation_inputs(
        plan=plan,
        base_catalog=base_catalog,
        target_catalog=target_catalog,
        pipeline=pipeline,
    )
    transaction_factory = getattr(cache, "transaction", None)
    transaction = (
        transaction_factory()
        if _live_revisions(target_catalog)
        and callable(transaction_factory)
        else nullcontext()
    )
    with transaction:
        result = _execute_incremental_computation(
            plan=plan,
            base_catalog=base_catalog,
            target_catalog=target_catalog,
            cache=cache,
            pipeline=pipeline,
            materializer=materializer,
            embed_text=embed_text,
            checkpoint=checkpoint,
            _inputs_validated=True,
        )
    final_measurements = result.measurements.model_copy(
        update={
            "total_wall_seconds": time.perf_counter() - execution_started,
        }
    )
    return result.model_copy(
        update={"measurements": final_measurements}
    )


def _checkpoint(
    callback: ComputationCheckpoint | None,
    point: ComputationFailurePoint,
) -> None:
    if callback is not None:
        callback(point)


__all__ = [
    "CacheStatistics",
    "ComputationMeasurements",
    "ComputationArtifactManifest",
    "ComputedEmbedding",
    "ComputationCheckpoint",
    "ComputationFailurePoint",
    "IncrementalComputationError",
    "IncrementalComputationResult",
    "PipelineConfiguration",
    "RevisionContentMaterializer",
    "SourceArtifactBinding",
    "TombstoneArtifactBinding",
    "execute_incremental_computation",
    "pipeline_configuration_sha256",
]
