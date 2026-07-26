from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Literal

import faiss
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.documents import ChunkRecord, DocumentRecord
from app.domain.queries import SearchRequest
from app.filesystem import atomic_directory_move
from app.indexing.builder import validate_index_directory
from app.indexing.change_plan import (
    ChangePlan,
    build_change_plan,
    canonical_change_plan_bytes,
)
from app.indexing.incremental_computation import (
    ComputationArtifactManifest,
    ComputedEmbedding,
    IncrementalComputationResult,
    PipelineConfiguration,
    RevisionContentMaterializer,
    execute_incremental_computation,
    pipeline_configuration_sha256,
)
from app.indexing.computation_cache import PersistentComputationCache
from app.indexing.manifest import (
    ArtifactFile,
    BM25Spec,
    EmbeddingSpec,
    FaissSpec,
    IndexManifest,
    load_index_manifest,
    serialize_index_manifest,
)
from app.indexing.store import (
    activate_version,
    load_active_pointer,
    load_index_version,
    publication_lock,
)
from app.ingestion.revision_catalog import (
    RevisionCatalogSnapshot,
    canonical_revision_catalog_bytes,
    empty_revision_catalog_snapshot,
    revision_catalog_sha256,
)
from app.utils import tokenize_for_bm25


PublicationFailurePoint = Literal[
    "file_validation",
    "parser",
    "normalizer",
    "chunker",
    "embedding",
    "cache_read",
    "cache_write",
    "documents_artifact_write",
    "chunks_artifact_write",
    "bm25_write",
    "faiss_write",
    "manifest_write",
    "version_install",
    "active_pointer_replace",
]
FailureInjector = Callable[[PublicationFailurePoint], None]
EmbedText = Callable[[str], list[float]]

_LIFECYCLE_MANIFEST_PATH = "lifecycle.json"
_TARGET_CATALOG_PATH = "revision_catalog.json"
_CHANGE_PLAN_PATH = "change_plan.json"
_COMPUTATION_MANIFEST_PATH = "computation_manifest.json"
_EMBEDDING_ROWS_PATH = "embedding_rows.json"
_RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class LifecyclePublicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class PublicationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class BaseIndexBinding(PublicationModel):
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lifecycle_publication_id: str = Field(pattern=r"^publication_[0-9a-f]{64}$")


class SourceIndexBinding(PublicationModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    canonical_document: bool
    indexed_chunk_ids: tuple[str, ...] = ()
    parent_chunk_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_chunk_shape(self) -> SourceIndexBinding:
        for values, label in (
            (self.indexed_chunk_ids, "indexed chunk IDs"),
            (self.parent_chunk_ids, "parent chunk IDs"),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{label} must use unique canonical order")
        if not self.canonical_document and (
            self.indexed_chunk_ids or self.parent_chunk_ids
        ):
            raise ValueError("non-canonical source cannot own index chunks")
        return self


class TombstoneIndexBinding(PublicationModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{64}$")
    prior_document_ids: tuple[str, ...] = ()
    prior_indexed_chunk_ids: tuple[str, ...] = ()
    prior_parent_chunk_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_prior_mapping_order(self) -> TombstoneIndexBinding:
        for values, label in (
            (self.prior_document_ids, "prior document IDs"),
            (self.prior_indexed_chunk_ids, "prior indexed chunk IDs"),
            (self.prior_parent_chunk_ids, "prior parent chunk IDs"),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{label} must use unique canonical order")
        return self


class LifecycleIndexManifest(PublicationModel):
    schema_version: Literal["lifecycle_index_manifest_v1"] = (
        "lifecycle_index_manifest_v1"
    )
    publication_id: str = Field(pattern=r"^publication_[0-9a-f]{64}$")
    producer: Literal["enterprise_agentic_rag_v2"] = "enterprise_agentic_rag_v2"
    target_index_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    profile_id: str = Field(min_length=1, max_length=128)
    plan_id: str = Field(pattern=r"^plan_[0-9a-f]{64}$")
    source_events_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    computation_artifact_set_id: str = Field(pattern=r"^compute_[0-9a-f]{64}$")
    pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    governance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_event_count: int = Field(ge=0)
    base_index: BaseIndexBinding | None = None
    documents_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embeddings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    indexed_chunk_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_chunk_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    computation_chunk_order: tuple[str, ...]
    source_bindings: tuple[SourceIndexBinding, ...]
    tombstone_bindings: tuple[TombstoneIndexBinding, ...] = ()

    @model_validator(mode="after")
    def validate_manifest(self) -> LifecycleIndexManifest:
        source_identities = [
            (item.source_system, item.source_key) for item in self.source_bindings
        ]
        tombstone_identities = [
            (item.source_system, item.source_key) for item in self.tombstone_bindings
        ]
        if (
            source_identities != sorted(source_identities)
            or len(source_identities) != len(set(source_identities))
        ):
            raise ValueError("source index bindings must use canonical order")
        if (
            tombstone_identities != sorted(tombstone_identities)
            or len(tombstone_identities) != len(set(tombstone_identities))
        ):
            raise ValueError("tombstone index bindings must use canonical order")
        if set(source_identities) & set(tombstone_identities):
            raise ValueError("live and tombstone index bindings must not overlap")
        if len(self.computation_chunk_order) != len(
            set(self.computation_chunk_order)
        ):
            raise ValueError("computation chunk order must contain unique IDs")
        expected = _content_id(
            "publication",
            self.model_dump(mode="json", exclude={"publication_id"}),
        )
        if self.publication_id != expected:
            raise ValueError("publication ID does not match canonical payload")
        return self


class IncrementalPublicationResult(PublicationModel):
    status: Literal["BUILT", "REUSED"]
    activated: bool
    index_manifest: IndexManifest
    lifecycle_manifest: LifecycleIndexManifest
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RollbackAuditEvent(PublicationModel):
    schema_version: Literal["lifecycle_rollback_audit_v1"] = (
        "lifecycle_rollback_audit_v1"
    )
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_event_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    operation: Literal["ROLLBACK"] = "ROLLBACK"
    from_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    from_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    to_run_id: str = Field(pattern=_RUN_ID_PATTERN)
    to_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurred_at: datetime
    old_data_visibility_restored: Literal[True] = True
    query_fingerprint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_event(self) -> RollbackAuditEvent:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        expected = _sha256(
            _canonical_json_bytes(
                self.model_dump(mode="json", exclude={"event_sha256"})
            )
        )
        if self.event_sha256 != expected:
            raise ValueError("rollback audit event hash does not match payload")
        return self


class RollbackResult(PublicationModel):
    pointer_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_fingerprint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    audit_event: RollbackAuditEvent


class RollbackIntent(PublicationModel):
    schema_version: Literal["lifecycle_rollback_intent_v1"] = (
        "lifecycle_rollback_intent_v1"
    )
    audit_event: RollbackAuditEvent


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _content_id(prefix: str, payload: object) -> str:
    return f"{prefix}_{_sha256(_canonical_json_bytes(payload))}"


def _payload_sha256(payload: object) -> str:
    return _sha256(_canonical_json_bytes(payload))


def serialize_lifecycle_manifest(manifest: LifecycleIndexManifest) -> bytes:
    validated = LifecycleIndexManifest.model_validate(
        manifest.model_dump(mode="json")
    )
    return _pretty_json_bytes(validated.model_dump(mode="json"))


def load_lifecycle_manifest(path: Path) -> LifecycleIndexManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return LifecycleIndexManifest.model_validate(payload)


def _strict_inputs(
    *,
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None,
    target_catalog: RevisionCatalogSnapshot,
    computation: IncrementalComputationResult,
    pipeline: PipelineConfiguration,
) -> tuple[
    ChangePlan,
    RevisionCatalogSnapshot,
    RevisionCatalogSnapshot,
    IncrementalComputationResult,
    PipelineConfiguration,
]:
    try:
        strict_plan = ChangePlan.model_validate(plan.model_dump(mode="json"))
        strict_target = RevisionCatalogSnapshot.model_validate(
            target_catalog.model_dump(mode="json")
        )
        strict_computation = IncrementalComputationResult.model_validate(
            computation.model_dump(mode="json")
        )
        strict_pipeline = PipelineConfiguration.model_validate(
            pipeline.model_dump(mode="json")
        )
        if base_catalog is None:
            strict_base = empty_revision_catalog_snapshot()
        else:
            strict_base = RevisionCatalogSnapshot.model_validate(
                base_catalog.model_dump(mode="json")
            )
    except Exception:
        raise LifecyclePublicationError(
            "publication_input_invalid",
            "G7 inputs failed strict boundary validation",
        ) from None
    try:
        expected_plan = build_change_plan(
            base=strict_base,
            target=strict_target,
            base_index_run_id=strict_plan.base_index_run_id,
            target_index_run_id=strict_plan.target_index_run_id,
            conflicts=strict_plan.conflicts,
            quarantined=strict_plan.quarantined,
        )
    except Exception:
        raise LifecyclePublicationError(
            "publication_plan_invalid",
            "base and target catalogs do not reconstruct the supplied ChangePlan",
        ) from None
    if expected_plan != strict_plan or not strict_plan.executable:
        raise LifecyclePublicationError(
            "publication_plan_mismatch",
            "G7 requires an exact executable deterministic ChangePlan",
        )
    artifact_manifest = strict_computation.artifact_manifest
    if (
        artifact_manifest.plan_id != strict_plan.plan_id
        or artifact_manifest.base_catalog_sha256
        != strict_plan.base_catalog_sha256
        or artifact_manifest.target_catalog_sha256
        != strict_plan.target_catalog_sha256
        or artifact_manifest.base_index_run_id
        != strict_plan.base_index_run_id
        or artifact_manifest.target_index_run_id
        != strict_plan.target_index_run_id
        or artifact_manifest.pipeline_sha256
        != pipeline_configuration_sha256(strict_pipeline)
        or revision_catalog_sha256(strict_target)
        != strict_plan.target_catalog_sha256
    ):
        raise LifecyclePublicationError(
            "computation_binding_mismatch",
            "G6 computation does not bind the exact G7 plan, catalogs, and pipeline",
        )
    if artifact_manifest.base_manifest_sha256 is not None:
        raise LifecyclePublicationError(
            "caller_base_binding_forbidden",
            "G6 must not manufacture a base index manifest binding",
        )
    return (
        strict_plan,
        strict_base,
        strict_target,
        strict_computation,
        strict_pipeline,
    )


def _load_base_binding(
    root: Path,
    plan: ChangePlan,
) -> tuple[BaseIndexBinding | None, LifecycleIndexManifest | None]:
    if plan.base_event_count == 0:
        return None, None
    assert plan.base_index_run_id is not None
    try:
        loaded = load_index_version(root, plan.base_index_run_id)
        lifecycle = validate_incremental_index_directory(loaded.path)
    except Exception:
        raise LifecyclePublicationError(
            "base_index_invalid",
            "the declared immutable base index could not be validated",
        ) from None
    if lifecycle.target_catalog_sha256 != plan.base_catalog_sha256:
        raise LifecyclePublicationError(
            "base_catalog_binding_mismatch",
            "the actual base index lifecycle manifest binds a different catalog",
        )
    return (
        BaseIndexBinding(
            run_id=loaded.manifest.run_id,
            manifest_sha256=loaded.manifest_sha256,
            catalog_sha256=lifecycle.target_catalog_sha256,
            lifecycle_publication_id=lifecycle.publication_id,
        ),
        lifecycle,
    )


def _active_identity(root: Path) -> tuple[str, str] | None:
    try:
        pointer = load_active_pointer(root)
    except FileNotFoundError:
        return None
    return pointer.run_id, pointer.manifest_sha256


def _require_expected_active(
    root: Path,
    base: BaseIndexBinding | None,
) -> None:
    actual = _active_identity(root)
    expected = None if base is None else (base.run_id, base.manifest_sha256)
    if actual != expected:
        raise LifecyclePublicationError(
            "active_base_conflict",
            "active pointer changed after planning; refusing a lost update",
        )


def _source_bindings(
    computation: IncrementalComputationResult,
) -> tuple[SourceIndexBinding, ...]:
    indexed_by_doc: dict[str, list[str]] = {}
    parents_by_doc: dict[str, list[str]] = {}
    for chunk in computation.chunks:
        destination = indexed_by_doc if chunk.indexable else parents_by_doc
        destination.setdefault(chunk.doc_id, []).append(chunk.chunk_id)
    return tuple(
        SourceIndexBinding(
            tenant_id=item.tenant_id,
            source_system=item.source_system,
            source_key=item.source_key,
            document_id=item.document_id,
            revision_id=item.revision_id,
            canonical_document=item.canonical_document,
            indexed_chunk_ids=tuple(
                sorted(indexed_by_doc.get(item.document_id, ()))
            ),
            parent_chunk_ids=tuple(
                sorted(parents_by_doc.get(item.document_id, ()))
            ),
        )
        for item in computation.artifact_manifest.source_bindings
    )


def _tombstone_bindings(
    computation: IncrementalComputationResult,
    base_lifecycle: LifecycleIndexManifest | None,
) -> tuple[TombstoneIndexBinding, ...]:
    previous = (
        {}
        if base_lifecycle is None
        else {
            (item.source_system, item.source_key): item
            for item in base_lifecycle.source_bindings
        }
    )
    result: list[TombstoneIndexBinding] = []
    for item in computation.artifact_manifest.tombstone_bindings:
        prior = previous.get((item.source_system, item.source_key))
        result.append(
            TombstoneIndexBinding(
                tenant_id=item.tenant_id,
                source_system=item.source_system,
                source_key=item.source_key,
                revision_id=item.revision_id,
                prior_document_ids=(
                    () if prior is None else (prior.document_id,)
                ),
                prior_indexed_chunk_ids=(
                    () if prior is None else prior.indexed_chunk_ids
                ),
                prior_parent_chunk_ids=(
                    () if prior is None else prior.parent_chunk_ids
                ),
            )
        )
    return tuple(result)


def _lifecycle_manifest(
    *,
    plan: ChangePlan,
    computation: IncrementalComputationResult,
    pipeline: PipelineConfiguration,
    profile_id: str,
    base_binding: BaseIndexBinding | None,
    base_lifecycle: LifecycleIndexManifest | None,
) -> LifecycleIndexManifest:
    documents = [document.doc_id for document in computation.documents]
    indexed_chunks = [
        chunk.chunk_id for chunk in computation.chunks if chunk.indexable
    ]
    parent_chunks = [
        chunk.chunk_id for chunk in computation.chunks if not chunk.indexable
    ]
    payload = {
        "schema_version": "lifecycle_index_manifest_v1",
        "producer": "enterprise_agentic_rag_v2",
        "target_index_run_id": plan.target_index_run_id,
        "profile_id": profile_id,
        "plan_id": plan.plan_id,
        "source_events_sha256": plan.source_events_sha256,
        "computation_artifact_set_id": (
            computation.artifact_manifest.artifact_set_id
        ),
        "pipeline_sha256": pipeline_configuration_sha256(pipeline),
        "governance_sha256": computation.artifact_manifest.governance_sha256,
        "target_catalog_sha256": plan.target_catalog_sha256,
        "target_event_count": plan.target_event_count,
        "base_index": (
            None if base_binding is None else base_binding.model_dump(mode="json")
        ),
        "documents_sha256": computation.artifact_manifest.documents_sha256,
        "chunks_sha256": computation.artifact_manifest.chunks_sha256,
        "embeddings_sha256": computation.artifact_manifest.embeddings_sha256,
        "document_ids_sha256": _payload_sha256(documents),
        "indexed_chunk_ids_sha256": _payload_sha256(indexed_chunks),
        "parent_chunk_ids_sha256": _payload_sha256(parent_chunks),
        "computation_chunk_order": [
            chunk.chunk_id for chunk in computation.chunks
        ],
        "source_bindings": [
            item.model_dump(mode="json") for item in _source_bindings(computation)
        ],
        "tombstone_bindings": [
            item.model_dump(mode="json")
            for item in _tombstone_bindings(computation, base_lifecycle)
        ],
    }
    return LifecycleIndexManifest(
        publication_id=_content_id("publication", payload),
        **payload,
    )


def _json_models(models: Iterable[BaseModel]) -> bytes:
    return _pretty_json_bytes(
        [model.model_dump(mode="json") for model in models]
    )


def _artifact_records(artifacts: dict[str, bytes]) -> list[ArtifactFile]:
    return [
        ArtifactFile(
            path=path,
            sha256=_sha256(content),
            byte_count=len(content),
        )
        for path, content in sorted(artifacts.items())
    ]


def _artifact_bytes(
    plan: ChangePlan,
    target: RevisionCatalogSnapshot,
    computation: IncrementalComputationResult,
    pipeline: PipelineConfiguration,
    lifecycle: LifecycleIndexManifest,
) -> tuple[dict[str, bytes], int]:
    indexed_chunks = tuple(
        chunk for chunk in computation.chunks if chunk.indexable
    )
    parents = tuple(chunk for chunk in computation.chunks if not chunk.indexable)
    if any(parent.kind != "parent" for parent in parents):
        raise LifecyclePublicationError(
            "non_indexable_chunk_invalid",
            "G7 only permits parent chunks outside the index mapping",
        )
    dimension = pipeline.embedding.dimension
    vectors = np.asarray(
        [embedding.vector for embedding in computation.embeddings],
        dtype="float32",
    )
    if vectors.size == 0:
        vectors = np.empty((0, dimension), dtype="float32")
    if vectors.shape != (len(indexed_chunks), dimension):
        raise LifecyclePublicationError(
            "embedding_shape_mismatch",
            "computed embeddings do not match target index rows",
        )
    if len(vectors):
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if (
            not np.isfinite(vectors).all()
            or not np.isfinite(norms).all()
            or np.any(norms == 0)
        ):
            raise LifecyclePublicationError(
                "embedding_vector_invalid",
                "target embeddings must be finite and non-zero",
            )
        vectors = vectors / norms
    index = faiss.IndexFlatIP(dimension)
    if len(vectors):
        index.add(vectors)
    tokens = [tokenize_for_bm25(chunk.text) for chunk in indexed_chunks]
    if any(not row for row in tokens):
        raise LifecyclePublicationError(
            "bm25_tokenization_empty",
            "every indexed chunk must produce at least one BM25 token",
        )
    return (
        {
            "documents.json": _json_models(computation.documents),
            "chunks.json": _json_models(indexed_chunks),
            "parents.json": _json_models(parents),
            "bm25_tokens.pkl": pickle.dumps(
                tokens,
                protocol=pickle.HIGHEST_PROTOCOL,
            ),
            "faiss.index": faiss.serialize_index(index).tobytes(),
            _TARGET_CATALOG_PATH: canonical_revision_catalog_bytes(target),
            _CHANGE_PLAN_PATH: canonical_change_plan_bytes(plan),
            _COMPUTATION_MANIFEST_PATH: _canonical_json_bytes(
                computation.artifact_manifest.model_dump(mode="json")
            ),
            _EMBEDDING_ROWS_PATH: _json_models(computation.embeddings),
            _LIFECYCLE_MANIFEST_PATH: serialize_lifecycle_manifest(lifecycle),
        },
        dimension,
    )


def _parser_versions(
    target: RevisionCatalogSnapshot,
) -> dict[str, str]:
    values: dict[str, str] = {}
    revisions = {item.revision_id: item for item in target.revisions}
    for head in target.ledger.source_heads:
        revision = revisions[head.current_revision_id]
        if revision.deleted or revision.materialization is None:
            continue
        name = revision.materialization.parser_name
        version = revision.materialization.parser_version
        existing = values.get(name)
        if existing is not None and existing != version:
            raise LifecyclePublicationError(
                "mixed_parser_versions",
                "one parser name cannot publish mixed semantic versions",
            )
        values[name] = version
    return dict(sorted(values.items()))


def _index_manifest(
    *,
    plan: ChangePlan,
    target: RevisionCatalogSnapshot,
    computation: IncrementalComputationResult,
    pipeline: PipelineConfiguration,
    profile_id: str,
    artifacts: dict[str, bytes],
    dimension: int,
    started_at: datetime,
    finished_at: datetime,
) -> IndexManifest:
    source_count = len(computation.artifact_manifest.source_bindings)
    canonical_count = len(computation.documents)
    return IndexManifest(
        schema_version="enterprise_index_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        index_version="v2-lifecycle",
        run_id=plan.target_index_run_id,
        profile_id=profile_id,
        corpus_manifest_hash=plan.target_catalog_sha256,
        embedding=EmbeddingSpec(
            model=pipeline.embedding.model_identifier,
            dimension=dimension,
            normalization="l2",
        ),
        faiss=FaissSpec(index_type="IndexFlatIP", metric="inner_product"),
        bm25=BM25Spec(
            tokenizer="jieba",
            parameters={"k1": 1.5, "b": 0.75, "epsilon": 0.25},
        ),
        chunker_config=pipeline.chunker_config.model_dump(mode="json"),
        parser_versions=_parser_versions(target),
        source_document_count=source_count,
        canonical_document_count=canonical_count,
        duplicate_count=source_count - canonical_count,
        chunk_count=len(computation.chunks),
        indexed_chunk_count=sum(
            chunk.indexable for chunk in computation.chunks
        ),
        parent_chunk_count=sum(
            chunk.kind == "parent" for chunk in computation.chunks
        ),
        table_chunk_count=sum(
            chunk.kind == "table" for chunk in computation.chunks
        ),
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=max(
            0,
            round((finished_at - started_at).total_seconds() * 1000),
        ),
        artifacts=_artifact_records(artifacts),
    )


def _hit(injector: FailureInjector | None, point: PublicationFailurePoint) -> None:
    if injector is not None:
        injector(point)


def _write_file(path: Path, content: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short index artifact write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_stage(
    *,
    stage: Path,
    artifacts: dict[str, bytes],
    manifest: IndexManifest,
    injector: FailureInjector | None,
) -> None:
    stage.mkdir()
    _hit(injector, "documents_artifact_write")
    _write_file(stage / "documents.json", artifacts["documents.json"])
    _hit(injector, "chunks_artifact_write")
    _write_file(stage / "chunks.json", artifacts["chunks.json"])
    _write_file(stage / "parents.json", artifacts["parents.json"])
    _hit(injector, "bm25_write")
    _write_file(stage / "bm25_tokens.pkl", artifacts["bm25_tokens.pkl"])
    _hit(injector, "faiss_write")
    _write_file(stage / "faiss.index", artifacts["faiss.index"])
    _hit(injector, "manifest_write")
    for name in (
        _TARGET_CATALOG_PATH,
        _CHANGE_PLAN_PATH,
        _COMPUTATION_MANIFEST_PATH,
        _EMBEDDING_ROWS_PATH,
    ):
        _write_file(stage / name, artifacts[name])
    _write_file(
        stage / _LIFECYCLE_MANIFEST_PATH,
        artifacts[_LIFECYCLE_MANIFEST_PATH],
    )
    _write_file(stage / "manifest.json", serialize_index_manifest(manifest))
    _sync_directory(stage)


def _safe_file(path: Path, root: Path) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_nlink != 1
        or path.resolve().parent != root.resolve()
    ):
        raise LifecyclePublicationError(
            "index_artifact_unsafe",
            "index artifact is not a confined single-link regular file",
        )


def validate_incremental_index_directory(
    path: Path,
) -> LifecycleIndexManifest:
    path = Path(path)
    manifest = load_index_manifest(path / "manifest.json")
    validate_index_directory(path, manifest)
    expected_paths = {"manifest.json", *(item.path for item in manifest.artifacts)}
    actual_paths = {item.name for item in path.iterdir()}
    if actual_paths != expected_paths:
        raise LifecyclePublicationError(
            "index_file_set_mismatch",
            "immutable index directory contains undeclared or missing files",
        )
    for name in expected_paths:
        _safe_file(path / name, path)
    artifact_names = {item.path for item in manifest.artifacts}
    required_lifecycle_artifacts = {
        _LIFECYCLE_MANIFEST_PATH,
        _TARGET_CATALOG_PATH,
        _CHANGE_PLAN_PATH,
        _COMPUTATION_MANIFEST_PATH,
        _EMBEDDING_ROWS_PATH,
    }
    if not required_lifecycle_artifacts <= artifact_names:
        raise LifecyclePublicationError(
            "lifecycle_manifest_missing",
            "G7 index manifest does not bind every lifecycle evidence artifact",
        )
    lifecycle = load_lifecycle_manifest(path / _LIFECYCLE_MANIFEST_PATH)
    if (
        lifecycle.target_index_run_id != manifest.run_id
        or lifecycle.profile_id != manifest.profile_id
    ):
        raise LifecyclePublicationError(
            "lifecycle_run_mismatch",
            "lifecycle run or profile does not match index manifest",
        )
    target_catalog_bytes = (path / _TARGET_CATALOG_PATH).read_bytes()
    target_catalog = RevisionCatalogSnapshot.model_validate_json(
        target_catalog_bytes
    )
    if (
        canonical_revision_catalog_bytes(target_catalog) != target_catalog_bytes
        or revision_catalog_sha256(target_catalog)
        != lifecycle.target_catalog_sha256
        or len(target_catalog.ledger.receipts) != lifecycle.target_event_count
    ):
        raise LifecyclePublicationError(
            "target_catalog_artifact_mismatch",
            "target catalog artifact is non-canonical or has the wrong binding",
        )
    plan_bytes = (path / _CHANGE_PLAN_PATH).read_bytes()
    change_plan = ChangePlan.model_validate_json(plan_bytes)
    if (
        canonical_change_plan_bytes(change_plan) != plan_bytes
        or change_plan.plan_id != lifecycle.plan_id
        or change_plan.source_events_sha256 != lifecycle.source_events_sha256
        or change_plan.target_catalog_sha256
        != lifecycle.target_catalog_sha256
        or change_plan.target_index_run_id != lifecycle.target_index_run_id
    ):
        raise LifecyclePublicationError(
            "change_plan_artifact_mismatch",
            "ChangePlan artifact is non-canonical or has the wrong binding",
        )
    computation_bytes = (path / _COMPUTATION_MANIFEST_PATH).read_bytes()
    computation_manifest = ComputationArtifactManifest.model_validate_json(
        computation_bytes
    )
    if (
        _canonical_json_bytes(computation_manifest.model_dump(mode="json"))
        != computation_bytes
        or computation_manifest.artifact_set_id
        != lifecycle.computation_artifact_set_id
        or computation_manifest.plan_id != lifecycle.plan_id
        or computation_manifest.pipeline_sha256 != lifecycle.pipeline_sha256
        or computation_manifest.governance_sha256
        != lifecycle.governance_sha256
        or computation_manifest.documents_sha256
        != lifecycle.documents_sha256
        or computation_manifest.chunks_sha256 != lifecycle.chunks_sha256
        or computation_manifest.embeddings_sha256
        != lifecycle.embeddings_sha256
    ):
        raise LifecyclePublicationError(
            "computation_manifest_artifact_mismatch",
            "computation manifest artifact is non-canonical or incorrectly bound",
        )
    embedding_rows = tuple(
        ComputedEmbedding.model_validate(item)
        for item in json.loads(
            (path / _EMBEDDING_ROWS_PATH).read_text(encoding="utf-8")
        )
    )
    if _payload_sha256(
        [item.model_dump(mode="json") for item in embedding_rows]
    ) != lifecycle.embeddings_sha256:
        raise LifecyclePublicationError(
            "embedding_rows_artifact_mismatch",
            "embedding row evidence does not match the computation manifest",
        )
    documents = tuple(
        DocumentRecord.model_validate(item)
        for item in json.loads(
            (path / "documents.json").read_text(encoding="utf-8")
        )
    )
    chunks = tuple(
        ChunkRecord.model_validate(item)
        for item in json.loads((path / "chunks.json").read_text(encoding="utf-8"))
    )
    parents = tuple(
        ChunkRecord.model_validate(item)
        for item in json.loads(
            (path / "parents.json").read_text(encoding="utf-8")
        )
    )
    document_ids = [item.doc_id for item in documents]
    indexed_chunk_ids = [item.chunk_id for item in chunks]
    parent_chunk_ids = [item.chunk_id for item in parents]
    chunks_by_id = {
        item.chunk_id: item for item in (*chunks, *parents)
    }
    if set(lifecycle.computation_chunk_order) != set(chunks_by_id):
        raise LifecyclePublicationError(
            "computation_chunk_order_mismatch",
            "lifecycle chunk order does not cover every target chunk exactly once",
        )
    computation_chunks = [
        chunks_by_id[chunk_id] for chunk_id in lifecycle.computation_chunk_order
    ]
    if (
        lifecycle.documents_sha256
        != _payload_sha256(
            [item.model_dump(mode="json") for item in documents]
        )
        or lifecycle.chunks_sha256
        != _payload_sha256(
            [
                item.model_dump(mode="json")
                for item in computation_chunks
            ]
        )
        or lifecycle.document_ids_sha256 != _payload_sha256(document_ids)
        or lifecycle.indexed_chunk_ids_sha256
        != _payload_sha256(indexed_chunk_ids)
        or lifecycle.parent_chunk_ids_sha256
        != _payload_sha256(parent_chunk_ids)
    ):
        raise LifecyclePublicationError(
            "lifecycle_artifact_binding_mismatch",
            "lifecycle manifest does not bind the complete target artifacts",
        )
    if [item.chunk_id for item in embedding_rows] != indexed_chunk_ids:
        raise LifecyclePublicationError(
            "embedding_row_order_mismatch",
            "embedding rows do not use the exact indexed chunk order",
        )
    with (path / "bm25_tokens.pkl").open("rb") as handle:
        token_rows = pickle.load(handle)
    if token_rows != [tokenize_for_bm25(item.text) for item in chunks]:
        raise LifecyclePublicationError(
            "bm25_row_mismatch",
            "BM25 rows do not match indexed chunk text and order",
        )
    index = faiss.deserialize_index(
        np.frombuffer(
            (path / "faiss.index").read_bytes(),
            dtype=np.uint8,
        ).copy()
    )
    if embedding_rows:
        expected_vectors = np.asarray(
            [item.vector for item in embedding_rows],
            dtype="float32",
        )
        expected_vectors = expected_vectors / np.linalg.norm(
            expected_vectors,
            axis=1,
            keepdims=True,
        )
        actual_vectors = np.vstack(
            [index.reconstruct(row) for row in range(index.ntotal)]
        )
        if not np.allclose(
            actual_vectors,
            expected_vectors,
            rtol=1e-6,
            atol=1e-6,
        ):
            raise LifecyclePublicationError(
                "faiss_row_mismatch",
                "FAISS rows do not match normalized embedding evidence",
            )
    document_id_set = set(document_ids)
    parent_id_set = set(parent_chunk_ids)
    if (
        any(item.doc_id not in document_id_set for item in (*chunks, *parents))
        or any(
            item.kind == "child"
            and item.parent_chunk_id not in parent_id_set
            for item in chunks
        )
    ):
        raise LifecyclePublicationError(
            "target_reference_invalid",
            "target chunks contain an invalid document or parent reference",
        )
    expected_documents = {
        item.document_id
        for item in lifecycle.source_bindings
        if item.canonical_document
    }
    expected_indexed = {
        chunk_id
        for item in lifecycle.source_bindings
        for chunk_id in item.indexed_chunk_ids
    }
    expected_parents = {
        chunk_id
        for item in lifecycle.source_bindings
        for chunk_id in item.parent_chunk_ids
    }
    if (
        expected_documents != set(document_ids)
        or expected_indexed != set(indexed_chunk_ids)
        or expected_parents != set(parent_chunk_ids)
    ):
        raise LifecyclePublicationError(
            "source_mapping_incomplete",
            "source bindings do not cover the complete target mapping",
        )
    deleted_documents = {
        value
        for item in lifecycle.tombstone_bindings
        for value in item.prior_document_ids
    }
    deleted_indexed = {
        value
        for item in lifecycle.tombstone_bindings
        for value in item.prior_indexed_chunk_ids
    }
    deleted_parents = {
        value
        for item in lifecycle.tombstone_bindings
        for value in item.prior_parent_chunk_ids
    }
    if (
        deleted_documents & set(document_ids)
        or deleted_indexed & set(indexed_chunk_ids)
        or deleted_parents & set(parent_chunk_ids)
    ):
        raise LifecyclePublicationError(
            "deleted_mapping_residual",
            "target snapshot still contains a tombstoned source mapping",
        )
    return lifecycle


def _manifest_sha256(path: Path) -> str:
    return _sha256((path / "manifest.json").read_bytes())


def _validate_existing(
    target: Path,
    expected: LifecycleIndexManifest,
) -> tuple[IndexManifest, str]:
    try:
        lifecycle = validate_incremental_index_directory(target)
        manifest = load_index_manifest(target / "manifest.json")
    except Exception:
        raise LifecyclePublicationError(
            "target_run_conflict",
            "target run ID exists but is not the expected immutable snapshot",
        ) from None
    if lifecycle.publication_id != expected.publication_id:
        raise LifecyclePublicationError(
            "target_run_conflict",
            "target run ID is already bound to different publication inputs",
        )
    return manifest, _manifest_sha256(target)


def build_incremental_index_version(
    *,
    root: Path,
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None,
    target_catalog: RevisionCatalogSnapshot,
    computation: IncrementalComputationResult,
    pipeline: PipelineConfiguration,
    profile_id: str = "lifecycle",
    activate: bool = False,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    failure_injector: FailureInjector | None = None,
) -> IncrementalPublicationResult:
    (
        plan,
        _base_catalog,
        target_catalog,
        computation,
        pipeline,
    ) = _strict_inputs(
        plan=plan,
        base_catalog=base_catalog,
        target_catalog=target_catalog,
        computation=computation,
        pipeline=pipeline,
    )
    root = Path(root).resolve()
    versions = root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    target = (versions / plan.target_index_run_id).resolve()
    if target.parent != versions.resolve():
        raise LifecyclePublicationError(
            "target_path_invalid",
            "target run path escapes the version root",
        )
    base_binding, base_lifecycle = _load_base_binding(root, plan)
    lifecycle = _lifecycle_manifest(
        plan=plan,
        computation=computation,
        pipeline=pipeline,
        profile_id=profile_id,
        base_binding=base_binding,
        base_lifecycle=base_lifecycle,
    )

    if target.exists():
        manifest, manifest_sha256 = _validate_existing(target, lifecycle)
        active = _active_identity(root)
        if active == (manifest.run_id, manifest_sha256):
            return IncrementalPublicationResult(
                status="REUSED",
                activated=True,
                index_manifest=manifest,
                lifecycle_manifest=lifecycle,
                manifest_sha256=manifest_sha256,
            )

    start = started_at or datetime.now(timezone.utc)
    finish = finished_at or datetime.now(timezone.utc)
    if (
        start.tzinfo is None
        or start.utcoffset() is None
        or finish.tzinfo is None
        or finish.utcoffset() is None
        or finish < start
    ):
        raise LifecyclePublicationError(
            "publication_time_invalid",
            "publication timestamps must be ordered and timezone-aware",
        )
    artifacts, dimension = _artifact_bytes(
        plan,
        target_catalog,
        computation,
        pipeline,
        lifecycle,
    )
    manifest = _index_manifest(
        plan=plan,
        target=target_catalog,
        computation=computation,
        pipeline=pipeline,
        profile_id=profile_id,
        artifacts=artifacts,
        dimension=dimension,
        started_at=start,
        finished_at=finish,
    )
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{plan.target_index_run_id}.staging-",
            dir=versions,
        )
    )
    stage.rmdir()
    installed_here = False
    status: Literal["BUILT", "REUSED"] = "BUILT"
    try:
        _write_stage(
            stage=stage,
            artifacts=artifacts,
            manifest=manifest,
            injector=failure_injector,
        )
        validate_incremental_index_directory(stage)
        with publication_lock(root):
            if target.exists():
                manifest, manifest_sha256 = _validate_existing(target, lifecycle)
                status = "REUSED"
            else:
                _require_expected_active(root, base_binding)
                _hit(failure_injector, "version_install")
                atomic_directory_move(stage, target)
                _sync_directory(versions)
                installed_here = True
                manifest_sha256 = _manifest_sha256(target)
            if activate:
                _require_expected_active(root, base_binding)
                try:
                    pointer = activate_version(
                        root,
                        plan.target_index_run_id,
                        _lock_held=True,
                        before_replace=lambda: _hit(
                            failure_injector,
                            "active_pointer_replace",
                        ),
                    )
                except Exception:
                    if (
                        installed_here
                        and _active_identity(root)
                        != (plan.target_index_run_id, manifest_sha256)
                    ):
                        shutil.rmtree(target)
                        _sync_directory(versions)
                        installed_here = False
                    raise
                manifest_sha256 = pointer.manifest_sha256
        return IncrementalPublicationResult(
            status=status,
            activated=activate,
            index_manifest=manifest,
            lifecycle_manifest=lifecycle,
            manifest_sha256=manifest_sha256,
        )
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def execute_incremental_publication(
    *,
    root: Path,
    plan: ChangePlan,
    base_catalog: RevisionCatalogSnapshot | None,
    target_catalog: RevisionCatalogSnapshot,
    cache: PersistentComputationCache,
    pipeline: PipelineConfiguration,
    materializer: RevisionContentMaterializer,
    embed_text: EmbedText,
    validate_files: Callable[[], None],
    profile_id: str = "lifecycle",
    activate: bool = False,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    failure_injector: FailureInjector | None = None,
) -> IncrementalPublicationResult:
    _hit(failure_injector, "file_validation")
    try:
        validate_files()
    except Exception:
        raise LifecyclePublicationError(
            "file_validation_failed",
            "source file validation failed before incremental computation",
        ) from None
    computation = execute_incremental_computation(
        plan=plan,
        base_catalog=base_catalog,
        target_catalog=target_catalog,
        cache=cache,
        pipeline=pipeline,
        materializer=materializer,
        embed_text=embed_text,
        checkpoint=lambda point: _hit(failure_injector, point),
    )
    return build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=base_catalog,
        target_catalog=target_catalog,
        computation=computation,
        pipeline=pipeline,
        profile_id=profile_id,
        activate=activate,
        started_at=started_at,
        finished_at=finished_at,
        failure_injector=failure_injector,
    )


def retrieval_fingerprint(
    *,
    root: Path,
    run_id: str,
    requests: Iterable[SearchRequest],
    embed_text: EmbedText | None = None,
) -> str:
    from app.retrieval.pipeline import HybridRetrievalPipeline
    from app.retrieval.snapshot import V2IndexSnapshot

    snapshot = V2IndexSnapshot.load(root, run_id)
    pipeline = HybridRetrievalPipeline(snapshot, embed_text=embed_text)
    payload = []
    for request in requests:
        strict_request = SearchRequest.model_validate(
            request.model_dump(mode="json")
        )
        result = pipeline.search(strict_request)
        payload.append(
            {
                "query": strict_request.query,
                "mode": strict_request.mode,
                "stop_reason": result.stop_reason,
                "hits": [
                    {
                        "chunk_id": hit.chunk_id,
                        "doc_id": hit.doc_id,
                        "parent_chunk_id": hit.parent_chunk_id,
                        "source_path": hit.source_path,
                        "section_path": hit.section_path,
                        "locator": (
                            None
                            if hit.locator is None
                            else hit.locator.model_dump(mode="json")
                        ),
                        "context_from_parent": hit.context_from_parent,
                    }
                    for hit in result.hits
                ],
            }
        )
    return _payload_sha256(payload)


def rollback_index_version(
    *,
    root: Path,
    target_run_id: str,
    expected_current_run_id: str,
    requests: Iterable[SearchRequest] = (),
    expected_query_fingerprint_sha256: str | None = None,
    embed_text: EmbedText | None = None,
    failure_injector: FailureInjector | None = None,
    audit_failure_injector: Callable[[], None] | None = None,
    occurred_at: datetime | None = None,
) -> RollbackResult:
    root = Path(root).resolve()
    request_values = tuple(requests)
    if bool(request_values) != bool(expected_query_fingerprint_sha256):
        raise LifecyclePublicationError(
            "rollback_probe_invalid",
            "rollback query requests and expected fingerprint must be supplied together",
        )
    with publication_lock(root):
        _recover_pending_rollback_locked(root)
        current = load_index_version(root)
        if current.manifest.run_id != expected_current_run_id:
            raise LifecyclePublicationError(
                "rollback_source_conflict",
                "active version changed before rollback",
            )
        target = load_index_version(root, target_run_id)
        validate_incremental_index_directory(target.path)
        query_sha256 = None
        if request_values:
            query_sha256 = retrieval_fingerprint(
                root=root,
                run_id=target_run_id,
                requests=request_values,
                embed_text=embed_text,
            )
            if query_sha256 != expected_query_fingerprint_sha256:
                raise LifecyclePublicationError(
                    "rollback_query_mismatch",
                    "candidate rollback snapshot does not restore fixed-query citations",
                )
        event = _build_rollback_audit_event(
            root=root,
            from_run_id=current.manifest.run_id,
            from_manifest_sha256=current.manifest_sha256,
            to_run_id=target.manifest.run_id,
            to_manifest_sha256=target.manifest_sha256,
            query_fingerprint_sha256=query_sha256,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
        _write_rollback_intent(root, event)
        try:
            pointer = activate_version(
                root,
                target_run_id,
                activated_at=occurred_at,
                _lock_held=True,
                before_replace=lambda: _hit(
                    failure_injector,
                    "active_pointer_replace",
                ),
            )
        except Exception:
            _remove_rollback_intent(root)
            raise
        try:
            if audit_failure_injector is not None:
                audit_failure_injector()
            _append_rollback_audit_event(root, event)
            _remove_rollback_intent(root)
        except Exception:
            raise LifecyclePublicationError(
                "rollback_outcome_unknown",
                "rollback pointer changed but audit completion requires recovery",
            ) from None
        return RollbackResult(
            pointer_manifest_sha256=pointer.manifest_sha256,
            query_fingerprint_sha256=query_sha256,
            audit_event=event,
        )


def recover_pending_rollback(
    *,
    root: Path,
) -> RollbackAuditEvent | None:
    root = Path(root).resolve()
    with publication_lock(root):
        return _recover_pending_rollback_locked(root)


def _recover_pending_rollback_locked(root: Path) -> RollbackAuditEvent | None:
    intent = _load_rollback_intent(root)
    if intent is None:
        return None
    active = load_index_version(root)
    event = intent.audit_event
    active_identity = (active.manifest.run_id, active.manifest_sha256)
    target_identity = (event.to_run_id, event.to_manifest_sha256)
    source_identity = (event.from_run_id, event.from_manifest_sha256)
    if active_identity == target_identity:
        _append_rollback_audit_event(root, event)
        _remove_rollback_intent(root)
        return event
    if active_identity == source_identity:
        _remove_rollback_intent(root)
        return None
    raise LifecyclePublicationError(
        "rollback_recovery_conflict",
        "active pointer does not match the pending rollback transition",
    )


def _build_rollback_audit_event(
    *,
    root: Path,
    from_run_id: str,
    from_manifest_sha256: str,
    to_run_id: str,
    to_manifest_sha256: str,
    query_fingerprint_sha256: str | None,
    occurred_at: datetime,
) -> RollbackAuditEvent:
    audit_dir = root / "audit"
    audit_dir.mkdir(exist_ok=True)
    previous = _last_rollback_audit_event(root)
    payload = {
        "schema_version": "lifecycle_rollback_audit_v1",
        "previous_event_sha256": (
            None if previous is None else previous.event_sha256
        ),
        "operation": "ROLLBACK",
        "from_run_id": from_run_id,
        "from_manifest_sha256": from_manifest_sha256,
        "to_run_id": to_run_id,
        "to_manifest_sha256": to_manifest_sha256,
        "occurred_at": occurred_at,
        "old_data_visibility_restored": True,
        "query_fingerprint_sha256": query_fingerprint_sha256,
    }
    unhashed = RollbackAuditEvent.model_construct(
        event_sha256="0" * 64,
        **payload,
    )
    event = RollbackAuditEvent(
        event_sha256=_sha256(
            _canonical_json_bytes(
                unhashed.model_dump(mode="json", exclude={"event_sha256"})
            )
        ),
        **payload,
    )
    return event


def _rollback_audit_paths(root: Path) -> tuple[Path, Path, Path]:
    audit_dir = root / "audit"
    return (
        audit_dir,
        audit_dir / "rollback.jsonl",
        audit_dir / "rollback.intent.json",
    )


def _last_rollback_audit_event(root: Path) -> RollbackAuditEvent | None:
    audit_dir, path, _ = _rollback_audit_paths(root)
    if not path.exists():
        return None
    _safe_file(path, audit_dir)
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise LifecyclePublicationError(
            "rollback_audit_too_large",
            "rollback audit exceeds its bounded local size",
        )
    lines = raw.splitlines()
    if not lines or raw != b"\n".join(lines) + b"\n":
        raise LifecyclePublicationError(
            "rollback_audit_invalid",
            "rollback audit is not canonical JSONL",
        )
    previous: RollbackAuditEvent | None = None
    for line in lines:
        event = RollbackAuditEvent.model_validate_json(line)
        if event.previous_event_sha256 != (
            None if previous is None else previous.event_sha256
        ):
            raise LifecyclePublicationError(
                "rollback_audit_chain_invalid",
                "rollback audit hash chain is invalid",
            )
        previous = event
    return previous


def _append_rollback_audit_event(
    root: Path,
    event: RollbackAuditEvent,
) -> RollbackAuditEvent:
    audit_dir, path, _ = _rollback_audit_paths(root)
    audit_dir.mkdir(exist_ok=True)
    previous = _last_rollback_audit_event(root)
    if previous is not None and previous.event_sha256 == event.event_sha256:
        return previous
    if event.previous_event_sha256 != (
        None if previous is None else previous.event_sha256
    ):
        raise LifecyclePublicationError(
            "rollback_audit_chain_conflict",
            "rollback audit event does not extend the current chain",
        )
    existing = path.read_bytes() if path.exists() else b""
    content = existing + _canonical_json_bytes(event.model_dump(mode="json")) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".rollback.audit.",
        suffix=".tmp",
        dir=audit_dir,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            _safe_file(path, audit_dir)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    _sync_directory(audit_dir)
    return event


def _write_rollback_intent(root: Path, event: RollbackAuditEvent) -> None:
    audit_dir, _, path = _rollback_audit_paths(root)
    audit_dir.mkdir(exist_ok=True)
    intent = RollbackIntent(audit_event=event)
    content = _canonical_json_bytes(intent.model_dump(mode="json")) + b"\n"
    if path.exists():
        _safe_file(path, audit_dir)
        existing = RollbackIntent.model_validate_json(path.read_bytes())
        if existing == intent:
            return
        raise LifecyclePublicationError(
            "rollback_intent_conflict",
            "a different rollback transition is pending recovery",
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".rollback.intent.",
        suffix=".tmp",
        dir=audit_dir,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    _sync_directory(audit_dir)


def _load_rollback_intent(root: Path) -> RollbackIntent | None:
    audit_dir, _, path = _rollback_audit_paths(root)
    if not path.exists():
        return None
    _safe_file(path, audit_dir)
    raw = path.read_bytes()
    intent = RollbackIntent.model_validate_json(raw)
    if raw != _canonical_json_bytes(intent.model_dump(mode="json")) + b"\n":
        raise LifecyclePublicationError(
            "rollback_intent_invalid",
            "rollback recovery intent is not canonical",
        )
    return intent


def _remove_rollback_intent(root: Path) -> None:
    audit_dir, _, path = _rollback_audit_paths(root)
    if not path.exists():
        return
    _safe_file(path, audit_dir)
    path.unlink()
    _sync_directory(audit_dir)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "BaseIndexBinding",
    "IncrementalPublicationResult",
    "LifecycleIndexManifest",
    "LifecyclePublicationError",
    "PublicationFailurePoint",
    "RollbackAuditEvent",
    "RollbackIntent",
    "RollbackResult",
    "SourceIndexBinding",
    "TombstoneIndexBinding",
    "build_incremental_index_version",
    "execute_incremental_publication",
    "load_lifecycle_manifest",
    "retrieval_fingerprint",
    "recover_pending_rollback",
    "rollback_index_version",
    "serialize_lifecycle_manifest",
    "validate_incremental_index_directory",
]
