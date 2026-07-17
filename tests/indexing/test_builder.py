from datetime import datetime, timedelta, timezone
from pathlib import Path

import faiss
import numpy as np
import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.indexing.builder import (
    build_index_artifacts,
    preview_build,
    validate_index_directory,
)
from app.ingestion.chunking import ChunkerConfig


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"
START = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
FINISH = START + timedelta(seconds=2)


def build_corpus(path: Path) -> Path:
    write_corpus(path, load_facts(FACTS), load_profile(PROFILE))
    return path


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[float]:
        self.calls.append(text)
        total = sum(ord(character) for character in text)
        return [
            float((total % 97) + 1),
            float((len(text) % 31) + 1),
            float((total % 17) + 1),
            1.0,
        ]


def test_preview_reports_measured_counts_without_embedding_or_writing(
    tmp_path: Path,
) -> None:
    corpus = build_corpus(tmp_path / "corpus")
    output = tmp_path / "index"

    preview = preview_build(
        input_dir=corpus,
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
    )

    assert preview.source_document_count == 72
    assert preview.canonical_document_count == 64
    assert preview.duplicate_count == 8
    assert preview.chunk_count == preview.indexed_chunk_count == 64
    assert not output.exists()


def test_builder_writes_validated_artifacts_with_one_embedding_per_indexed_chunk(
    tmp_path: Path,
) -> None:
    corpus = build_corpus(tmp_path / "corpus")
    output = tmp_path / "index"
    embedder = FakeEmbedder()

    manifest = build_index_artifacts(
        input_dir=corpus,
        output_dir=output,
        run_id="test-run",
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_model="fake-4d",
        embed_text=embedder,
        started_at=START,
        finished_at=FINISH,
    )

    assert manifest.embedding.dimension == 4
    assert manifest.indexed_chunk_count == len(embedder.calls) == 64
    assert {artifact.path for artifact in manifest.artifacts} == {
        "bm25_tokens.pkl",
        "chunks.json",
        "documents.json",
        "faiss.index",
        "parents.json",
    }
    assert (output / "manifest.json").is_file()
    index = faiss.deserialize_index(
        np.frombuffer((output / "faiss.index").read_bytes(), dtype=np.uint8).copy()
    )
    assert index.ntotal == 64
    assert index.d == 4
    validate_index_directory(output, manifest)


def test_builder_rejects_inconsistent_embedding_dimensions_before_writing(
    tmp_path: Path,
) -> None:
    corpus = build_corpus(tmp_path / "corpus")
    output = tmp_path / "index"
    calls = 0

    def inconsistent(text: str) -> list[float]:
        nonlocal calls
        calls += 1
        return [1.0, 2.0, 3.0] if calls == 1 else [1.0, 2.0]

    with pytest.raises(ValueError, match="embedding dimensions"):
        build_index_artifacts(
            input_dir=corpus,
            output_dir=output,
            run_id="bad-dimensions",
            chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
            embedding_model="broken",
            embed_text=inconsistent,
            started_at=START,
            finished_at=FINISH,
        )

    assert not output.exists()


def test_builder_refuses_nonempty_output_directory(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path / "corpus")
    output = tmp_path / "index"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        build_index_artifacts(
            input_dir=corpus,
            output_dir=output,
            run_id="refuse-overwrite",
            chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
            embedding_model="fake-4d",
            embed_text=FakeEmbedder(),
            started_at=START,
            finished_at=FINISH,
        )

    assert marker.read_text(encoding="utf-8") == "keep"
