from __future__ import annotations

import pytest

from app.indexing.incremental_computation import (
    CacheStatistics,
    ComputationMeasurements,
)
from app.indexing.paired_performance import (
    PairedArmMeasurement,
    PairedMeasurement,
    TargetEquivalenceFingerprint,
    summarize_paired_measurements,
)


HASHES = {
    name: f"{index:064x}"
    for index, name in enumerate(
        (
            "bundle",
            "base",
            "target",
            "change",
            "query",
            "pipeline",
            "host",
            "config",
            "catalog",
            "documents",
            "chunks",
            "embeddings",
            "document_ids",
            "indexed_chunk_ids",
            "parent_chunk_ids",
            "chunk_order",
            "query_result",
        ),
        start=1,
    )
}


def _arm(
    *,
    pair_number: int,
    arm: str,
    execution_order: int,
    total_seconds: float,
    embedding_calls: int,
) -> PairedArmMeasurement:
    return PairedArmMeasurement(
        experiment_id="g10-deterministic-v1",
        pair_number=pair_number,
        arm=arm,
        execution_order=execution_order,
        workspace_identity_sha256=(
            f"{pair_number * 2 + (arm == 'intervention'):064x}"
        ),
        target_cache_mode=(
            "cold" if arm == "baseline" else "warm"
        ),
        base_index_prestate_sha256="a" * 64,
        base_cache_prestate_sha256="b" * 64,
        bundle_manifest_sha256=HASHES["bundle"],
        base_catalog_sha256=HASHES["base"],
        target_catalog_sha256=HASHES["target"],
        change_set_sha256=HASHES["change"],
        query_set_sha256=HASHES["query"],
        pipeline_sha256=HASHES["pipeline"],
        embedding_model="deterministic-shake256-128",
        host_identity_sha256=HASHES["host"],
        configuration_sha256=HASHES["config"],
        coordinator_process_id=10_000 + pair_number,
        process_id=(
            pair_number * 2 + (1 if arm == "intervention" else 0)
        ),
        total_wall_seconds=total_seconds,
        input_validation_seconds=0.0,
        computation_wall_seconds=total_seconds * 0.7,
        publication_wall_seconds=total_seconds * 0.3,
        peak_rss_bytes=100_000_000,
        cache_statistics=CacheStatistics(
            parsed_hits=0,
            parsed_misses=embedding_calls,
            normalized_hits=0,
            normalized_misses=embedding_calls,
            chunk_hits=0,
            chunk_misses=embedding_calls,
            embedding_hits=0,
            embedding_misses=embedding_calls,
        ),
        computation_measurements=ComputationMeasurements(
            parse_calls=embedding_calls,
            normalize_calls=embedding_calls,
            chunk_calls=embedding_calls,
            embedding_calls=embedding_calls,
            artifact_serialization_seconds=0.01,
            total_wall_seconds=total_seconds * 0.7,
        ),
        target_fingerprint=TargetEquivalenceFingerprint(
            target_catalog_sha256=HASHES["catalog"],
            documents_sha256=HASHES["documents"],
            chunks_sha256=HASHES["chunks"],
            embeddings_sha256=HASHES["embeddings"],
            document_ids_sha256=HASHES["document_ids"],
            indexed_chunk_ids_sha256=HASHES["indexed_chunk_ids"],
            parent_chunk_ids_sha256=HASHES["parent_chunk_ids"],
            computation_chunk_order_sha256=HASHES["chunk_order"],
            query_fingerprint_sha256=HASHES["query_result"],
            active_index_deleted_residual_count=0,
        ),
    )


def test_supported_summary_uses_frozen_paired_decision_and_nearest_rank() -> None:
    pairs = []
    ratios = [0.50, 0.55, 0.60, 0.62, 0.65, 0.68, 0.70, 0.72, 0.74, 0.75]
    for pair_number, ratio in enumerate(ratios, start=1):
        baseline_first = pair_number % 2 == 1
        baseline = _arm(
            pair_number=pair_number,
            arm="baseline",
            execution_order=1 if baseline_first else 2,
            total_seconds=10.0,
            embedding_calls=1200,
        )
        intervention = _arm(
            pair_number=pair_number,
            arm="intervention",
            execution_order=2 if baseline_first else 1,
            total_seconds=10.0 * ratio,
            embedding_calls=51,
        )
        pairs.append(
            PairedMeasurement(
                baseline=baseline,
                intervention=intervention,
            )
        )

    summary = summarize_paired_measurements(pairs, expected_pair_count=10)

    assert summary.decision == "SUPPORTED"
    assert summary.faster_pair_count == 10
    assert summary.total_time_ratio.p50 == 0.65
    assert summary.total_time_ratio.p95 == 0.75
    assert summary.intervention_embedding_call_ratio == 51 / 1200
    assert summary.correctness_equivalent_pair_count == 10


def test_pair_rejects_a_target_correctness_mismatch_before_statistics() -> None:
    baseline = _arm(
        pair_number=1,
        arm="baseline",
        execution_order=1,
        total_seconds=10.0,
        embedding_calls=1200,
    )
    intervention = _arm(
        pair_number=1,
        arm="intervention",
        execution_order=2,
        total_seconds=5.0,
        embedding_calls=51,
    )
    mismatched = intervention.target_fingerprint.model_copy(
        update={"embeddings_sha256": "f" * 64}
    )

    with pytest.raises(ValueError, match="correctness fingerprints differ"):
        PairedMeasurement(
            baseline=baseline,
            intervention=intervention.model_copy(
                update={"target_fingerprint": mismatched}
            ),
        )


@pytest.mark.parametrize(
    ("ratios", "intervention_calls", "expected_decision"),
    [
        ([0.75] * 8 + [1.0] * 2, 120, "SUPPORTED"),
        ([1.05] * 10, 120, "REGRESSION"),
        ([0.80] * 10, 120, "NO_MEASURABLE_BENEFIT"),
    ],
)
def test_frozen_decision_threshold_boundaries(
    ratios: list[float],
    intervention_calls: int,
    expected_decision: str,
) -> None:
    pairs = []
    for pair_number, ratio in enumerate(ratios, start=1):
        baseline_first = pair_number % 2 == 1
        pairs.append(
            PairedMeasurement(
                baseline=_arm(
                    pair_number=pair_number,
                    arm="baseline",
                    execution_order=1 if baseline_first else 2,
                    total_seconds=10.0,
                    embedding_calls=1200,
                ),
                intervention=_arm(
                    pair_number=pair_number,
                    arm="intervention",
                    execution_order=2 if baseline_first else 1,
                    total_seconds=10.0 * ratio,
                    embedding_calls=intervention_calls,
                ),
            )
        )

    summary = summarize_paired_measurements(pairs, expected_pair_count=10)

    assert summary.decision == expected_decision
