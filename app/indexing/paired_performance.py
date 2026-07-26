from __future__ import annotations

import math
from statistics import fmean
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.indexing.incremental_computation import (
    CacheStatistics,
    ComputationMeasurements,
)
from app.observability.metrics import nearest_rank_percentile


PairedArm = Literal["baseline", "intervention"]
PairedDecision = Literal[
    "SUPPORTED",
    "NO_MEASURABLE_BENEFIT",
    "REGRESSION",
]
JsonThreshold = bool | float | int | str


class PairedPerformanceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class PairedDecisionProtocol(PairedPerformanceModel):
    active_index_deletion_residual_count: Literal[0] = 0
    correctness_equivalent_pairs: int = Field(ge=1)
    faster_pair_count_at_least: int = Field(ge=1)
    intervention_embedding_call_ratio_at_most: float = Field(
        ge=0.0,
        le=1.0,
    )
    median_total_time_ratio_at_most: float = Field(gt=0.0)
    median_total_time_ratio_regression_at_or_above: float = Field(gt=0.0)
    any_active_index_deletion_residual: Literal[True] = True
    any_correctness_mismatch: Literal[True] = True
    infrastructure_failure_status: Literal["INCONCLUSIVE"] = "INCONCLUSIVE"
    unrepresentable_frozen_dataset_status: Literal["BLOCKED"] = "BLOCKED"

    @model_validator(mode="after")
    def validate_threshold_order(self) -> PairedDecisionProtocol:
        if (
            self.faster_pair_count_at_least
            > self.correctness_equivalent_pairs
            or self.median_total_time_ratio_at_most
            >= self.median_total_time_ratio_regression_at_or_above
        ):
            raise ValueError("paired decision thresholds are inconsistent")
        return self


def frozen_decision_protocol(pair_count: int) -> PairedDecisionProtocol:
    if pair_count < 1:
        raise ValueError("pair_count must be positive")
    return PairedDecisionProtocol(
        correctness_equivalent_pairs=pair_count,
        faster_pair_count_at_least=math.ceil(pair_count * 0.8),
        intervention_embedding_call_ratio_at_most=0.10,
        median_total_time_ratio_at_most=0.75,
        median_total_time_ratio_regression_at_or_above=1.05,
    )


def decision_protocol_from_experiment_thresholds(
    *,
    success_thresholds: Mapping[str, JsonThreshold],
    failure_thresholds: Mapping[str, JsonThreshold],
    expected_pair_count: int,
) -> PairedDecisionProtocol:
    combined = {
        **success_thresholds,
        **failure_thresholds,
    }
    if len(combined) != len(success_thresholds) + len(failure_thresholds):
        raise ValueError("success and failure threshold names overlap")
    protocol = PairedDecisionProtocol.model_validate(combined)
    if protocol != frozen_decision_protocol(expected_pair_count):
        raise ValueError(
            "experiment thresholds differ from the frozen G10 protocol"
        )
    return protocol


class TargetEquivalenceFingerprint(PairedPerformanceModel):
    schema_version: Literal["target_equivalence_fingerprint_v1"] = (
        "target_equivalence_fingerprint_v1"
    )
    target_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embeddings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    indexed_chunk_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_chunk_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    computation_chunk_order_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_index_deleted_residual_count: int = Field(ge=0)


class PairedArmMeasurement(PairedPerformanceModel):
    schema_version: Literal["paired_arm_measurement_v1"] = (
        "paired_arm_measurement_v1"
    )
    experiment_id: str = Field(min_length=1, max_length=128)
    pair_number: int = Field(ge=1)
    arm: PairedArm
    execution_order: int = Field(ge=1, le=2)
    workspace_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_cache_mode: Literal["cold", "warm"]
    base_index_prestate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_cache_prestate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: str = Field(min_length=1, max_length=256)
    host_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coordinator_process_id: int = Field(ge=1)
    process_id: int = Field(ge=1)
    total_wall_seconds: float = Field(gt=0.0)
    input_validation_seconds: float = Field(ge=0.0)
    computation_wall_seconds: float = Field(ge=0.0)
    publication_wall_seconds: float = Field(ge=0.0)
    peak_rss_bytes: int = Field(ge=0)
    cache_statistics: CacheStatistics
    computation_measurements: ComputationMeasurements
    target_fingerprint: TargetEquivalenceFingerprint

    @model_validator(mode="after")
    def validate_timing_boundary(self) -> PairedArmMeasurement:
        component_total = (
            self.input_validation_seconds
            + self.computation_wall_seconds
            + self.publication_wall_seconds
        )
        if component_total > self.total_wall_seconds * 1.001:
            raise ValueError(
                "computation and publication time exceed total wall time"
            )
        if (
            abs(
                self.computation_measurements.total_wall_seconds
                - self.computation_wall_seconds
            )
            > max(0.001, self.computation_wall_seconds * 0.001)
        ):
            raise ValueError(
                "production computation measurement does not match arm timing"
            )
        return self


_PAIR_IDENTITY_FIELDS = (
    "experiment_id",
    "pair_number",
    "bundle_manifest_sha256",
    "base_catalog_sha256",
    "target_catalog_sha256",
    "change_set_sha256",
    "query_set_sha256",
    "pipeline_sha256",
    "embedding_model",
    "host_identity_sha256",
    "configuration_sha256",
    "coordinator_process_id",
    "base_index_prestate_sha256",
    "base_cache_prestate_sha256",
)


class PairedMeasurement(PairedPerformanceModel):
    schema_version: Literal["paired_measurement_v1"] = "paired_measurement_v1"
    baseline: PairedArmMeasurement
    intervention: PairedArmMeasurement

    @model_validator(mode="after")
    def validate_pair(self) -> PairedMeasurement:
        if self.baseline.arm != "baseline":
            raise ValueError("baseline field must contain the baseline arm")
        if self.intervention.arm != "intervention":
            raise ValueError(
                "intervention field must contain the intervention arm"
            )
        for field_name in _PAIR_IDENTITY_FIELDS:
            if getattr(self.baseline, field_name) != getattr(
                self.intervention, field_name
            ):
                raise ValueError(
                    f"paired arms have mixed {field_name} identity"
                )
        if (
            self.baseline.workspace_identity_sha256
            == self.intervention.workspace_identity_sha256
        ):
            raise ValueError("paired arms must use separate workspace roots")
        if self.baseline.process_id == self.intervention.process_id:
            raise ValueError("paired arms must use separate worker processes")
        if (
            self.baseline.process_id == self.baseline.coordinator_process_id
            or self.intervention.process_id
            == self.intervention.coordinator_process_id
        ):
            raise ValueError("arm workers must be separate from the coordinator")
        if (
            self.baseline.target_cache_mode != "cold"
            or self.intervention.target_cache_mode != "warm"
        ):
            raise ValueError("paired arms use invalid cache prestates")
        expected_baseline_order = (
            1 if self.baseline.pair_number % 2 == 1 else 2
        )
        if (
            self.baseline.execution_order != expected_baseline_order
            or self.intervention.execution_order
            != 3 - expected_baseline_order
        ):
            raise ValueError("paired arms violate the frozen alternating order")
        if self.baseline.target_fingerprint != self.intervention.target_fingerprint:
            raise ValueError("paired target correctness fingerprints differ")
        if (
            self.baseline.target_fingerprint
            .active_index_deleted_residual_count
            != 0
        ):
            raise ValueError("paired target retains deleted active-index state")
        return self


class RatioDistribution(PairedPerformanceModel):
    count: int = Field(ge=1)
    minimum: float = Field(gt=0.0)
    maximum: float = Field(gt=0.0)
    mean: float = Field(gt=0.0)
    p50: float = Field(gt=0.0)
    p95: float = Field(gt=0.0)


class PairedBenchmarkSummary(PairedPerformanceModel):
    schema_version: Literal["paired_benchmark_summary_v1"] = (
        "paired_benchmark_summary_v1"
    )
    experiment_id: str
    pair_count: int = Field(ge=1)
    correctness_equivalent_pair_count: int = Field(ge=0)
    faster_pair_count: int = Field(ge=0)
    total_time_ratio: RatioDistribution
    baseline_first_total_time_ratio: RatioDistribution
    intervention_first_total_time_ratio: RatioDistribution
    intervention_embedding_call_ratio: float = Field(ge=0.0)
    baseline_embedding_calls: int = Field(ge=1)
    intervention_embedding_calls: int = Field(ge=0)
    baseline_peak_rss_bytes: int = Field(ge=0)
    intervention_peak_rss_bytes: int = Field(ge=0)
    decision: PairedDecision


def _ratio_distribution(values: Sequence[float]) -> RatioDistribution:
    if not values or any(value <= 0.0 or not math.isfinite(value) for value in values):
        raise ValueError("paired ratios must be finite and positive")
    p50 = nearest_rank_percentile(values, 0.50)
    p95 = nearest_rank_percentile(values, 0.95)
    if p50 is None or p95 is None:
        raise AssertionError("non-empty ratio distribution has no percentile")
    return RatioDistribution(
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=fmean(values),
        p50=p50,
        p95=p95,
    )


def summarize_paired_measurements(
    measurements: Sequence[PairedMeasurement],
    *,
    expected_pair_count: int,
    decision_protocol: PairedDecisionProtocol | None = None,
) -> PairedBenchmarkSummary:
    if expected_pair_count < 1:
        raise ValueError("expected_pair_count must be positive")
    protocol = (
        frozen_decision_protocol(expected_pair_count)
        if decision_protocol is None
        else PairedDecisionProtocol.model_validate(
            decision_protocol.model_dump(mode="json")
        )
    )
    if protocol.correctness_equivalent_pairs != expected_pair_count:
        raise ValueError("decision protocol pair count does not match")
    pairs = sorted(
        (
            PairedMeasurement.model_validate(item.model_dump(mode="json"))
            for item in measurements
        ),
        key=lambda item: item.baseline.pair_number,
    )
    if len(pairs) != expected_pair_count:
        raise ValueError(
            f"expected {expected_pair_count} complete pairs, got {len(pairs)}"
        )
    if [item.baseline.pair_number for item in pairs] != list(
        range(1, expected_pair_count + 1)
    ):
        raise ValueError("paired measurement numbers must be contiguous")

    first = pairs[0].baseline
    repeated_identity_fields = tuple(
        field_name
        for field_name in _PAIR_IDENTITY_FIELDS
        if field_name not in {"pair_number", "coordinator_process_id"}
    )
    for pair in pairs[1:]:
        for field_name in repeated_identity_fields:
            if getattr(pair.baseline, field_name) != getattr(first, field_name):
                raise ValueError(
                    f"paired measurements use mixed {field_name} identity"
                )

    ratios = [
        pair.intervention.total_wall_seconds
        / pair.baseline.total_wall_seconds
        for pair in pairs
    ]
    distribution = _ratio_distribution(ratios)
    baseline_first_distribution = _ratio_distribution(
        [
            ratio
            for pair, ratio in zip(pairs, ratios, strict=True)
            if pair.baseline.execution_order == 1
        ]
    )
    intervention_first_distribution = _ratio_distribution(
        [
            ratio
            for pair, ratio in zip(pairs, ratios, strict=True)
            if pair.intervention.execution_order == 1
        ]
    )
    faster_pair_count = sum(value < 1.0 for value in ratios)
    baseline_embedding_calls = sum(
        pair.baseline.computation_measurements.embedding_calls
        for pair in pairs
    )
    intervention_embedding_calls = sum(
        pair.intervention.computation_measurements.embedding_calls
        for pair in pairs
    )
    embedding_ratio = intervention_embedding_calls / baseline_embedding_calls
    if (
        distribution.p50
        >= protocol.median_total_time_ratio_regression_at_or_above
    ):
        decision: PairedDecision = "REGRESSION"
    elif (
        distribution.p50 <= protocol.median_total_time_ratio_at_most
        and faster_pair_count >= protocol.faster_pair_count_at_least
        and embedding_ratio
        <= protocol.intervention_embedding_call_ratio_at_most
    ):
        decision = "SUPPORTED"
    else:
        decision = "NO_MEASURABLE_BENEFIT"

    return PairedBenchmarkSummary(
        experiment_id=first.experiment_id,
        pair_count=len(pairs),
        correctness_equivalent_pair_count=len(pairs),
        faster_pair_count=faster_pair_count,
        total_time_ratio=distribution,
        baseline_first_total_time_ratio=baseline_first_distribution,
        intervention_first_total_time_ratio=intervention_first_distribution,
        intervention_embedding_call_ratio=embedding_ratio,
        baseline_embedding_calls=baseline_embedding_calls,
        intervention_embedding_calls=intervention_embedding_calls,
        baseline_peak_rss_bytes=max(
            pair.baseline.peak_rss_bytes for pair in pairs
        ),
        intervention_peak_rss_bytes=max(
            pair.intervention.peak_rss_bytes for pair in pairs
        ),
        decision=decision,
    )


__all__ = [
    "PairedArmMeasurement",
    "PairedBenchmarkSummary",
    "PairedDecisionProtocol",
    "PairedMeasurement",
    "RatioDistribution",
    "TargetEquivalenceFingerprint",
    "decision_protocol_from_experiment_thresholds",
    "frozen_decision_protocol",
    "summarize_paired_measurements",
]
