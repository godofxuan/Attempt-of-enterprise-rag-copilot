from __future__ import annotations

import pytest

from app.external_datasets.enterprise_dense_capacity import (
    DenseQualificationCheckpoint,
    decide_full_dense_run,
)


def _checkpoint(count: int, rate: float) -> DenseQualificationCheckpoint:
    return DenseQualificationCheckpoint(
        chunk_count=count,
        elapsed_seconds=count / rate,
        chunks_per_second=rate,
        input_characters=count * 100,
        vector_bytes=count * 1024 * 4,
        process_peak_rss_bytes=100_000_000,
        error_count=0,
    )


def test_dense_capacity_fails_closed_without_builder_and_dev_protocol() -> None:
    decision = decide_full_dense_run(
        [
            _checkpoint(1_000, 60),
            _checkpoint(10_000, 55),
            _checkpoint(50_000, 50),
        ],
        full_chunk_count=1_702_370,
        embedding_dimension=1024,
        available_disk_bytes=50_000_000_000,
        sharded_builder_ready=False,
        development_protocol_ready=False,
    )

    assert decision.decision == "FULL_DENSE_NO_GO"
    assert "resumable_sharded_builder_ready" in decision.reasons
    assert "development_quality_protocol_ready" in decision.reasons


def test_dense_capacity_rejects_unregistered_checkpoint_shape() -> None:
    with pytest.raises(ValueError, match="exactly 1k, 10k, and 50k"):
        decide_full_dense_run(
            [_checkpoint(1_000, 60)] * 3,
            full_chunk_count=1_702_370,
            embedding_dimension=1024,
            available_disk_bytes=50_000_000_000,
            sharded_builder_ready=True,
            development_protocol_ready=True,
        )
