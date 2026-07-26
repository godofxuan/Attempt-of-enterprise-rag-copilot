from __future__ import annotations

import hashlib
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.indexing.builder import (
    BuildPhase,
    EmbedText,
    build_index_artifacts,
)
from app.ingestion.chunking import ChunkerConfig
from app.observability.metrics import (
    nearest_rank_percentile,
    process_peak_rss_bytes,
)


EmbeddingBackend = Literal["deterministic", "ollama"]
EXPECTED_BUILD_PHASES: tuple[BuildPhase, ...] = (
    "prepare",
    "embedding",
    "index_construction",
    "artifact_serialization",
    "artifact_write",
    "validation",
)


class DurationDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=1)
    minimum: float = Field(ge=0.0)
    maximum: float = Field(ge=0.0)
    mean: float = Field(ge=0.0)
    p50: float = Field(ge=0.0)
    p95: float = Field(ge=0.0)


class FullRebuildMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["full_rebuild_measurement_v1"] = (
        "full_rebuild_measurement_v1"
    )
    run_id: str
    repetition: int = Field(ge=1)
    profile_id: str
    corpus_manifest_sha256: str
    source_document_count: int = Field(ge=1)
    canonical_document_count: int = Field(ge=1)
    chunk_count: int = Field(ge=1)
    indexed_chunk_count: int = Field(ge=1)
    embedding_backend: EmbeddingBackend
    embedding_model: str
    embedding_dimension: int = Field(ge=1)
    embedding_call_count: int = Field(ge=1)
    phase_duration_ms: dict[str, float]
    total_duration_ms: float = Field(ge=0.0)
    peak_rss_bytes: int = Field(ge=0)
    artifact_set_sha256: str
    output_manifest_sha256: str
    build_timestamp: datetime
    started_at: datetime
    finished_at: datetime
    python_version: str
    platform: str
    process_id: int = Field(ge=1)


class FullRebuildSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["full_rebuild_summary_v1"] = "full_rebuild_summary_v1"
    profile_id: str
    corpus_manifest_sha256: str
    embedding_backend: EmbeddingBackend
    embedding_model: str
    repetitions: int = Field(ge=1)
    source_document_count: int = Field(ge=1)
    canonical_document_count: int = Field(ge=1)
    indexed_chunk_count: int = Field(ge=1)
    embedding_calls_per_run: list[int]
    total_duration_ms: DurationDistribution
    phase_duration_ms: dict[str, DurationDistribution]
    peak_rss_bytes: DurationDistribution
    distinct_artifact_set_hashes: int = Field(ge=1)


def deterministic_embedding(text: str, dimension: int = 128) -> list[float]:
    if dimension <= 0:
        raise ValueError("embedding dimension must be positive")
    digest = hashlib.shake_256(text.encode("utf-8")).digest(dimension)
    return [(value - 127.5) / 127.5 for value in digest]


def measure_full_rebuild(
    *,
    input_dir: Path,
    output_dir: Path,
    run_id: str,
    repetition: int,
    chunker_config: ChunkerConfig,
    embedding_backend: EmbeddingBackend,
    embedding_model: str,
    embed_text: EmbedText,
    started_at: datetime | None = None,
) -> FullRebuildMeasurement:
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    corpus_manifest = input_dir / "manifest.json"
    corpus_manifest_sha256 = hashlib.sha256(corpus_manifest.read_bytes()).hexdigest()
    phase_duration_ms: dict[str, float] = {}
    embedding_call_count = 0

    def observe(phase: BuildPhase, duration_ms: float) -> None:
        if phase in phase_duration_ms:
            raise RuntimeError(f"build phase was observed twice: {phase}")
        phase_duration_ms[phase] = duration_ms

    def counted_embedding(text: str) -> list[float]:
        nonlocal embedding_call_count
        vector = embed_text(text)
        embedding_call_count += 1
        return vector

    observed_start = datetime.now(timezone.utc)
    build_timestamp = started_at or observed_start
    total_started = time.perf_counter()
    manifest = build_index_artifacts(
        input_dir=input_dir,
        output_dir=output_dir,
        run_id=run_id,
        chunker_config=chunker_config,
        embedding_model=embedding_model,
        embed_text=counted_embedding,
        started_at=build_timestamp,
        finished_at=build_timestamp,
        phase_observer=observe,
    )
    total_duration_ms = max(0.0, (time.perf_counter() - total_started) * 1000.0)
    observed_finish = datetime.now(timezone.utc)

    if tuple(phase_duration_ms) != EXPECTED_BUILD_PHASES:
        raise RuntimeError(
            "incomplete build phase observations: "
            f"expected {EXPECTED_BUILD_PHASES}, got {tuple(phase_duration_ms)}"
        )
    if embedding_call_count != manifest.indexed_chunk_count:
        raise RuntimeError(
            "embedding call count does not match indexed chunk count: "
            f"{embedding_call_count} != {manifest.indexed_chunk_count}"
        )

    peak_rss = process_peak_rss_bytes()
    artifact_set_sha256 = _artifact_set_sha256(manifest.artifacts)
    output_manifest_sha256 = hashlib.sha256(
        (output_dir / "manifest.json").read_bytes()
    ).hexdigest()
    return FullRebuildMeasurement(
        run_id=run_id,
        repetition=repetition,
        profile_id=manifest.profile_id,
        corpus_manifest_sha256=corpus_manifest_sha256,
        source_document_count=manifest.source_document_count,
        canonical_document_count=manifest.canonical_document_count,
        chunk_count=manifest.chunk_count,
        indexed_chunk_count=manifest.indexed_chunk_count,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        embedding_dimension=manifest.embedding.dimension,
        embedding_call_count=embedding_call_count,
        phase_duration_ms=phase_duration_ms,
        total_duration_ms=total_duration_ms,
        peak_rss_bytes=peak_rss or 0,
        artifact_set_sha256=artifact_set_sha256,
        output_manifest_sha256=output_manifest_sha256,
        build_timestamp=build_timestamp,
        started_at=observed_start,
        finished_at=observed_finish,
        python_version=platform.python_version(),
        platform=platform.platform(),
        process_id=os.getpid(),
    )


def summarize_full_rebuilds(
    measurements: Sequence[FullRebuildMeasurement],
) -> FullRebuildSummary:
    rows = sorted(measurements, key=lambda row: row.repetition)
    if not rows:
        raise ValueError("at least one full rebuild measurement is required")
    first = rows[0]
    configuration = (
        first.profile_id,
        first.corpus_manifest_sha256,
        first.embedding_backend,
        first.embedding_model,
        first.source_document_count,
        first.canonical_document_count,
        first.indexed_chunk_count,
    )
    for row in rows[1:]:
        observed = (
            row.profile_id,
            row.corpus_manifest_sha256,
            row.embedding_backend,
            row.embedding_model,
            row.source_document_count,
            row.canonical_document_count,
            row.indexed_chunk_count,
        )
        if observed != configuration:
            raise ValueError("full rebuild measurements use mixed configurations")
    repetitions = [row.repetition for row in rows]
    if len(repetitions) != len(set(repetitions)):
        raise ValueError("full rebuild repetition numbers must be unique")

    return FullRebuildSummary(
        profile_id=first.profile_id,
        corpus_manifest_sha256=first.corpus_manifest_sha256,
        embedding_backend=first.embedding_backend,
        embedding_model=first.embedding_model,
        repetitions=len(rows),
        source_document_count=first.source_document_count,
        canonical_document_count=first.canonical_document_count,
        indexed_chunk_count=first.indexed_chunk_count,
        embedding_calls_per_run=[row.embedding_call_count for row in rows],
        total_duration_ms=_distribution(
            [row.total_duration_ms for row in rows]
        ),
        phase_duration_ms={
            phase: _distribution(
                [row.phase_duration_ms[phase] for row in rows]
            )
            for phase in EXPECTED_BUILD_PHASES
        },
        peak_rss_bytes=_distribution(
            [float(row.peak_rss_bytes) for row in rows]
        ),
        distinct_artifact_set_hashes=len(
            {row.artifact_set_sha256 for row in rows}
        ),
    )


def _artifact_set_sha256(artifacts) -> str:
    digest = hashlib.sha256()
    for artifact in sorted(artifacts, key=lambda item: item.path):
        digest.update(artifact.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(artifact.sha256.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(artifact.byte_count).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _distribution(values: Sequence[float]) -> DurationDistribution:
    if not values:
        raise ValueError("distribution requires at least one value")
    p50 = nearest_rank_percentile(values, 0.50)
    p95 = nearest_rank_percentile(values, 0.95)
    if p50 is None or p95 is None:
        raise AssertionError("non-empty distribution has no percentile")
    return DurationDistribution(
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=fmean(values),
        p50=p50,
        p95=p95,
    )


__all__ = [
    "DurationDistribution",
    "EXPECTED_BUILD_PHASES",
    "FullRebuildMeasurement",
    "FullRebuildSummary",
    "deterministic_embedding",
    "measure_full_rebuild",
    "summarize_full_rebuilds",
]
