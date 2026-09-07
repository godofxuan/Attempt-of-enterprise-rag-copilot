from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pytest

from app.agent import runner_v2
from app.config import Settings
from app.domain.agent import ToolError
from app.domain.queries import OpenRequest
from app.indexing.store import activate_version
from tests.indexing.test_builder import build_corpus
from tests.indexing.test_store import FakeEmbedder, build_version
from tests.v2_test_support import user_context


@pytest.fixture
def versions(tmp_path, monkeypatch):
    corpus = build_corpus(tmp_path / "corpus")
    root = tmp_path / "indexes"
    build_version(root, corpus, "first", activate=True)
    build_version(root, corpus, "second")
    settings = Settings(_env_file=None, v2_indexes_dir=root)
    monkeypatch.setattr(runner_v2, "get_settings", lambda: settings)
    monkeypatch.setattr("app.retriever._embed_text", lambda model, text: FakeEmbedder()(text))
    factory = runner_v2._get_default_v2_runner
    if hasattr(factory, "cache_clear"):
        factory.cache_clear()
    yield root
    if hasattr(factory, "cache_clear"):
        factory.cache_clear()


def test_default_service_factory_follows_activation_and_rollback(versions):
    first = runner_v2._get_default_v2_runner()
    activate_version(versions, "second")
    second = runner_v2._get_default_v2_runner()
    assert second.registry.navigator.snapshot.version.manifest.run_id == "second"
    assert second is not first
    activate_version(versions, "first")
    restored = runner_v2._get_default_v2_runner()
    assert restored.registry.navigator.snapshot.version.manifest.run_id == "first"


@pytest.mark.parametrize("change", ["activate", "rollback", "missing_pointer"])
def test_activation_during_answer_build_withholds_the_old_answer(versions, change):
    runner = runner_v2._get_default_v2_runner()
    chunk = runner.registry.navigator.snapshot.chunks[0]

    class SwitchingBuilder:
        def build(self, **kwargs):
            activate_version(versions, "second")
            if change == "rollback":
                activate_version(versions, "first")
            elif change == "missing_pointer":
                (versions / "active.json").unlink()
            return runner_v2.ExtractiveResponseBuilder().build(**kwargs)

    runner.response_builder = SwitchingBuilder()
    user = user_context().model_copy(
        update={
            "tenant_id": chunk.tenant_id,
            "region": chunk.region,
            "groups": chunk.acl_groups,
        }
    )
    response = runner.run(chunk.text[:120], user)
    assert response.mode == "system"
    assert response.sources == []
    assert response.claims == []
    assert response.trace["index_binding_status"] == (
        "unavailable" if change == "missing_pointer" else "changed"
    )


def test_bad_new_manifest_does_not_fall_back_to_a_cached_old_runner(versions):
    runner_v2._get_default_v2_runner()
    activate_version(versions, "second")
    pointer_path = versions / "active.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["manifest_sha256"] = "0" * 64
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    response = runner_v2.run_agent_v2_chat("What is the remote work limit?", user_context())
    assert response.mode == "system"
    assert response.sources == []


def test_parallel_cold_requests_share_one_versioned_runner(versions):
    with ThreadPoolExecutor(max_workers=4) as pool:
        runners = list(pool.map(lambda _: runner_v2._get_default_v2_runner(), range(8)))
    assert len({id(runner) for runner in runners}) == 1


def test_deleted_policy_is_not_navigable_after_target_activation(versions):
    old = runner_v2._get_default_v2_runner()
    chunk = old.registry.navigator.snapshot.chunks[0]
    corpus = versions.parent / "corpus"
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = [
        row for row in manifest["documents"] if row["metadata"]["policy_id"] != chunk.policy_id
    ]
    manifest["documents"] = documents
    manifest["document_count"] = len(documents)
    for name, field in [
        ("counts_by_format", "format"),
        ("counts_by_source_type", "source_type"),
        ("counts_by_variant", "variant"),
    ]:
        manifest[name] = dict(Counter(row[field] for row in documents))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    build_version(versions, corpus, "deleted", activate=True)
    current = runner_v2._get_default_v2_runner()
    user = user_context().model_copy(
        update={
            "tenant_id": chunk.tenant_id,
            "region": chunk.region,
            "groups": chunk.acl_groups,
        }
    )
    result = current.registry.navigator.open(
        OpenRequest(
            request_id="delete-check",
            user=user,
            target_type="document",
            target_id=chunk.doc_id,
        )
    )
    assert isinstance(result, ToolError)
    assert result.code in {"not_found", "permission"}
    assert chunk.doc_id not in current.registry.navigator.snapshot.documents_by_id
    stale = old.run(chunk.text[:120], user)
    assert stale.mode == "system" and stale.sources == []
    activate_version(versions, "first")
    assert (
        chunk.doc_id
        in runner_v2._get_default_v2_runner().registry.navigator.snapshot.documents_by_id
    )


def _worker_index_identity(root, connection):
    settings = Settings(_env_file=None, v2_indexes_dir=Path(root))
    runner_v2.get_settings = lambda: settings
    try:
        while connection.recv() == "read":
            runner = runner_v2._get_default_v2_runner()
            connection.send(runner.registry.navigator.snapshot.version.manifest.run_id)
    finally:
        connection.close()


def test_two_processes_observe_activation_without_an_invalidation_message(versions):
    context = get_context("spawn")
    processes = []
    connections = []
    try:
        for _ in range(2):
            parent, child = context.Pipe()
            process = context.Process(target=_worker_index_identity, args=(str(versions), child))
            process.start()
            child.close()
            processes.append(process)
            connections.append(parent)
        for expected in ("first", "second", "first"):
            activate_version(versions, expected)
            for connection in connections:
                connection.send("read")
            for connection in connections:
                assert connection.poll(30), "worker did not return index identity"
                assert connection.recv() == expected
    finally:
        for connection in connections:
            connection.send("stop")
            connection.close()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
