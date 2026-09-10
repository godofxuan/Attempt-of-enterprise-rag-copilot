import hashlib
import json

import pytest

from app.indexing.builder import build_index_artifacts, validate_index_directory
from app.indexing.manifest import serialize_index_manifest
from app.indexing.store import activate_version, load_index_version
from app.ingestion.chunking import ChunkerConfig
from tests.indexing.test_builder import FINISH, START, FakeEmbedder, build_corpus


def build(root, run_id, mode="structure"):
    corpus = build_corpus(root / ("corpus-" + run_id))
    output = root / "indexes" / "versions" / run_id
    manifest = build_index_artifacts(
        input_dir=corpus,
        output_dir=output,
        run_id=run_id,
        chunker_config=ChunkerConfig(mode=mode),
        embedding_model="fake-4d",
        embed_text=FakeEmbedder(),
        started_at=START,
        finished_at=FINISH,
    )
    return output, manifest


def test_structure_quality_is_manifest_bound_and_recomputed(tmp_path):
    output, manifest = build(tmp_path, "structure")
    reports = json.loads((output / "document_quality.json").read_text(encoding="utf-8"))
    assert len(reports) == manifest.canonical_document_count
    assert all(report["decision"] == "ACCEPT" for report in reports)
    reports[0]["parser_version"] = "forged"
    changed = json.dumps(reports).encode()
    (output / "document_quality.json").write_bytes(changed)
    artifacts = [
        entry.model_copy(
            update={"sha256": hashlib.sha256(changed).hexdigest(), "byte_count": len(changed)}
        )
        if entry.path == "document_quality.json"
        else entry
        for entry in manifest.artifacts
    ]
    rebound = manifest.model_copy(update={"artifacts": artifacts})
    (output / "manifest.json").write_bytes(serialize_index_manifest(rebound))
    with pytest.raises(ValueError, match="document quality artifact"):
        validate_index_directory(output, rebound)


def test_missing_quality_does_not_replace_active_index(tmp_path):
    _, legacy = build(tmp_path, "legacy", "fixed")
    root = tmp_path / "indexes"
    activate_version(root, legacy.run_id)
    before = (root / "active.json").read_bytes()
    output, _ = build(tmp_path, "candidate")
    (output / "document_quality.json").unlink()
    with pytest.raises(FileNotFoundError):
        activate_version(root, "candidate")
    assert (root / "active.json").read_bytes() == before
    assert load_index_version(root).manifest.run_id == "legacy"


def test_structure_can_activate_and_return_to_legacy_in_isolated_store(tmp_path):
    build(tmp_path, "legacy", "fixed")
    build(tmp_path, "candidate")
    root = tmp_path / "indexes"
    activate_version(root, "legacy")
    activate_version(root, "candidate")
    assert load_index_version(root).manifest.chunker_config["mode"] == "structure"
    activate_version(root, "legacy")
    assert load_index_version(root).manifest.chunker_config["mode"] == "fixed"
