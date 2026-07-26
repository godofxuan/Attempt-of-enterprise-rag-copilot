from __future__ import annotations

import json
import hashlib
import pickle
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import faiss
import numpy as np

from app.domain.queries import QueryFilters, SearchRequest, UserContext
from app.indexing.change_plan import build_change_plan
from app.indexing.incremental_computation import execute_incremental_computation
from app.indexing.incremental_snapshot import (
    LifecyclePublicationError,
    build_incremental_index_version,
    execute_incremental_publication,
    retrieval_fingerprint,
    recover_pending_rollback,
    rollback_index_version,
    validate_incremental_index_directory,
)
from app.indexing.store import activate_version, load_index_version
from app.indexing.manifest import load_index_manifest, serialize_index_manifest
from app.ingestion.revision_catalog import (
    PersistentRevisionCatalog,
    RevisionMaterialization,
    empty_revision_catalog_snapshot,
)
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.source_events import SourceEvent
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.snapshot import V2IndexSnapshot
from tests.indexing.test_incremental_computation import (
    FixtureEmbedder,
    FixtureMaterializer,
    MemoryComputationCache,
    NORMALIZED_SHA,
    NOW,
    _pipeline,
    _governance_update_catalog_and_plan,
)


START = datetime(2026, 7, 26, 16, 0, tzinfo=timezone.utc)
FINISH = START + timedelta(seconds=1)


def _upsert_event(event_id: str = "evt-base") -> SourceEvent:
    return SourceEvent(
        event_id=event_id,
        operation="UPSERT",
        tenant_id="tenant-a",
        region="ap-east",
        source_system="sharepoint",
        source_key="policy/leave",
        occurred_at=NOW,
        content_relpath="policies/leave.md",
        declared_media_type="text/markdown",
        content_sha256="1" * 64,
        actor_pseudonym="operator-a",
        acl_groups=("group-employees",),
    )


def _materialization(event: SourceEvent) -> RevisionMaterialization:
    return RevisionMaterialization(
        document_id="doc-leave",
        asset_id=f"asset_{'2' * 32}",
        parent_event_id=event.event_id,
        content_sha256=event.content_sha256,
        normalized_sha256=NORMALIZED_SHA,
        parser_name="markdown",
        parser_version="1",
        normalizer_version="1",
    )


def _compute(plan, target, *, base=None):
    return execute_incremental_computation(
        plan=plan,
        base_catalog=base,
        target_catalog=target,
        cache=MemoryComputationCache(),
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )


def _base_and_delete(tmp_path: Path):
    catalog = PersistentRevisionCatalog((tmp_path / "catalog").absolute())
    upsert = _upsert_event()
    accepted = catalog.apply(upsert, materialization=_materialization(upsert))
    base = catalog.snapshot()
    base_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=base,
        base_index_run_id=None,
        target_index_run_id="index-base",
    )
    base_computation = _compute(base_plan, base)
    catalog.apply(
        SourceEvent(
            event_id="evt-delete",
            operation="DELETE",
            tenant_id="tenant-a",
            region="ap-east",
            source_system="sharepoint",
            source_key="policy/leave",
            expected_revision_id=accepted.revision.revision_id,
            occurred_at=NOW + timedelta(seconds=1),
            actor_pseudonym="operator-a",
        ),
        materialization=None,
    )
    deleted = catalog.snapshot()
    delete_plan = build_change_plan(
        base=base,
        target=deleted,
        base_index_run_id="index-base",
        target_index_run_id="index-deleted",
    )
    deleted_computation = _compute(delete_plan, deleted, base=base)
    return (
        base,
        base_plan,
        base_computation,
        deleted,
        delete_plan,
        deleted_computation,
    )


def _request() -> SearchRequest:
    return SearchRequest(
        request_id="fixed-query",
        query="annual leave",
        purpose="rollback verification",
        user=UserContext(
            user_id="user-a",
            tenant_id="tenant-a",
            region="ap-east",
            groups=["group-employees"],
        ),
        filters=QueryFilters(authoritative_only=False),
        top_k=3,
        candidate_k=10,
        mode="bm25",
    )


def _rehash_artifact(version_path: Path, name: str) -> None:
    manifest_path = version_path / "manifest.json"
    manifest = load_index_manifest(manifest_path)
    content = (version_path / name).read_bytes()
    artifacts = [
        (
            item.model_copy(
                update={
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "byte_count": len(content),
                }
            )
            if item.path == name
            else item
        )
        for item in manifest.artifacts
    ]
    manifest_path.write_bytes(
        serialize_index_manifest(
            manifest.model_copy(update={"artifacts": artifacts})
        )
    )


def test_builds_complete_snapshot_and_exact_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    base, plan, computation, *_ = _base_and_delete(tmp_path)

    first = build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    before = {
        path.name: path.read_bytes()
        for path in (root / "versions" / "index-base").iterdir()
    }
    pointer_before = (root / "active.json").read_bytes()

    replay = build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=computation,
        pipeline=_pipeline(),
        activate=True,
    )

    assert first.status == "BUILT"
    assert replay.status == "REUSED"
    assert replay.activated is True
    assert (root / "active.json").read_bytes() == pointer_before
    assert {
        path.name: path.read_bytes()
        for path in (root / "versions" / "index-base").iterdir()
    } == before
    snapshot = V2IndexSnapshot.load(root)
    assert snapshot.version.manifest_sha256 == first.manifest_sha256
    assert snapshot.faiss_index.ntotal == len(snapshot.chunks) == 1


def test_nonempty_base_is_bound_to_actual_manifest_and_active_pointer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    (
        base,
        base_plan,
        base_computation,
        deleted,
        delete_plan,
        deleted_computation,
    ) = _base_and_delete(tmp_path)
    base_result = build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=base_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )

    result = build_incremental_index_version(
        root=root,
        plan=delete_plan,
        base_catalog=base,
        target_catalog=deleted,
        computation=deleted_computation,
        pipeline=_pipeline(),
        activate=False,
        started_at=START,
        finished_at=FINISH,
    )

    binding = result.lifecycle_manifest.base_index
    assert binding is not None
    assert binding.run_id == "index-base"
    assert binding.manifest_sha256 == base_result.manifest_sha256
    assert binding.catalog_sha256 == delete_plan.base_catalog_sha256


@pytest.mark.parametrize(
    "failure_point",
    [
        "documents_artifact_write",
        "chunks_artifact_write",
        "bm25_write",
        "faiss_write",
        "manifest_write",
        "version_install",
        "active_pointer_replace",
    ],
)
def test_each_publication_failure_point_is_atomic_across_ten_attempts(
    tmp_path: Path,
    failure_point: str,
) -> None:
    root = tmp_path / "indexes"
    (
        base,
        base_plan,
        base_computation,
        deleted,
        delete_plan,
        deleted_computation,
    ) = _base_and_delete(tmp_path)
    build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=base_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    pointer_before = (root / "active.json").read_bytes()
    base_manifest_sha256 = load_index_version(root).manifest_sha256

    def inject(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"injected {point}")

    for _ in range(10):
        with pytest.raises(RuntimeError, match="injected"):
            build_incremental_index_version(
                root=root,
                plan=delete_plan,
                base_catalog=base,
                target_catalog=deleted,
                computation=deleted_computation,
                pipeline=_pipeline(),
                activate=True,
                started_at=START,
                finished_at=FINISH,
                failure_injector=inject,
            )
        assert (root / "active.json").read_bytes() == pointer_before
        assert load_index_version(root).manifest_sha256 == base_manifest_sha256
        assert not (root / "versions" / "index-deleted").exists()
        assert list((root / "versions").glob(".index-deleted.staging-*")) == []


@pytest.mark.parametrize(
    "failure_point",
    [
        "file_validation",
        "parser",
        "normalizer",
        "chunker",
        "embedding",
        "cache_read",
        "cache_write",
    ],
)
def test_each_precompute_failure_point_is_atomic_across_ten_attempts(
    tmp_path: Path,
    failure_point: str,
) -> None:
    root = tmp_path / "indexes"
    base, target, plan = _governance_update_catalog_and_plan(tmp_path)
    base_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=base,
        base_index_run_id=None,
        target_index_run_id="index-base",
    )
    base_computation = _compute(base_plan, base)
    build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=base_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    pointer_before = (root / "active.json").read_bytes()
    base_manifest_sha256 = load_index_version(root).manifest_sha256

    def inject(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"injected {point}")

    for _ in range(10):
        with pytest.raises(RuntimeError, match="injected"):
            execute_incremental_publication(
                root=root,
                plan=plan,
                base_catalog=base,
                target_catalog=target,
                cache=MemoryComputationCache(),
                pipeline=_pipeline(),
                materializer=FixtureMaterializer(),
                embed_text=FixtureEmbedder(),
                validate_files=lambda: None,
                activate=True,
                started_at=START,
                finished_at=FINISH,
                failure_injector=inject,
            )
        assert (root / "active.json").read_bytes() == pointer_before
        assert load_index_version(root).manifest_sha256 == base_manifest_sha256
        assert not (root / "versions" / "index-target").exists()
        assert list((root / "versions").glob(".index-target.staging-*")) == []

    retry = execute_incremental_publication(
        root=root,
        plan=plan,
        base_catalog=base,
        target_catalog=target,
        cache=MemoryComputationCache(),
        pipeline=_pipeline(),
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
        validate_files=lambda: None,
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    assert retry.activated is True
    assert load_index_version(root).manifest.run_id == "index-target"


def test_delete_has_zero_residuals_and_rollback_restores_queries_and_citations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    (
        base,
        base_plan,
        base_computation,
        deleted,
        delete_plan,
        deleted_computation,
    ) = _base_and_delete(tmp_path)
    base_result = build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=base_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    request = _request()
    expected_query = retrieval_fingerprint(
        root=root,
        run_id="index-base",
        requests=[request],
    )
    base_hits = HybridRetrievalPipeline(V2IndexSnapshot.load(root)).search(request)
    assert [hit.doc_id for hit in base_hits.hits] == ["doc-leave"]

    deleted_result = build_incremental_index_version(
        root=root,
        plan=delete_plan,
        base_catalog=base,
        target_catalog=deleted,
        computation=deleted_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    deleted_path = root / "versions" / "index-deleted"
    lifecycle = validate_incremental_index_directory(deleted_path)
    deleted_snapshot = V2IndexSnapshot.load(root)
    deleted_search = HybridRetrievalPipeline(deleted_snapshot).search(request)

    assert deleted_result.activated is True
    assert deleted_snapshot.chunks == ()
    assert deleted_snapshot.documents_by_id == {}
    assert deleted_snapshot.faiss_index.ntotal == 0
    assert deleted_snapshot.bm25.corpus_size == 0
    assert deleted_search.hits == []
    assert lifecycle.tombstone_bindings[0].prior_document_ids == ("doc-leave",)
    assert json.loads((deleted_path / "documents.json").read_text("utf-8")) == []
    assert json.loads((deleted_path / "chunks.json").read_text("utf-8")) == []

    rollback = rollback_index_version(
        root=root,
        target_run_id="index-base",
        expected_current_run_id="index-deleted",
        requests=[request],
        expected_query_fingerprint_sha256=expected_query,
        occurred_at=FINISH + timedelta(seconds=1),
    )

    assert rollback.pointer_manifest_sha256 == base_result.manifest_sha256
    assert load_index_version(root).manifest_sha256 == base_result.manifest_sha256
    assert (
        retrieval_fingerprint(
            root=root,
            run_id="index-base",
            requests=[request],
        )
        == expected_query
    )
    assert rollback.audit_event.old_data_visibility_restored is True
    assert rollback.audit_event.from_run_id == "index-deleted"
    assert rollback.audit_event.to_run_id == "index-base"


def test_post_pointer_rollback_audit_failure_is_explicit_and_recoverable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    (
        base,
        base_plan,
        base_computation,
        deleted,
        delete_plan,
        deleted_computation,
    ) = _base_and_delete(tmp_path)
    build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=base_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    build_incremental_index_version(
        root=root,
        plan=delete_plan,
        base_catalog=base,
        target_catalog=deleted,
        computation=deleted_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )

    def fail_audit() -> None:
        raise OSError("injected audit failure")

    with pytest.raises(LifecyclePublicationError) as captured:
        rollback_index_version(
            root=root,
            target_run_id="index-base",
            expected_current_run_id="index-deleted",
            occurred_at=FINISH + timedelta(seconds=1),
            audit_failure_injector=fail_audit,
        )

    assert captured.value.code == "rollback_outcome_unknown"
    assert load_index_version(root).manifest.run_id == "index-base"
    assert (root / "audit" / "rollback.intent.json").is_file()

    recovered = recover_pending_rollback(root=root)

    assert recovered is not None
    assert recovered.from_run_id == "index-deleted"
    assert recovered.to_run_id == "index-base"
    assert not (root / "audit" / "rollback.intent.json").exists()
    assert recover_pending_rollback(root=root) is None


def test_stale_plan_cannot_activate_over_a_different_base(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    (
        base,
        base_plan,
        base_computation,
        deleted,
        delete_plan,
        deleted_computation,
    ) = _base_and_delete(tmp_path)
    build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=base_computation,
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    pointer = json.loads((root / "active.json").read_text(encoding="utf-8"))
    pointer["run_id"] = "different-run"
    (root / "active.json").write_text(
        json.dumps(pointer),
        encoding="utf-8",
    )

    with pytest.raises(LifecyclePublicationError, match="active pointer changed"):
        build_incremental_index_version(
            root=root,
            plan=delete_plan,
            base_catalog=base,
            target_catalog=deleted,
            computation=deleted_computation,
            pipeline=_pipeline(),
            activate=True,
            started_at=START,
            finished_at=FINISH,
        )


def test_same_run_with_different_publication_identity_is_a_conflict(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    base, plan, computation, *_ = _base_and_delete(tmp_path)
    build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=computation,
        pipeline=_pipeline(),
        profile_id="profile-a",
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )

    with pytest.raises(LifecyclePublicationError, match="different publication"):
        build_incremental_index_version(
            root=root,
            plan=plan,
            base_catalog=None,
            target_catalog=base,
            computation=computation,
            pipeline=_pipeline(),
            profile_id="profile-b",
            activate=True,
        )


@pytest.mark.parametrize("artifact_name", ["bm25_tokens.pkl", "faiss.index"])
def test_row_level_tampering_is_rejected_even_after_manifest_rehash(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    root = tmp_path / "indexes"
    base, plan, computation, *_ = _base_and_delete(tmp_path)
    build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=computation,
        pipeline=_pipeline(),
        activate=False,
        started_at=START,
        finished_at=FINISH,
    )
    version_path = root / "versions" / "index-base"
    if artifact_name == "bm25_tokens.pkl":
        (version_path / artifact_name).write_bytes(
            pickle.dumps([["wrong-row"]], protocol=pickle.HIGHEST_PROTOCOL)
        )
        expected = "BM25 rows"
    else:
        index = faiss.IndexFlatIP(4)
        index.add(np.asarray([[0.0, 1.0, 0.0, 0.0]], dtype="float32"))
        (version_path / artifact_name).write_bytes(
            faiss.serialize_index(index).tobytes()
        )
        expected = "FAISS rows"
    _rehash_artifact(version_path, artifact_name)

    with pytest.raises(LifecyclePublicationError, match=expected):
        validate_incremental_index_directory(version_path)


def test_competing_publications_from_one_base_have_one_winner(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    base, target, _ = _governance_update_catalog_and_plan(tmp_path)
    base_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=base,
        base_index_run_id=None,
        target_index_run_id="index-base",
    )
    build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=_compute(base_plan, base),
        pipeline=_pipeline(),
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    plans = [
        build_change_plan(
            base=base,
            target=target,
            base_index_run_id="index-base",
            target_index_run_id=run_id,
        )
        for run_id in ("index-target-a", "index-target-b")
    ]
    computations = [
        _compute(plan, target, base=base) for plan in plans
    ]
    barrier = threading.Barrier(2)

    def publish(index: int):
        def synchronize(point: str) -> None:
            if point == "manifest_write":
                barrier.wait(timeout=5)

        return build_incremental_index_version(
            root=root,
            plan=plans[index],
            base_catalog=base,
            target_catalog=target,
            computation=computations[index],
            pipeline=_pipeline(),
            activate=True,
            started_at=START,
            finished_at=FINISH,
            failure_injector=synchronize,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future
            for future in (
                executor.submit(publish, 0),
                executor.submit(publish, 1),
            )
        ]
        results = []
        errors = []
        for future in outcomes:
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(exc)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], LifecyclePublicationError)
    assert errors[0].code == "active_base_conflict"
    active_run = load_index_version(root).manifest.run_id
    assert active_run in {"index-target-a", "index-target-b"}
    loser = ({"index-target-a", "index-target-b"} - {active_run}).pop()
    assert not (root / "versions" / loser).exists()


def test_parent_child_computation_order_survives_split_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    base, plan, *_ = _base_and_delete(tmp_path)
    pipeline = _pipeline(
        chunker_config=ChunkerConfig(
            mode="parent_child",
            parent_size=1000,
            child_size=24,
            overlap=8,
        )
    )
    computation = execute_incremental_computation(
        plan=plan,
        target_catalog=base,
        cache=MemoryComputationCache(),
        pipeline=pipeline,
        materializer=FixtureMaterializer(),
        embed_text=FixtureEmbedder(),
    )

    build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=computation,
        pipeline=pipeline,
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )

    snapshot = V2IndexSnapshot.load(root)
    assert snapshot.parents_by_id
    assert all(
        chunk.parent_chunk_id in snapshot.parents_by_id
        for chunk in snapshot.chunks
    )
    validate_incremental_index_directory(snapshot.version.path)


def test_missing_runtime_artifact_is_rejected_before_pickle_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "indexes"
    base, plan, computation, *_ = _base_and_delete(tmp_path)
    build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=computation,
        pipeline=_pipeline(),
        activate=False,
        started_at=START,
        finished_at=FINISH,
    )
    version_path = root / "versions" / "index-base"
    manifest_path = version_path / "manifest.json"
    manifest = load_index_manifest(manifest_path)
    manifest_path.write_bytes(
        serialize_index_manifest(
            manifest.model_copy(
                update={
                    "artifacts": [
                        item
                        for item in manifest.artifacts
                        if item.path != "bm25_tokens.pkl"
                    ]
                }
            )
        )
    )

    def fail_if_loaded(*args, **kwargs):
        raise AssertionError("unbound pickle must not be deserialized")

    monkeypatch.setattr("app.indexing.builder.pickle.load", fail_if_loaded)
    with pytest.raises(ValueError, match="required runtime artifacts"):
        validate_incremental_index_directory(version_path)


def test_nonempty_legacy_base_without_catalog_binding_is_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "indexes"
    base, target, _ = _governance_update_catalog_and_plan(tmp_path)
    base_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=base,
        base_index_run_id=None,
        target_index_run_id="index-base",
    )
    build_incremental_index_version(
        root=root,
        plan=base_plan,
        base_catalog=None,
        target_catalog=base,
        computation=_compute(base_plan, base),
        pipeline=_pipeline(),
        activate=False,
        started_at=START,
        finished_at=FINISH,
    )
    source = root / "versions" / "index-base"
    legacy = root / "versions" / "legacy-base"
    shutil.copytree(source, legacy)
    manifest = load_index_manifest(legacy / "manifest.json")
    runtime_names = {
        "documents.json",
        "chunks.json",
        "parents.json",
        "bm25_tokens.pkl",
        "faiss.index",
    }
    for path in tuple(legacy.iterdir()):
        if path.name not in runtime_names | {"manifest.json"}:
            path.unlink()
    (legacy / "manifest.json").write_bytes(
        serialize_index_manifest(
            manifest.model_copy(
                update={
                    "run_id": "legacy-base",
                    "artifacts": [
                        item
                        for item in manifest.artifacts
                        if item.path in runtime_names
                    ],
                }
            )
        )
    )
    activate_version(root, "legacy-base")
    plan = build_change_plan(
        base=base,
        target=target,
        base_index_run_id="legacy-base",
        target_index_run_id="index-target",
    )
    computation = _compute(plan, target, base=base)

    with pytest.raises(LifecyclePublicationError, match="base index"):
        build_incremental_index_version(
            root=root,
            plan=plan,
            base_catalog=base,
            target_catalog=target,
            computation=computation,
            pipeline=_pipeline(),
            activate=True,
            started_at=START,
            finished_at=FINISH,
        )
