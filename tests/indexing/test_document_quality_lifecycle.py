import json

import pytest

from app.indexing.incremental_computation import execute_incremental_computation
from app.indexing.incremental_snapshot import (
    build_incremental_index_version,
    rollback_index_version,
)
from app.indexing.store import load_index_version
from app.ingestion.chunking import ChunkerConfig
from tests.indexing.test_incremental_computation import (
    FixtureEmbedder,
    FixtureMaterializer,
    MemoryComputationCache,
    _pipeline,
)
from tests.indexing.test_incremental_snapshot import FINISH, START, _base_and_delete


def test_structure_cache_delete_quality_and_rollback(tmp_path):
    base, plan, _, deleted, delete_plan, _ = _base_and_delete(tmp_path)
    pipeline = _pipeline(chunker_config=ChunkerConfig(mode="structure"))
    cache = MemoryComputationCache()

    def compute(plan, target, base=None):
        return execute_incremental_computation(
            plan=plan,
            base_catalog=base,
            target_catalog=target,
            cache=cache,
            pipeline=pipeline,
            materializer=FixtureMaterializer(),
            embed_text=FixtureEmbedder(),
        )

    first = compute(plan, base)
    again = compute(plan, base)
    assert again.measurements.embedding_calls == 0
    assert again.measurements.chunk_calls == 0
    root = tmp_path / "structure-index"
    initial = build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=first,
        pipeline=pipeline,
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    assert "document_quality.json" in {a.path for a in load_index_version(root).manifest.artifacts}
    deleted_result = compute(delete_plan, deleted, base)
    build_incremental_index_version(
        root=root,
        plan=delete_plan,
        base_catalog=base,
        target_catalog=deleted,
        computation=deleted_result,
        pipeline=pipeline,
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )
    current = load_index_version(root)
    assert current.manifest.indexed_chunk_count == 0
    assert json.loads((current.path / "document_quality.json").read_text()) == []
    rollback_index_version(
        root=root, target_run_id="index-base", expected_current_run_id="index-deleted"
    )
    assert load_index_version(root).manifest_sha256 == initial.manifest_sha256


@pytest.mark.parametrize(
    "point", ["chunks_artifact_write", "manifest_write", "active_pointer_replace"]
)
def test_structure_publication_fault_never_replaces_base(tmp_path, point):
    base, plan, _, deleted, delete_plan, _ = _base_and_delete(tmp_path)
    pipeline = _pipeline(chunker_config=ChunkerConfig(mode="structure"))

    def compute(plan, target, base=None):
        return execute_incremental_computation(
            plan=plan,
            base_catalog=base,
            target_catalog=target,
            cache=MemoryComputationCache(),
            pipeline=pipeline,
            materializer=FixtureMaterializer(),
            embed_text=FixtureEmbedder(),
        )

    root = tmp_path / "index"
    build_incremental_index_version(
        root=root,
        plan=plan,
        base_catalog=None,
        target_catalog=base,
        computation=compute(plan, base),
        pipeline=pipeline,
        activate=True,
    )
    before = (root / "active.json").read_bytes()

    def inject(current):
        if current == point:
            raise RuntimeError("dq-injected-fault")

    with pytest.raises(RuntimeError, match="dq-injected-fault"):
        build_incremental_index_version(
            root=root,
            plan=delete_plan,
            base_catalog=base,
            target_catalog=deleted,
            computation=compute(delete_plan, deleted, base),
            pipeline=pipeline,
            activate=True,
            failure_injector=inject,
        )
    assert (root / "active.json").read_bytes() == before
