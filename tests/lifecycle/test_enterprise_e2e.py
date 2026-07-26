from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.queries import (
    QueryFilters,
    SearchRequest,
    UserContext,
)
from app.indexing.computation_cache import (
    ComponentFingerprint,
    EmbeddingFingerprint,
)
from app.indexing.incremental_computation import PipelineConfiguration
from app.indexing.incremental_snapshot import (
    retrieval_fingerprint,
    validate_incremental_index_directory,
)
from app.indexing.store import load_index_version
from app.ingestion.chunking import ChunkerConfig
from app.lifecycle.enterprise_bundle import load_enterprise_bundle
from app.lifecycle.enterprise_bundle import (
    EnterpriseLifecyclePublicSummary,
    canonical_enterprise_lifecycle_summary_bytes,
)
from app.lifecycle.operator import (
    LifecycleActivateRequest,
    LifecycleBuildRequest,
    LifecycleOperationError,
    LifecycleOperatorService,
    LifecycleRollbackRequest,
)
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.snapshot import V2IndexSnapshot
from app.security.identity import Principal


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = ROOT / "data" / "enterprise_bundle"
PUBLIC_SUMMARY = (
    ROOT / "data" / "v2" / "public" / "lifecycle_g9" / "summary.json"
)
NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)


class ActorPseudonymizer:
    def pseudonym(self, principal: Principal) -> str:
        return f"actor-{principal.subject}"


def _principal() -> Principal:
    return Principal(
        subject="northstar-operator",
        tenant_id="northstar-demo",
        region="ap-east",
        groups=[
            "group-employees",
            "group-engineering",
            "group-procurement",
            "group-security",
        ],
        roles=["rag.operator"],
        issuer="https://identity.localhost/",
        audience="enterprise-rag-api",
        key_id="g9-test-key",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _pipeline() -> PipelineConfiguration:
    return PipelineConfiguration(
        materializer=ComponentFingerprint(
            name="g9-production-materializer-contract",
            semantic_version="1",
            implementation_sha256="1" * 64,
        ),
        governance=ComponentFingerprint(
            name="g9-governance-contract",
            semantic_version="1",
            implementation_sha256="2" * 64,
        ),
        normalizer=ComponentFingerprint(
            name="g9-normalizer-contract",
            semantic_version="1",
            implementation_sha256="3" * 64,
        ),
        chunker=ComponentFingerprint(
            name="g9-chunker-contract",
            semantic_version="1",
            implementation_sha256="4" * 64,
        ),
        chunker_config=ChunkerConfig(
            mode="fixed",
            chunk_size=240,
            overlap=24,
        ),
        embedding=EmbeddingFingerprint(
            component=ComponentFingerprint(
                name="g9-deterministic-test-embedder",
                semantic_version="1",
                implementation_sha256="5" * 64,
            ),
            backend="deterministic-test",
            model_identifier="g9-fixture-4d",
            model_sha256="6" * 64,
            dimension=4,
            normalization="l2",
        ),
    )


def _service(root: Path, input_root: Path) -> LifecycleOperatorService:
    return LifecycleOperatorService(
        input_root=input_root.absolute(),
        asset_root=(root / "assets").absolute(),
        catalog_root=(root / "catalog").absolute(),
        cache_root=(root / "cache").absolute(),
        index_root=(root / "indexes").absolute(),
        actor_pseudonymizer=ActorPseudonymizer(),
        pipeline=_pipeline(),
        embed_text=lambda text: [1.0, 2.0, 3.0, 4.0],
    )


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _document_id(source_system: str, source_key: str) -> str:
    identity = "\0".join(
        ("northstar-demo", source_system, source_key)
    ).encode("utf-8")
    return f"doc_{hashlib.sha256(identity).hexdigest()}"


def _query(bundle) -> SearchRequest:
    query = bundle.query("vendor-rollback")
    return SearchRequest(
        request_id="g9-vendor-rollback",
        query=query.query,
        purpose=query.purpose,
        user=UserContext(
            user_id="northstar-auditor",
            tenant_id="northstar-demo",
            region="ap-east",
            groups=list(query.groups),
        ),
        filters=QueryFilters(authoritative_only=False),
        top_k=5,
        candidate_k=20,
        mode="bm25",
    )


def _active_index_deleted_residuals(
    *,
    snapshot: V2IndexSnapshot,
    lifecycle,
    hits,
    document_id: str,
    indexed_chunk_ids: set[str],
    parent_chunk_ids: set[str],
    source_system: str,
    source_key: str,
) -> set[tuple[str, str]]:
    residuals: set[tuple[str, str]] = set()
    if document_id in snapshot.documents_by_id:
        residuals.add(("document", document_id))
    for chunk_id in indexed_chunk_ids:
        if chunk_id in snapshot.all_chunks_by_id:
            residuals.add(("indexed_chunk", chunk_id))
        if chunk_id in snapshot.chunk_index_by_id:
            residuals.add(("bm25_row", chunk_id))
            residuals.add(("faiss_row", chunk_id))
    for chunk_id in parent_chunk_ids:
        if chunk_id in snapshot.parents_by_id:
            residuals.add(("parent_chunk", chunk_id))
    for hit in hits:
        if hit.doc_id == document_id or hit.chunk_id in indexed_chunk_ids:
            residuals.add(("retrieval_hit", hit.chunk_id))
    if any(
        (binding.source_system, binding.source_key)
        == (source_system, source_key)
        for binding in lifecycle.source_bindings
    ):
        residuals.add(("live_source_binding", source_key))
    return residuals


def test_fictional_enterprise_lifecycle_runs_end_to_end(
    tmp_path: Path,
) -> None:
    copied_bundle = tmp_path / "bundle"
    shutil.copytree(BUNDLE_ROOT, copied_bundle)
    bundle = load_enterprise_bundle(copied_bundle)
    runtime_root = tmp_path / "runtime"
    service = _service(runtime_root, copied_bundle)
    principal = _principal()

    initial = service.build(
        LifecycleBuildRequest(
            target_run_id="g9-initial",
            events=bundle.batch("initial"),
            activate=True,
        ),
        principal,
    )
    accepted_revisions = {
        event.event_id: event.resulting_revision_id
        for event in initial.events
    }
    assert initial.activated is True
    assert initial.document_count == 4
    assert all(event.disposition == "APPLIED" for event in initial.events)
    assert service.status(principal).state == "SYNCHRONIZED"

    fixed_query = _query(bundle)
    initial_fingerprint = retrieval_fingerprint(
        root=service.index_root,
        run_id=initial.run_id,
        requests=(fixed_query,),
    )
    initial_snapshot = V2IndexSnapshot.load(service.index_root)
    initial_lifecycle = validate_incremental_index_directory(
        initial_snapshot.version.path
    )
    initial_hits = HybridRetrievalPipeline(initial_snapshot).search(fixed_query)
    expected_query_event = bundle.expected_initial_event("vendor-rollback")
    vendor_document_id = _document_id(
        expected_query_event.source_system,
        expected_query_event.source_key,
    )
    assert any(hit.doc_id == vendor_document_id for hit in initial_hits.hits)
    vendor_indexed_chunk_ids = {
        chunk.chunk_id
        for chunk in initial_snapshot.chunks
        if chunk.doc_id == vendor_document_id
    }
    vendor_parent_chunk_ids = {
        chunk.chunk_id
        for chunk in initial_snapshot.parents_by_id.values()
        if chunk.doc_id == vendor_document_id
    }
    assert vendor_indexed_chunk_ids

    assets_before_replay = _file_snapshot(service.asset_root)
    sources = copied_bundle / "sources"
    unavailable_sources = copied_bundle / "sources.unavailable"
    sources.rename(unavailable_sources)
    restarted = _service(runtime_root, copied_bundle)
    replay = restarted.build(
        LifecycleBuildRequest(
            target_run_id="g9-replay",
            events=bundle.batch("initial"),
            activate=False,
        ),
        principal,
    )
    assert all(event.disposition == "REPLAYED" for event in replay.events)
    assert _file_snapshot(service.asset_root) == assets_before_replay
    replay_version = load_index_version(service.index_root, replay.run_id)
    replay_lifecycle = validate_incremental_index_directory(
        replay_version.path
    )
    assert (
        replay_lifecycle.target_catalog_sha256,
        replay_lifecycle.documents_sha256,
        replay_lifecycle.chunks_sha256,
        replay_lifecycle.embeddings_sha256,
        replay_lifecycle.document_ids_sha256,
        replay_lifecycle.indexed_chunk_ids_sha256,
        replay_lifecycle.parent_chunk_ids_sha256,
        replay_lifecycle.computation_chunk_order,
    ) == (
        initial_lifecycle.target_catalog_sha256,
        initial_lifecycle.documents_sha256,
        initial_lifecycle.chunks_sha256,
        initial_lifecycle.embeddings_sha256,
        initial_lifecycle.document_ids_sha256,
        initial_lifecycle.indexed_chunk_ids_sha256,
        initial_lifecycle.parent_chunk_ids_sha256,
        initial_lifecycle.computation_chunk_order,
    )
    replay_fingerprint = retrieval_fingerprint(
        root=service.index_root,
        run_id=replay.run_id,
        requests=(fixed_query,),
    )
    assert replay_fingerprint == initial_fingerprint
    unavailable_sources.rename(sources)

    changes = bundle.resolve_batch(
        "change",
        accepted_revisions=accepted_revisions,
    )
    changed = restarted.build(
        LifecycleBuildRequest(
            target_run_id="g9-changed",
            events=changes,
            activate=False,
        ),
        principal,
    )
    pointer_before_activation = (
        service.index_root / "active.json"
    ).read_bytes()
    pending = restarted.status(principal)
    assert changed.document_count == 3
    assert changed.activated is False
    assert pending.state == "INDEX_UPDATE_PENDING"
    assert pending.active_run_id == initial.run_id

    exact_retry = restarted.build(
        LifecycleBuildRequest(
            target_run_id="g9-changed",
            events=changes,
            activate=False,
        ),
        principal,
    )
    assert exact_retry.plan_id == changed.plan_id
    assert exact_retry.publication_id == changed.publication_id
    assert all(
        event.disposition == "REPLAYED" for event in exact_retry.events
    )
    assert (service.index_root / "active.json").read_bytes() == (
        pointer_before_activation
    )

    changed_version = load_index_version(service.index_root, changed.run_id)
    lifecycle = validate_incremental_index_directory(changed_version.path)
    changed_snapshot = V2IndexSnapshot.load(
        service.index_root,
        changed.run_id,
    )
    changed_hits = HybridRetrievalPipeline(changed_snapshot).search(fixed_query)
    changed_fingerprint = retrieval_fingerprint(
        root=service.index_root,
        run_id=changed.run_id,
        requests=(fixed_query,),
    )
    deleted_residuals = _active_index_deleted_residuals(
        snapshot=changed_snapshot,
        lifecycle=lifecycle,
        hits=changed_hits.hits,
        document_id=vendor_document_id,
        indexed_chunk_ids=vendor_indexed_chunk_ids,
        parent_chunk_ids=vendor_parent_chunk_ids,
        source_system=expected_query_event.source_system,
        source_key=expected_query_event.source_key,
    )
    assert deleted_residuals == set()
    assert any(
        vendor_document_id in binding.prior_document_ids
        for binding in lifecycle.tombstone_bindings
    )

    activated = restarted.activate_existing(
        LifecycleActivateRequest(
            target_run_id=changed.run_id,
            expected_current_run_id=initial.run_id,
        ),
        principal,
    )
    assert activated.run_id == changed.run_id
    with pytest.raises(LifecycleOperationError) as stale:
        restarted.activate_existing(
            LifecycleActivateRequest(
                target_run_id=changed.run_id,
                expected_current_run_id=initial.run_id,
            ),
            principal,
        )
    assert stale.value.code == "active_version_conflict"
    assert load_index_version(service.index_root).manifest.run_id == changed.run_id

    rollback = restarted.rollback(
        LifecycleRollbackRequest(
            target_run_id=initial.run_id,
            expected_current_run_id=changed.run_id,
        ),
        principal,
    )
    assert rollback.manifest_sha256 == initial.manifest_sha256
    assert load_index_version(service.index_root).manifest.run_id == initial.run_id
    restored_fingerprint = retrieval_fingerprint(
        root=service.index_root,
        run_id=load_index_version(service.index_root).manifest.run_id,
        requests=(fixed_query,),
    )
    assert restored_fingerprint == initial_fingerprint
    restored_hits = HybridRetrievalPipeline(
        V2IndexSnapshot.load(service.index_root)
    ).search(fixed_query)
    assert any(hit.doc_id == vendor_document_id for hit in restored_hits.hits)

    audit_lines = (
        service.index_root / "audit" / "rollback.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    audit = json.loads(audit_lines[0])
    assert audit["from_run_id"] == changed.run_id
    assert audit["to_run_id"] == initial.run_id

    summary = EnterpriseLifecyclePublicSummary(
        bundle_id=bundle.manifest.bundle_id,
        bundle_manifest_sha256=bundle.manifest_sha256,
        synthetic=True,
        embedding_backend="deterministic-test",
        initial_run_id=initial.run_id,
        changed_run_id=changed.run_id,
        catalog_advanced=(
            pending.catalog_sha256 != pending.active_catalog_sha256
        ),
        exact_retry_plan_match=(exact_retry.plan_id == changed.plan_id),
        exact_retry_publication_match=(
            exact_retry.publication_id == changed.publication_id
        ),
        stale_activation_rejected=(
            stale.value.code == "active_version_conflict"
        ),
        rollback_manifest_restored=(
            rollback.manifest_sha256 == initial.manifest_sha256
        ),
        initial_event_count=len(initial.events),
        replayed_event_count=sum(
            event.disposition == "REPLAYED" for event in replay.events
        ),
        change_event_count=len(changed.events),
        initial_document_count=initial.document_count,
        changed_document_count=changed.document_count,
        active_index_deleted_residual_count=len(deleted_residuals),
        initial_query_fingerprint_sha256=initial_fingerprint,
        changed_query_fingerprint_sha256=changed_fingerprint,
        restored_query_fingerprint_sha256=restored_fingerprint,
        rollback_audit_event_count=len(audit_lines),
    )
    public_bytes = PUBLIC_SUMMARY.read_bytes()

    assert public_bytes == canonical_enterprise_lifecycle_summary_bytes(
        summary
    )
    assert EnterpriseLifecyclePublicSummary.model_validate_json(
        public_bytes
    ) == summary
