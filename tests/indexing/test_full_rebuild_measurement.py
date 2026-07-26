from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.corpus.artifacts import write_corpus
from app.corpus.generator import load_facts, load_profile
from app.indexing.benchmark import (
    deterministic_embedding,
    measure_full_rebuild,
    summarize_full_rebuilds,
)
from app.ingestion.chunking import ChunkerConfig


ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE = ROOT / "data" / "v2" / "config" / "demo.json"


def test_full_rebuild_measurement_records_counts_phases_memory_and_hashes(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))

    measured = measure_full_rebuild(
        input_dir=corpus,
        output_dir=tmp_path / "index",
        run_id="measurement-001",
        repetition=1,
        chunker_config=ChunkerConfig(mode="fixed", chunk_size=500, overlap=80),
        embedding_backend="deterministic",
        embedding_model="deterministic-shake256-128",
        embed_text=deterministic_embedding,
        started_at=datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
    )

    assert measured.source_document_count == 72
    assert measured.canonical_document_count == 64
    assert measured.embedding_call_count == measured.indexed_chunk_count == 64
    assert measured.embedding_dimension == 128
    assert set(measured.phase_duration_ms) == {
        "prepare",
        "embedding",
        "index_construction",
        "artifact_serialization",
        "artifact_write",
        "validation",
    }
    assert all(value >= 0.0 for value in measured.phase_duration_ms.values())
    assert measured.total_duration_ms >= sum(measured.phase_duration_ms.values())
    assert measured.peak_rss_bytes > 0
    assert len(measured.corpus_manifest_sha256) == 64
    assert len(measured.artifact_set_sha256) == 64
    assert len(measured.output_manifest_sha256) == 64


def test_full_rebuild_summary_uses_nearest_rank_and_rejects_mixed_configurations(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    write_corpus(corpus, load_facts(FACTS), load_profile(PROFILE))
    build_timestamp = datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc)
    rows = []
    for repetition in range(1, 3):
        rows.append(
            measure_full_rebuild(
                input_dir=corpus,
                output_dir=tmp_path / f"index-{repetition}",
                run_id=f"measurement-{repetition:03d}",
                repetition=repetition,
                chunker_config=ChunkerConfig(
                    mode="fixed",
                    chunk_size=500,
                    overlap=80,
                ),
                embedding_backend="deterministic",
                embedding_model="deterministic-shake256-128",
                embed_text=deterministic_embedding,
                started_at=build_timestamp,
            )
        )

    summary = summarize_full_rebuilds(rows)

    assert summary.repetitions == 2
    assert summary.embedding_calls_per_run == [64, 64]
    assert summary.total_duration_ms.p50 > 0.0
    assert summary.total_duration_ms.p95 >= summary.total_duration_ms.p50
    assert set(summary.phase_duration_ms) == set(rows[0].phase_duration_ms)
    assert summary.distinct_artifact_set_hashes == 1

    mixed = list(rows)
    mixed[1] = mixed[1].model_copy(update={"embedding_model": "other-model"})
    with pytest.raises(ValueError, match="mixed configurations"):
        summarize_full_rebuilds(mixed)
