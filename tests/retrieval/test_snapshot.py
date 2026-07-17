from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import MappingProxyType

import pytest

from app.indexing.manifest import load_index_manifest, serialize_index_manifest
from app.retrieval.snapshot import V2IndexSnapshot


def copy_store(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def refresh_active_hash(root: Path) -> None:
    pointer_path = root / "active.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    manifest_path = root / "versions" / pointer["run_id"] / "manifest.json"
    pointer["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    pointer_path.write_text(
        json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_snapshot_loads_active_artifacts_in_exact_index_order(
    v2_index_root: Path,
) -> None:
    snapshot = V2IndexSnapshot.load(v2_index_root)
    manifest = snapshot.version.manifest

    assert snapshot.version.manifest.run_id == "parent-child-run"
    assert len(snapshot.chunks) == manifest.indexed_chunk_count
    assert snapshot.faiss_index.ntotal == manifest.indexed_chunk_count
    assert snapshot.faiss_index.d == manifest.embedding.dimension == 4
    assert snapshot.bm25.corpus_size == manifest.indexed_chunk_count
    assert len(snapshot.bm25_tokens) == manifest.indexed_chunk_count
    assert [snapshot.chunk_index_by_id[chunk.chunk_id] for chunk in snapshot.chunks] == (
        list(range(manifest.indexed_chunk_count))
    )


def test_snapshot_loads_parent_and_document_maps(v2_index_root: Path) -> None:
    snapshot = V2IndexSnapshot.load(v2_index_root)
    manifest = snapshot.version.manifest

    assert isinstance(snapshot.parents_by_id, MappingProxyType)
    assert isinstance(snapshot.documents_by_id, MappingProxyType)
    assert len(snapshot.parents_by_id) == (
        manifest.chunk_count - manifest.indexed_chunk_count
    )
    assert len(snapshot.documents_by_id) == manifest.canonical_document_count
    assert all(parent.kind == "parent" and not parent.indexable for parent in snapshot.parents_by_id.values())
    children = [chunk for chunk in snapshot.chunks if chunk.kind == "child"]
    assert children
    assert all(chunk.parent_chunk_id in snapshot.parents_by_id for chunk in children)
    assert all(chunk.doc_id in snapshot.documents_by_id for chunk in snapshot.chunks)


def test_snapshot_supports_unicode_store_path(
    tmp_path: Path,
    v2_index_root: Path,
) -> None:
    copied = copy_store(v2_index_root, tmp_path / "中文索引")

    snapshot = V2IndexSnapshot.load(copied)

    assert snapshot.version.path.parent.name == "versions"
    assert snapshot.version.manifest.run_id == "parent-child-run"


def test_snapshot_requires_an_active_pointer(tmp_path: Path) -> None:
    root = tmp_path / "indexes-v2"
    root.mkdir()

    with pytest.raises(FileNotFoundError, match="active.json"):
        V2IndexSnapshot.load(root)


def test_tampered_pickle_is_rejected_before_deserialization(
    tmp_path: Path,
    v2_index_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = copy_store(v2_index_root, tmp_path / "tampered")
    tokens_path = root / "versions" / "parent-child-run" / "bm25_tokens.pkl"
    payload = tokens_path.read_bytes()
    tokens_path.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])

    def fail_if_deserialized(*args, **kwargs):
        raise AssertionError("pickle must not be loaded before hash validation")

    monkeypatch.setattr("app.indexing.builder.pickle.load", fail_if_deserialized)

    with pytest.raises(ValueError, match="hash mismatch"):
        V2IndexSnapshot.load(root)


def test_snapshot_rejects_manifest_with_unknown_faiss_contract(
    tmp_path: Path,
    v2_index_root: Path,
) -> None:
    root = copy_store(v2_index_root, tmp_path / "unknown-faiss")
    manifest_path = root / "versions" / "parent-child-run" / "manifest.json"
    manifest = load_index_manifest(manifest_path)
    manifest = manifest.model_copy(
        update={
            "faiss": manifest.faiss.model_copy(
                update={"index_type": "UnsupportedIndex"}
            )
        }
    )
    manifest_path.write_bytes(serialize_index_manifest(manifest))
    refresh_active_hash(root)

    with pytest.raises(ValueError, match="FAISS index type"):
        V2IndexSnapshot.load(root)
