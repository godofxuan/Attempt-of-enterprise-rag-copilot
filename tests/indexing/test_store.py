from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.indexing.store import (
    activate_version,
    build_index_version,
    load_active_manifest,
    load_index_version,
)
from app.ingestion.chunking import ChunkerConfig


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"
START = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
FINISH = START + timedelta(seconds=2)


class FakeEmbedder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("synthetic embedding failure")
        total = sum(ord(character) for character in text)
        return [
            float((total % 97) + 1),
            float((len(text) % 31) + 1),
            float((total % 17) + 1),
            1.0,
        ]


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("index-store-corpus") / "corpus"
    write_corpus(path, load_facts(FACTS), load_profile(PROFILE))
    return path


def build_version(
    root: Path,
    corpus_dir: Path,
    run_id: str,
    *,
    embedder: FakeEmbedder | None = None,
    activate: bool = False,
    force: bool = False,
):
    return build_index_version(
        root=root,
        input_dir=corpus_dir,
        run_id=run_id,
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="fake-4d",
        embed_text=embedder or FakeEmbedder(),
        activate=activate,
        force=force,
        started_at=START,
        finished_at=FINISH,
    )


def read_pointer(root: Path) -> dict[str, object]:
    return json.loads((root / "active.json").read_text(encoding="utf-8"))


def test_build_and_activate_writes_verifiable_pointer(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"

    manifest = build_version(root, corpus_dir, "run-one", activate=True)

    version_path = root / "versions" / "run-one"
    manifest_bytes = (version_path / "manifest.json").read_bytes()
    pointer = read_pointer(root)
    loaded = load_index_version(root)
    assert pointer["schema_version"] == "enterprise_active_index_v1"
    assert pointer["producer"] == "enterprise_agentic_rag_v2"
    assert pointer["run_id"] == "run-one"
    assert pointer["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert loaded.path == version_path.resolve()
    assert loaded.manifest == manifest
    assert load_active_manifest(root) == manifest


def test_build_and_activate_supports_batch_embedding_provider(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"
    calls: list[list[str]] = []

    def embed_chunks(chunks) -> np.ndarray:
        calls.append([chunk.chunk_id for chunk in chunks])
        return np.asarray(
            [[float(index + 1), 1.0] for index, _ in enumerate(chunks)],
            dtype="float32",
        )

    manifest = build_index_version(
        root=root,
        input_dir=corpus_dir,
        run_id="batch-run",
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="fake-batch-2d",
        embed_chunks=embed_chunks,
        activate=True,
        started_at=START,
        finished_at=FINISH,
    )

    assert len(calls) == 1
    assert len(calls[0]) == manifest.indexed_chunk_count
    assert manifest.embedding.dimension == 2
    assert load_active_manifest(root) == manifest


def test_missing_or_corrupt_version_cannot_replace_active_pointer(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"
    build_version(root, corpus_dir, "run-one", activate=True)
    previous_pointer = (root / "active.json").read_bytes()

    with pytest.raises(FileNotFoundError, match="version"):
        activate_version(root, "missing")
    assert (root / "active.json").read_bytes() == previous_pointer

    build_version(root, corpus_dir, "run-two")
    chunks_path = root / "versions" / "run-two" / "chunks.json"
    chunks_bytes = chunks_path.read_bytes()
    chunks_path.write_bytes(bytes([chunks_bytes[0] ^ 1]) + chunks_bytes[1:])
    with pytest.raises(ValueError, match="hash mismatch"):
        activate_version(root, "run-two")
    assert (root / "active.json").read_bytes() == previous_pointer


def test_second_build_retains_first_and_rollback_does_not_rebuild(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"
    first_embedder = FakeEmbedder()
    second_embedder = FakeEmbedder()
    first = build_version(
        root,
        corpus_dir,
        "run-one",
        embedder=first_embedder,
        activate=True,
    )
    first_manifest_bytes = (
        root / "versions" / "run-one" / "manifest.json"
    ).read_bytes()

    second = build_version(
        root,
        corpus_dir,
        "run-two",
        embedder=second_embedder,
        activate=True,
    )

    assert first.run_id == "run-one"
    assert second.run_id == "run-two"
    assert (root / "versions" / "run-one").is_dir()
    assert (root / "versions" / "run-two").is_dir()
    assert read_pointer(root)["run_id"] == "run-two"
    call_counts = (len(first_embedder.calls), len(second_embedder.calls))

    activate_version(root, "run-one")

    assert read_pointer(root)["run_id"] == "run-one"
    assert (root / "versions" / "run-one" / "manifest.json").read_bytes() == (
        first_manifest_bytes
    )
    assert (len(first_embedder.calls), len(second_embedder.calls)) == call_counts


def test_active_pointer_is_atomically_replaced_from_complete_json(
    tmp_path: Path,
    corpus_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "indexes-v2"
    build_version(root, corpus_dir, "run-one", activate=True)
    build_version(root, corpus_dir, "run-two")
    real_replace = os.replace
    observations: list[tuple[str, str]] = []

    def observed_replace(source, target) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if target_path == root / "active.json":
            staged = json.loads(source_path.read_text(encoding="utf-8"))
            previous = json.loads(target_path.read_text(encoding="utf-8"))
            observations.append((previous["run_id"], staged["run_id"]))
        real_replace(source, target)

    monkeypatch.setattr("app.indexing.store.os.replace", observed_replace)

    activate_version(root, "run-two")

    assert observations == [("run-one", "run-two")]
    assert read_pointer(root)["run_id"] == "run-two"
    assert list(root.glob(".active.json.*.tmp")) == []


def test_failed_build_cleans_staging_and_keeps_previous_active(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"
    build_version(root, corpus_dir, "run-one", activate=True)
    previous_pointer = (root / "active.json").read_bytes()

    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        build_version(
            root,
            corpus_dir,
            "run-two",
            embedder=FakeEmbedder(fail=True),
            activate=True,
        )

    assert (root / "active.json").read_bytes() == previous_pointer
    assert not (root / "versions" / "run-two").exists()
    assert list((root / "versions").glob(".run-two.staging-*")) == []


def test_force_refuses_unowned_version_directory_before_embedding(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"
    target = root / "versions" / "run-one"
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("not owned by this builder", encoding="utf-8")
    embedder = FakeEmbedder()

    with pytest.raises(PermissionError, match="refusing --force"):
        build_version(
            root,
            corpus_dir,
            "run-one",
            embedder=embedder,
            force=True,
        )

    assert marker.read_text(encoding="utf-8") == "not owned by this builder"
    assert embedder.calls == []


def test_force_cannot_rewrite_the_active_version_in_place(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"
    build_version(root, corpus_dir, "run-one", activate=True)
    previous_pointer = (root / "active.json").read_bytes()
    previous_manifest = (
        root / "versions" / "run-one" / "manifest.json"
    ).read_bytes()
    embedder = FakeEmbedder()

    with pytest.raises(PermissionError, match="active version"):
        build_version(
            root,
            corpus_dir,
            "run-one",
            embedder=embedder,
            force=True,
            activate=True,
        )

    assert (root / "active.json").read_bytes() == previous_pointer
    assert (root / "versions" / "run-one" / "manifest.json").read_bytes() == (
        previous_manifest
    )
    assert embedder.calls == []


def test_run_id_cannot_escape_version_root(
    tmp_path: Path,
    corpus_dir: Path,
) -> None:
    root = tmp_path / "indexes-v2"

    with pytest.raises(ValueError, match="run_id"):
        activate_version(root, "../escape")
    with pytest.raises(ValueError, match="run_id"):
        build_version(root, corpus_dir, "../escape")
    assert not (tmp_path / "escape").exists()
