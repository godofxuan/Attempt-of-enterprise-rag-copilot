from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

import pytest

import app.indexing.incremental_computation as computation_module
from app.domain.documents import DocumentRecord, DocumentVersion
from app.indexing.change_plan import build_change_plan
from app.indexing.computation_cache import (
    CacheWriteResult,
    ComponentFingerprint,
    EmbeddingFingerprint,
    NormalizedContentArtifact,
    ParsedContentArtifact,
    PersistentComputationCache,
    cache_key_sha256,
    cache_payload_sha256,
)
from app.indexing.incremental_computation import (
    IncrementalComputationError,
    IncrementalComputationResult,
    PipelineConfiguration,
    execute_incremental_computation,
)
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.revision_catalog import (
    DocumentRevision,
    PersistentRevisionCatalog,
    RevisionCatalogSnapshot,
    RevisionMaterialization,
    empty_revision_catalog_snapshot,
    revision_catalog_sha256,
)
from app.ingestion.source_events import SourceEvent, SourceEventLedger


NOW = datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc)
TEXT = "Employees receive ten days of annual leave."
NORMALIZED_SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()


def _catalog_and_plan(
    root: Path,
    *,
    acl_groups: tuple[str, ...] = ("group-employees",),
    event_id: str = "evt-leave-1",
    catalog_name: str = "catalog",
    tenant_id: str = "tenant-a",
    parser_version: str = "1",
    normalizer_version: str = "1",
):
    event = SourceEvent(
        event_id=event_id,
        operation="UPSERT",
        tenant_id=tenant_id,
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policies/leave.md",
        declared_media_type="text/markdown",
        content_sha256="1" * 64,
        actor_pseudonym="operator-a",
        acl_groups=acl_groups,
    )
    catalog = PersistentRevisionCatalog((root / catalog_name).absolute())
    catalog.apply(
        event,
        materialization=RevisionMaterialization(
            document_id="doc-leave",
            asset_id=f"asset_{'2' * 32}",
            parent_event_id=event.event_id,
            content_sha256=event.content_sha256,
            normalized_sha256=NORMALIZED_SHA,
            parser_name="markdown",
            parser_version=parser_version,
            normalizer_version=normalizer_version,
        ),
    )
    target = catalog.snapshot()
    plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=target,
        base_index_run_id=None,
        target_index_run_id="index-target",
    )
    return target, plan


def _duplicate_catalog_and_plan(root: Path):
    catalog = PersistentRevisionCatalog((root / "duplicate-catalog").absolute())
    for suffix, source_key in (("a", "policy/a"), ("b", "policy/b")):
        event = SourceEvent(
            event_id=f"evt-{suffix}",
            operation="UPSERT",
            tenant_id="tenant-a",
            region="ap-east",
            source_system="sharepoint",
            source_key=source_key,
            occurred_at=NOW,
            content_relpath=f"{source_key}.md",
            declared_media_type="text/markdown",
            content_sha256="1" * 64,
            actor_pseudonym="operator-a",
            acl_groups=("group-employees",),
        )
        catalog.apply(
            event,
            materialization=RevisionMaterialization(
                document_id=f"doc-{suffix}",
                asset_id=f"asset_{suffix * 32}",
                parent_event_id=event.event_id,
                content_sha256=event.content_sha256,
                normalized_sha256=NORMALIZED_SHA,
                parser_name="markdown",
                parser_version="1",
                normalizer_version="1",
            ),
        )
    target = catalog.snapshot()
    return target, build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=target,
        base_index_run_id=None,
        target_index_run_id="index-target",
    )


def _tombstone_catalog_and_plan(root: Path):
    catalog = PersistentRevisionCatalog((root / "tombstone-catalog").absolute())
    upsert = SourceEvent(
        event_id="evt-upsert",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policy/leave.md",
        declared_media_type="text/markdown",
        content_sha256="1" * 64,
        actor_pseudonym="operator-a",
        acl_groups=("group-employees",),
    )
    accepted = catalog.apply(
        upsert,
        materialization=RevisionMaterialization(
            document_id="doc-leave",
            asset_id=f"asset_{'2' * 32}",
            parent_event_id=upsert.event_id,
            content_sha256=upsert.content_sha256,
            normalized_sha256=NORMALIZED_SHA,
            parser_name="markdown",
            parser_version="1",
            normalizer_version="1",
        ),
    )
    catalog.apply(
        SourceEvent(
            event_id="evt-delete",
            operation="DELETE",
            tenant_id="tenant-a",
            region="ap-east",
            source_system="sharepoint",
            source_key="policy/leave",
            expected_revision_id=accepted.revision.revision_id,
            occurred_at=NOW,
            actor_pseudonym="operator-a",
        ),
        materialization=None,
    )
    target = catalog.snapshot()
    return target, build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=target,
        base_index_run_id=None,
        target_index_run_id="index-target",
    )


def _governance_update_catalog_and_plan(root: Path):
    catalog = PersistentRevisionCatalog(
        (root / "governance-update-catalog").absolute()
    )
    first = SourceEvent(
        event_id="evt-governance-1",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policy/leave.md",
        declared_media_type="text/markdown",
        content_sha256="1" * 64,
        actor_pseudonym="operator-a",
        acl_groups=("group-employees",),
    )
    accepted = catalog.apply(
        first,
        materialization=RevisionMaterialization(
            document_id="doc-leave",
            asset_id=f"asset_{'2' * 32}",
            parent_event_id=first.event_id,
            content_sha256=first.content_sha256,
            normalized_sha256=NORMALIZED_SHA,
            parser_name="markdown",
            parser_version="1",
            normalizer_version="1",
        ),
    )
    base = catalog.snapshot()
    second = SourceEvent(
        event_id="evt-governance-2",
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        expected_revision_id=accepted.revision.revision_id,
        occurred_at=NOW + timedelta(seconds=1),
        content_relpath="policy/leave.md",
        declared_media_type="text/markdown",
        content_sha256="1" * 64,
        actor_pseudonym="operator-a",
        acl_groups=("group-legal",),
    )
    catalog.apply(
        second,
        materialization=RevisionMaterialization(
            document_id="doc-leave",
            asset_id=f"asset_{'2' * 32}",
            parent_event_id=second.event_id,
            content_sha256=second.content_sha256,
            normalized_sha256=NORMALIZED_SHA,
            parser_name="markdown",
            parser_version="1",
            normalizer_version="1",
        ),
    )
    target = catalog.snapshot()
    plan = build_change_plan(
        base=base,
        target=target,
        base_index_run_id="index-base",
        target_index_run_id="index-target",
    )
    return base, target, plan


def _ratio_catalogs(root: Path):
    del root
    ledger = SourceEventLedger()
    revisions: dict[str, DocumentRevision] = {}
    content_by_sha256: dict[str, str] = {}
    current_revision_ids: dict[int, str] = {}

    def apply_in_memory(
        event: SourceEvent,
        materialization: RevisionMaterialization,
    ) -> DocumentRevision:
        application = ledger.apply(event)
        head = next(
            item
            for item in ledger.snapshot().source_heads
            if (item.source_system, item.source_key)
            == (event.source_system, event.source_key)
        )
        revision = DocumentRevision(
            revision_id=application.receipt.resulting_revision_id,
            previous_revision_id=application.receipt.previous_revision_id,
            event_id=event.event_id,
            event_payload_sha256=application.receipt.payload_sha256,
            operation=event.operation,
            source_system=event.source_system,
            source_key=event.source_key,
            tenant_id=event.tenant_id,
            region=head.region,
            acl_groups=head.acl_groups,
            actor_pseudonym=event.actor_pseudonym,
            occurred_at=event.occurred_at,
            declared_media_type=event.declared_media_type,
            content_sha256=event.content_sha256,
            materialization=materialization,
            deleted=False,
        )
        revisions[revision.revision_id] = revision
        return revision

    def snapshot() -> RevisionCatalogSnapshot:
        return RevisionCatalogSnapshot(
            ledger=ledger.snapshot(),
            revisions=tuple(
                sorted(revisions.values(), key=lambda item: item.revision_id)
            ),
        )

    for ordinal in range(100):
        text = f"Policy {ordinal:03d} baseline content."
        content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        content_by_sha256[content_sha256] = text
        event = SourceEvent(
            event_id=f"evt-ratio-base-{ordinal:03d}",
            operation="UPSERT",
            tenant_id="tenant-a",
            region="ap-east",
            source_system="sharepoint",
            source_key=f"policy/{ordinal:03d}",
            occurred_at=NOW + timedelta(minutes=ordinal),
            content_relpath=f"policy/{ordinal:03d}.md",
            declared_media_type="text/markdown",
            content_sha256=content_sha256,
            actor_pseudonym="operator-a",
            acl_groups=("group-employees",),
        )
        revision = apply_in_memory(
            event,
            RevisionMaterialization(
                document_id=f"doc-{ordinal:03d}",
                asset_id=f"asset_{content_sha256[:32]}",
                parent_event_id=event.event_id,
                content_sha256=content_sha256,
                normalized_sha256=content_sha256,
                parser_name="markdown",
                parser_version="1",
                normalizer_version="1",
            ),
        )
        current_revision_ids[ordinal] = revision.revision_id
    base = snapshot()
    targets = {0: base}
    for ordinal in range(20):
        text = f"Policy {ordinal:03d} revised content."
        content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        content_by_sha256[content_sha256] = text
        event = SourceEvent(
            event_id=f"evt-ratio-change-{ordinal:03d}",
            operation="UPSERT",
            tenant_id="tenant-a",
            region="ap-east",
            source_system="sharepoint",
            source_key=f"policy/{ordinal:03d}",
            expected_revision_id=current_revision_ids[ordinal],
            occurred_at=NOW + timedelta(days=1, minutes=ordinal),
            content_relpath=f"policy/{ordinal:03d}.md",
            declared_media_type="text/markdown",
            content_sha256=content_sha256,
            actor_pseudonym="operator-a",
            acl_groups=("group-employees",),
        )
        revision = apply_in_memory(
            event,
            RevisionMaterialization(
                document_id=f"doc-{ordinal:03d}",
                asset_id=f"asset_{content_sha256[:32]}",
                parent_event_id=event.event_id,
                content_sha256=content_sha256,
                normalized_sha256=content_sha256,
                parser_name="markdown",
                parser_version="1",
                normalizer_version="1",
            ),
        )
        current_revision_ids[ordinal] = revision.revision_id
        if ordinal + 1 in {1, 5, 20}:
            targets[ordinal + 1] = snapshot()
    return base, targets, content_by_sha256


class FixtureMaterializer:
    def __init__(
        self,
        *,
        parser_digest: str = "3" * 64,
        parser_version: str = "1",
    ) -> None:
        self.parse_calls = 0
        self.normalize_calls = 0
        self.materialize_calls = 0
        self.parser_digest = parser_digest
        self.parser_version = parser_version

    def parser_fingerprint(
        self,
        revision: DocumentRevision,
    ) -> ComponentFingerprint:
        return ComponentFingerprint(
            name="markdown",
            semantic_version=self.parser_version,
            implementation_sha256=self.parser_digest,
            dependency_versions=("stdlib=3.13",),
        )

    def parse_content(
        self,
        revision: DocumentRevision,
    ) -> ParsedContentArtifact:
        self.parse_calls += 1
        return ParsedContentArtifact(text=TEXT)

    def normalize_content(
        self,
        revision: DocumentRevision,
        parsed: ParsedContentArtifact,
    ) -> NormalizedContentArtifact:
        self.normalize_calls += 1
        return NormalizedContentArtifact(
            title="Leave",
            text=parsed.text,
            normalized_sha256=NORMALIZED_SHA,
        )

    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        self.materialize_calls += 1
        assert revision.materialization is not None
        return DocumentRecord(
            doc_id=revision.materialization.document_id,
            title=normalized.title,
            source_type="policy",
            source_path="private-asset",
            format="markdown",
            department="People",
            filed_department="People",
            policy_id="leave",
            region=revision.region,
            tenant_id=revision.tenant_id,
            acl_groups=list(revision.acl_groups),
            document_version=DocumentVersion(
                version_id=revision.revision_id,
                version="1",
                status="active",
                effective_from=date(2026, 1, 1),
                authority_level=80,
            ),
            authority_level=80,
            checksum=revision.content_sha256,
            normalized_text_hash=normalized.normalized_sha256,
            ingested_at=revision.occurred_at,
            parser_name=revision.materialization.parser_name,
            parser_version=revision.materialization.parser_version,
            text=normalized.text,
            sections=list(normalized.sections),
            tables=list(normalized.tables),
            parse_warnings=list(normalized.parse_warnings),
            fact_ids=[],
            variant="canonical",
        )


class FixtureEmbedder:
    def __init__(self, *, dimension: int = 4) -> None:
        self.calls = 0
        self.dimension = dimension

    def __call__(self, text: str) -> list[float]:
        self.calls += 1
        return [float(value) for value in range(1, self.dimension + 1)]


class DuplicateMaterializer(FixtureMaterializer):
    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        document = super().materialize_document(revision, normalized)
        version = document.document_version.model_copy(
            update={"version_id": "shared-version"}
        )
        return document.model_copy(
            update={
                "document_version": version,
                "variant": (
                    "authoritative"
                    if revision.source_key == "policy/a"
                    else "duplicate"
                ),
                "policy_id": None,
            }
        )


class StaleDocumentMaterializer(FixtureMaterializer):
    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        document = super().materialize_document(revision, normalized)
        return document.model_copy(update={"text": "stale cached body"})


class DepartmentMaterializer(FixtureMaterializer):
    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        document = super().materialize_document(revision, normalized)
        return document.model_copy(
            update={
                "department": "Legal",
                "filed_department": "Legal",
            }
        )


class RatioMaterializer(FixtureMaterializer):
    def __init__(self, content_by_sha256: dict[str, str]) -> None:
        super().__init__()
        self.content_by_sha256 = content_by_sha256

    def parse_content(
        self,
        revision: DocumentRevision,
    ) -> ParsedContentArtifact:
        self.parse_calls += 1
        assert revision.content_sha256 is not None
        return ParsedContentArtifact(
            text=self.content_by_sha256[revision.content_sha256]
        )

    def normalize_content(
        self,
        revision: DocumentRevision,
        parsed: ParsedContentArtifact,
    ) -> NormalizedContentArtifact:
        self.normalize_calls += 1
        return NormalizedContentArtifact(
            title=revision.source_key,
            text=parsed.text,
            normalized_sha256=hashlib.sha256(
                parsed.text.encode("utf-8")
            ).hexdigest(),
        )

    def materialize_document(
        self,
        revision: DocumentRevision,
        normalized: NormalizedContentArtifact,
    ) -> DocumentRecord:
        document = super().materialize_document(revision, normalized)
        return document.model_copy(
            update={
                "policy_id": revision.source_key.replace("/", "-"),
                "source_path": f"private/{revision.source_key}.md",
            }
        )


class MemoryComputationCache:
    def __init__(self) -> None:
        self.entries: dict[str, object] = {}

    def _load(self, key):
        return self.entries.get(cache_key_sha256(key))

    def _store(self, key, payload) -> CacheWriteResult:
        key_sha256 = cache_key_sha256(key)
        existing = self.entries.get(key_sha256)
        if existing is None:
            self.entries[key_sha256] = payload
            status = "STORED"
        else:
            assert existing == payload
            status = "REUSED"
        return CacheWriteResult(
            status=status,
            key_sha256=key_sha256,
            payload_sha256=cache_payload_sha256(payload),
            serialization_seconds=0.0,
        )

    load_parsed = _load
    load_normalized = _load
    load_chunks = _load
    load_embedding = _load
    store_parsed = _store
    store_normalized = _store
    store_chunks = _store
    store_embedding = _store


def _pipeline(
    *,
    normalizer_digest: str = "4" * 64,
    normalizer_version: str = "1",
    chunker_config: ChunkerConfig | None = None,
    model_digest: str = "7" * 64,
    model_identifier: str = "fixture-4d",
    dimension: int = 4,
) -> PipelineConfiguration:
    return PipelineConfiguration(
        materializer=ComponentFingerprint(
            name="fixture-document-materializer",
            semantic_version="1",
            implementation_sha256="2" * 64,
            dependency_versions=("pydantic=2",),
        ),
        governance=ComponentFingerprint(
            name="enterprise-document-governance",
            semantic_version="1",
            implementation_sha256="3" * 64,
            dependency_versions=("pydantic=2",),
        ),
        normalizer=ComponentFingerprint(
            name="enterprise-normalizer",
            semantic_version=normalizer_version,
            implementation_sha256=normalizer_digest,
            dependency_versions=("pydantic=2",),
        ),
        chunker=ComponentFingerprint(
            name="enterprise-chunker",
            semantic_version="1",
            implementation_sha256="5" * 64,
            dependency_versions=("pydantic=2",),
        ),
        chunker_config=chunker_config
        or ChunkerConfig(mode="fixed", chunk_size=200, overlap=20),
        embedding=EmbeddingFingerprint(
            component=ComponentFingerprint(
                name="fixture-embedder",
                semantic_version="1",
                implementation_sha256="6" * 64,
            ),
            backend="deterministic-test",
            model_identifier=model_identifier,
            model_sha256=model_digest,
            dimension=dimension,
            normalization="none",
        ),
    )


def test_exact_replay_reuses_all_content_computation_and_reruns_governance(
    tmp_path: Path,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    cache = PersistentComputationCache((tmp_path / "cache").absolute())
    materializer = FixtureMaterializer()
    embedder = FixtureEmbedder()

    first = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=embedder,
    )
    second = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=embedder,
    )

    assert first.stats.parsed_misses == first.stats.normalized_misses == 1
    assert first.stats.chunk_misses == 1
    assert first.stats.embedding_misses == 1
    assert first.measurements.parse_calls == 1
    assert first.measurements.normalize_calls == 1
    assert first.measurements.chunk_calls == 1
    assert first.measurements.embedding_calls == 1
    assert second.stats.parsed_hits == second.stats.normalized_hits == 1
    assert second.stats.chunk_hits == 1
    assert second.stats.embedding_hits == 1
    assert second.measurements.parse_calls == 0
    assert second.measurements.normalize_calls == 0
    assert second.measurements.chunk_calls == 0
    assert second.measurements.embedding_calls == 0
    assert first.measurements.artifact_serialization_seconds >= 0.0
    assert first.measurements.total_wall_seconds >= (
        first.measurements.artifact_serialization_seconds
    )
    assert first.artifact_manifest == second.artifact_manifest
    assert materializer.parse_calls == materializer.normalize_calls == 1
    assert materializer.materialize_calls == 2
    assert embedder.calls == 1
    assert second.documents[0].acl_groups == ["group-employees"]
    assert second.chunks[0].acl_groups == ["group-employees"]


def test_pipeline_changes_invalidate_only_the_changed_stage_and_downstream(
    tmp_path: Path,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    cache = PersistentComputationCache((tmp_path / "cache").absolute())
    embedder = FixtureEmbedder()
    original = FixtureMaterializer()

    execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=original,
        embed_text=embedder,
    )

    parser_changed = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(parser_digest="8" * 64),
        embed_text=embedder,
    )
    assert parser_changed.stats.parsed_misses == 1
    assert parser_changed.stats.normalized_misses == 1
    assert parser_changed.stats.chunk_misses == 1
    assert parser_changed.stats.embedding_misses == 1

    normalizer_changed = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(normalizer_digest="9" * 64),
        materializer=FixtureMaterializer(parser_digest="8" * 64),
        embed_text=embedder,
    )
    assert normalizer_changed.stats.parsed_hits == 1
    assert normalizer_changed.stats.normalized_misses == 1
    assert normalizer_changed.stats.chunk_misses == 1
    assert normalizer_changed.stats.embedding_misses == 1

    changed_config = ChunkerConfig(mode="fixed", chunk_size=100, overlap=10)
    chunker_changed = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(
            normalizer_digest="9" * 64,
            chunker_config=changed_config,
        ),
        materializer=FixtureMaterializer(parser_digest="8" * 64),
        embed_text=embedder,
    )
    assert chunker_changed.stats.parsed_hits == 1
    assert chunker_changed.stats.normalized_hits == 1
    assert chunker_changed.stats.chunk_misses == 1
    assert chunker_changed.stats.embedding_misses == 1

    model_changed = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(
            normalizer_digest="9" * 64,
            chunker_config=changed_config,
            model_digest="a" * 64,
        ),
        materializer=FixtureMaterializer(parser_digest="8" * 64),
        embed_text=embedder,
    )
    assert model_changed.stats.parsed_hits == 1
    assert model_changed.stats.normalized_hits == 1
    assert model_changed.stats.chunk_hits == 1
    assert model_changed.stats.embedding_misses == 1


def test_semantic_versions_model_dimension_and_tenant_invalidate_end_to_end(
    tmp_path: Path,
) -> None:
    baseline_target, baseline_plan = _catalog_and_plan(
        tmp_path,
        catalog_name="matrix-baseline",
    )
    cache = PersistentComputationCache((tmp_path / "cache-matrix").absolute())
    execute_incremental_computation(
        plan=baseline_plan,
        target_catalog=baseline_target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )

    parser_target, parser_plan = _catalog_and_plan(
        tmp_path,
        event_id="evt-parser-v2",
        catalog_name="matrix-parser-v2",
        parser_version="2",
    )
    parser_changed = execute_incremental_computation(
        plan=parser_plan,
        target_catalog=parser_target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(parser_version="2"),
        embed_text=FixtureEmbedder(),
    )
    assert parser_changed.stats.parsed_misses == 1
    assert parser_changed.stats.normalized_misses == 1
    assert parser_changed.stats.chunk_misses == 1
    assert parser_changed.stats.embedding_misses == 1

    normalizer_target, normalizer_plan = _catalog_and_plan(
        tmp_path,
        event_id="evt-normalizer-v2",
        catalog_name="matrix-normalizer-v2",
        normalizer_version="2",
    )
    normalizer_changed = execute_incremental_computation(
        plan=normalizer_plan,
        target_catalog=normalizer_target,
        cache=cache,
        pipeline=_pipeline(normalizer_version="2"),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )
    assert normalizer_changed.stats.parsed_hits == 1
    assert normalizer_changed.stats.normalized_misses == 1
    assert normalizer_changed.stats.chunk_misses == 1
    assert normalizer_changed.stats.embedding_misses == 1

    tenant_target, tenant_plan = _catalog_and_plan(
        tmp_path,
        event_id="evt-tenant-b",
        catalog_name="matrix-tenant-b",
        tenant_id="tenant-b",
    )
    tenant_changed = execute_incremental_computation(
        plan=tenant_plan,
        target_catalog=tenant_target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )
    assert tenant_changed.stats.parsed_misses == 1
    assert tenant_changed.stats.normalized_misses == 1
    assert tenant_changed.stats.chunk_misses == 1
    assert tenant_changed.stats.embedding_misses == 1

    model_changed = execute_incremental_computation(
        plan=baseline_plan,
        target_catalog=baseline_target,
        cache=cache,
        pipeline=_pipeline(model_identifier="fixture-4d-v2"),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )
    assert model_changed.stats.parsed_hits == 1
    assert model_changed.stats.normalized_hits == 1
    assert model_changed.stats.chunk_hits == 1
    assert model_changed.stats.embedding_misses == 1

    dimension_changed = execute_incremental_computation(
        plan=baseline_plan,
        target_catalog=baseline_target,
        cache=cache,
        pipeline=_pipeline(dimension=3),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(dimension=3),
    )
    assert dimension_changed.stats.parsed_hits == 1
    assert dimension_changed.stats.normalized_hits == 1
    assert dimension_changed.stats.chunk_hits == 1
    assert dimension_changed.stats.embedding_misses == 1
    assert len(dimension_changed.embeddings[0].vector) == 3


def test_change_ratios_recompute_only_changed_sources(
    tmp_path: Path,
) -> None:
    base, targets, content_by_sha256 = _ratio_catalogs(tmp_path)
    initial_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=base,
        base_index_run_id=None,
        target_index_run_id="ratio-base",
    )
    for changed_count in (0, 1, 5, 20):
        cache = MemoryComputationCache()
        execute_incremental_computation(
            plan=initial_plan,
            target_catalog=base,
            cache=cache,
            pipeline=_pipeline(),
            materializer=RatioMaterializer(content_by_sha256),
            embed_text=FixtureEmbedder(),
        )
        target = targets[changed_count]
        plan = build_change_plan(
            base=base,
            target=target,
            base_index_run_id="ratio-base",
            target_index_run_id=f"ratio-target-{changed_count}",
        )
        materializer = RatioMaterializer(content_by_sha256)
        embedder = FixtureEmbedder()
        result = execute_incremental_computation(
            plan=plan,
            base_catalog=base,
            target_catalog=target,
            cache=cache,
            pipeline=_pipeline(),
            materializer=materializer,
            embed_text=embedder,
        )

        unchanged_count = 100 - changed_count
        assert result.stats.parsed_hits == unchanged_count
        assert result.stats.normalized_hits == unchanged_count
        assert result.stats.chunk_hits == unchanged_count
        assert result.stats.embedding_hits == unchanged_count
        assert result.measurements.parse_calls == changed_count
        assert result.measurements.normalize_calls == changed_count
        assert result.measurements.chunk_calls == changed_count
        assert result.measurements.embedding_calls == changed_count
        assert materializer.parse_calls == changed_count
        assert materializer.normalize_calls == changed_count
        assert embedder.calls == changed_count


def test_nonempty_plan_requires_and_revalidates_its_base_catalog(
    tmp_path: Path,
) -> None:
    base, target, plan = _governance_update_catalog_and_plan(tmp_path)
    cache_root = (tmp_path / "cache").absolute()
    materializer = FixtureMaterializer()

    with pytest.raises(IncrementalComputationError) as missing:
        execute_incremental_computation(
            plan=plan,
            target_catalog=target,
            cache=PersistentComputationCache(cache_root),
            pipeline=_pipeline(),
            materializer=materializer,
            embed_text=FixtureEmbedder(),
        )
    assert missing.value.code == "base_catalog_required"
    assert not cache_root.exists()
    assert materializer.parse_calls == 0

    initial_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=base,
        base_index_run_id=None,
        target_index_run_id="index-base",
    )
    cache = PersistentComputationCache(cache_root)
    execute_incremental_computation(
        plan=initial_plan,
        target_catalog=base,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=FixtureEmbedder(),
    )
    changed = execute_incremental_computation(
        plan=plan,
        base_catalog=base,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=FixtureEmbedder(),
    )

    assert revision_catalog_sha256(base) == plan.base_catalog_sha256
    assert changed.stats.parsed_hits == changed.stats.normalized_hits == 1
    assert changed.stats.chunk_hits == changed.stats.embedding_hits == 1
    assert changed.measurements.parse_calls == 0
    assert changed.measurements.embedding_calls == 0
    assert changed.documents[0].acl_groups == ["group-legal"]


def test_governance_change_reuses_content_but_projects_current_acl(
    tmp_path: Path,
) -> None:
    first_target, first_plan = _catalog_and_plan(
        tmp_path,
        catalog_name="catalog-first",
    )
    second_target, second_plan = _catalog_and_plan(
        tmp_path,
        acl_groups=("group-legal",),
        event_id="evt-leave-2",
        catalog_name="catalog-second",
    )
    cache = PersistentComputationCache((tmp_path / "cache").absolute())
    materializer = FixtureMaterializer()
    embedder = FixtureEmbedder()

    execute_incremental_computation(
        plan=first_plan,
        target_catalog=first_target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=embedder,
    )
    changed = execute_incremental_computation(
        plan=second_plan,
        target_catalog=second_target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=embedder,
    )

    assert changed.stats.parsed_hits == 1
    assert changed.stats.normalized_hits == 1
    assert changed.stats.chunk_hits == 1
    assert changed.stats.embedding_hits == 1
    assert changed.documents[0].acl_groups == ["group-legal"]
    assert changed.chunks[0].acl_groups == ["group-legal"]


def test_complete_target_governance_selects_one_duplicate_before_chunking(
    tmp_path: Path,
) -> None:
    target, plan = _duplicate_catalog_and_plan(tmp_path)
    materializer = DuplicateMaterializer()
    embedder = FixtureEmbedder()

    result = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=PersistentComputationCache((tmp_path / "cache").absolute()),
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=embedder,
    )

    assert result.artifact_manifest.canonical_document_count == 1
    assert [document.doc_id for document in result.documents] == ["doc-a"]
    assert {chunk.doc_id for chunk in result.chunks} == {"doc-a"}
    assert embedder.calls == 1
    bindings = result.artifact_manifest.source_bindings
    assert [binding.canonical_document for binding in bindings] == [True, False]
    assert bindings[1].chunk_artifact_sha256 is None


def test_tombstone_target_has_explicit_zero_artifact_binding(
    tmp_path: Path,
) -> None:
    target, plan = _tombstone_catalog_and_plan(tmp_path)
    materializer = FixtureMaterializer()
    embedder = FixtureEmbedder()
    cache_root = (tmp_path / "cache").absolute()

    result = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=PersistentComputationCache(cache_root),
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=embedder,
    )

    assert result.documents == result.chunks == result.embeddings == ()
    assert result.artifact_manifest.source_bindings == ()
    assert len(result.artifact_manifest.tombstone_bindings) == 1
    assert (
        result.artifact_manifest.tombstone_bindings[0].source_key
        == "policy/leave"
    )
    assert materializer.parse_calls == embedder.calls == 0
    assert not cache_root.exists()


def test_embedding_failure_leaves_index_state_unchanged_and_retry_reuses_upstream(
    tmp_path: Path,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    cache = PersistentComputationCache((tmp_path / "cache").absolute())
    materializer = FixtureMaterializer()
    index_root = tmp_path / "index"
    versions = index_root / "versions"
    versions.mkdir(parents=True)
    active = index_root / "active.json"
    active.write_bytes(b'{"run_id":"old"}\n')
    marker = versions / "old.marker"
    marker.write_bytes(b"immutable-old")

    def fail_embedding(text: str) -> list[float]:
        raise RuntimeError("injected embedding failure")

    with pytest.raises(IncrementalComputationError) as failed:
        execute_incremental_computation(
            plan=plan,
            target_catalog=target,
            cache=cache,
            pipeline=_pipeline(),
            materializer=materializer,
            embed_text=fail_embedding,
        )
    assert failed.value.code == "embedding_failed"
    assert active.read_bytes() == b'{"run_id":"old"}\n'
    assert marker.read_bytes() == b"immutable-old"

    retry = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=materializer,
        embed_text=FixtureEmbedder(),
    )
    assert retry.stats.parsed_hits == 1
    assert retry.stats.normalized_hits == 1
    assert retry.stats.chunk_hits == 1
    assert retry.stats.embedding_misses == 1
    assert active.read_bytes() == b'{"run_id":"old"}\n'
    assert marker.read_bytes() == b"immutable-old"


def test_tampered_validated_models_and_stale_materialization_fail_before_use(
    tmp_path: Path,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    cache_root = (tmp_path / "cache").absolute()
    tampered_plan = plan.model_copy(update={"plan_id": f"plan_{'f' * 64}"})

    with pytest.raises(IncrementalComputationError) as invalid_plan:
        execute_incremental_computation(
            plan=tampered_plan,
            target_catalog=target,
            cache=PersistentComputationCache(cache_root),
            pipeline=_pipeline(),
            materializer=FixtureMaterializer(),
            embed_text=FixtureEmbedder(),
        )
    assert invalid_plan.value.code == "plan_invalid"
    assert not cache_root.exists()

    payload = plan.model_dump(mode="json", exclude={"plan_id"})
    payload["upserts"][0]["target_revision_id"] = f"rev_{'e' * 64}"
    plan_id = "plan_" + hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    forged_plan = plan.__class__(plan_id=plan_id, **payload)
    with pytest.raises(IncrementalComputationError) as wrong_target:
        execute_incremental_computation(
            plan=forged_plan,
            target_catalog=target,
            cache=PersistentComputationCache(cache_root),
            pipeline=_pipeline(),
            materializer=FixtureMaterializer(),
            embed_text=FixtureEmbedder(),
        )
    assert wrong_target.value.code == "plan_target_binding_mismatch"
    assert not cache_root.exists()

    with pytest.raises(IncrementalComputationError) as stale_document:
        execute_incremental_computation(
            plan=plan,
            target_catalog=target,
            cache=PersistentComputationCache(cache_root),
            pipeline=_pipeline(),
            materializer=StaleDocumentMaterializer(),
            embed_text=FixtureEmbedder(),
        )
    assert stale_document.value.code == "document_binding_mismatch"


def test_artifact_set_id_binds_final_governed_document_and_chunk_projection(
    tmp_path: Path,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    cache = PersistentComputationCache((tmp_path / "cache").absolute())
    first = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )
    changed = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=cache,
        pipeline=_pipeline(),
        materializer=DepartmentMaterializer(),
        embed_text=FixtureEmbedder(),
    )

    assert first.artifact_manifest.artifact_set_id != (
        changed.artifact_manifest.artifact_set_id
    )
    assert first.artifact_manifest.documents_sha256 != (
        changed.artifact_manifest.documents_sha256
    )
    assert first.artifact_manifest.chunks_sha256 != (
        changed.artifact_manifest.chunks_sha256
    )
    assert first.artifact_manifest.embeddings_sha256 == (
        changed.artifact_manifest.embeddings_sha256
    )


def test_result_rejects_artifacts_that_do_not_match_its_manifest(
    tmp_path: Path,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    result = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=PersistentComputationCache((tmp_path / "cache").absolute()),
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )
    wrong_document = result.documents[0].model_copy(
        update={"department": "Legal"}
    )
    wrong_document_payload = result.model_dump(mode="json")
    wrong_document_payload["documents"] = [
        wrong_document.model_dump(mode="json")
    ]
    with pytest.raises(ValueError, match="documents"):
        IncrementalComputationResult.model_validate(wrong_document_payload)

    wrong_embedding_payload = result.model_dump(mode="json")
    wrong_embedding_payload["embeddings"][0]["vector"] = [1.0, 2.0, 3.0]
    with pytest.raises(ValueError, match="dimension|embeddings"):
        IncrementalComputationResult.model_validate(wrong_embedding_payload)


def test_total_wall_time_includes_final_result_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, plan = _catalog_and_plan(tmp_path)
    original_result_model = computation_module.IncrementalComputationResult
    original_transaction = PersistentComputationCache.transaction

    def delayed_result_validation(*args, **kwargs):
        time.sleep(0.05)
        return original_result_model(*args, **kwargs)

    @contextmanager
    def delayed_transaction(cache):
        with original_transaction(cache):
            yield
        time.sleep(0.05)

    monkeypatch.setattr(
        computation_module,
        "IncrementalComputationResult",
        delayed_result_validation,
    )
    monkeypatch.setattr(
        PersistentComputationCache,
        "transaction",
        delayed_transaction,
    )
    observed_started = time.perf_counter()
    result = execute_incremental_computation(
        plan=plan,
        target_catalog=target,
        cache=PersistentComputationCache((tmp_path / "cache").absolute()),
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )
    observed_wall = time.perf_counter() - observed_started

    assert result.measurements.total_wall_seconds >= 0.10
    assert result.measurements.total_wall_seconds <= observed_wall
    assert observed_wall - result.measurements.total_wall_seconds < 0.03
