from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.run_manifest import build_run_manifest


def test_manifest_records_actual_non_sensitive_provenance(tmp_path: Path) -> None:
    dataset = tmp_path / "dev.json"
    dataset.write_text('[{"case_id":"one"},{"case_id":"two"}]', encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "enterprise_corpus_manifest_v1",
                "producer": "enterprise_agentic_rag_v2",
                "generator_version": "test-generator",
                "profile_id": "demo",
                "document_count": 2,
            }
        ),
        encoding="utf-8",
    )

    manifest = build_run_manifest(
        run_id="run-001",
        suite="all",
        split="dev",
        mode="deterministic",
        dataset_path=dataset,
        corpus_dir=corpus_dir,
        index_root=tmp_path / "absent-index",
        config={
            "top_k": 5,
            "candidate_k": 20,
            "chat_model": "qwen-test",
            "llm_api_key": "must-not-appear",
        },
        runtime={
            "variant": "hash-128-extractive",
            "embedding_model": "deterministic-hash-128",
            "model_calls": 0,
        },
        repository_root=Path.cwd(),
    )

    payload = manifest.model_dump(mode="json")
    serialized = json.dumps(payload)
    assert manifest.dataset.case_count == 2
    assert len(manifest.dataset.sha256) == 64
    assert manifest.corpus.profile_id == "demo"
    assert manifest.corpus.document_count == 2
    assert manifest.index.status == "not_available"
    assert manifest.config["top_k"] == 5
    assert manifest.config["llm_api_key"] == "<redacted>"
    assert "must-not-appear" not in serialized
    assert manifest.git.head
    assert isinstance(manifest.git.dirty, bool)
    assert manifest.environment.python_version
    assert "pytest" in manifest.environment.packages


def test_manifest_rejects_non_array_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "dev.json"
    dataset.write_text('{"not":"an array"}', encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "manifest.json").write_text("{}", encoding="utf-8")

    try:
        build_run_manifest(
            run_id="run-001",
            suite="all",
            split="dev",
            mode="deterministic",
            dataset_path=dataset,
            corpus_dir=corpus_dir,
            index_root=None,
            config={},
            runtime={},
            repository_root=Path.cwd(),
        )
    except ValueError as exc:
        assert "JSON array" in str(exc)
    else:
        raise AssertionError("non-array dataset must be rejected")
