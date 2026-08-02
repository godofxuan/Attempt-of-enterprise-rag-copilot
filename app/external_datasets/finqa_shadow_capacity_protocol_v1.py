from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHADOW_CAPACITY_PROTOCOL_VERSION = "finqa_shadow_capacity_protocol_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowCapacityMatrixV1(_StrictFrozenModel):
    worker_counts: tuple[int, ...]
    caller_concurrency: tuple[int, ...]
    repetitions: int = Field(ge=2, le=10)
    queue_capacity: int = Field(ge=1, le=256)
    admission_timeout_seconds: float = Field(ge=0, le=30)
    response_deadline_seconds: float = Field(gt=0, le=60)
    shutdown_grace_seconds: float = Field(gt=0, le=60)
    setup_timing: Literal["excluded_from_observation_elapsed_time"]
    preparation_timing: Literal["once_before_all_trials"]
    process_lifetime: Literal["fresh_pool_per_trial_reused_within_trial"]
    workload_order: Literal["fixed_e13_selection_order_for_every_trial"]
    schedule_algorithm: Literal[
        "repeat_0_ascending_repeat_1_reversed_repeat_2_rotate_left_3"
    ]

    @model_validator(mode="after")
    def validate_frozen_matrix(self) -> FinQAShadowCapacityMatrixV1:
        if self.worker_counts != (1, 2, 4):
            raise ValueError("E15 worker-count matrix changed")
        if self.caller_concurrency != (1, 4, 8):
            raise ValueError("E15 caller-concurrency matrix changed")
        if self.repetitions != 3:
            raise ValueError("E15 repetition count changed")
        if max(self.caller_concurrency) > max(self.worker_counts) + self.queue_capacity:
            raise ValueError("E15 maximum concurrency exceeds bounded capacity")
        return self


class FinQAShadowCapacityComparisonV1(_StrictFrozenModel):
    comparison_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    baseline_worker_count: int = Field(ge=1)
    candidate_worker_count: int = Field(ge=1)
    caller_concurrency: int = Field(ge=1)
    min_median_throughput_speedup: float = Field(gt=1)
    min_worker_scaling_efficiency: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_scaling_direction(self) -> FinQAShadowCapacityComparisonV1:
        if self.candidate_worker_count <= self.baseline_worker_count:
            raise ValueError("E15 comparison must increase worker count")
        return self


class FinQAShadowCapacityGatesV1(_StrictFrozenModel):
    min_preparation_success_rate: float = Field(ge=0, le=1)
    required_trial_count: int = Field(ge=1)
    min_trial_completion_rate: float = Field(ge=0, le=1)
    max_backpressure_rejections: int = Field(ge=0)
    max_deadline_exceeded: int = Field(ge=0)
    max_worker_errors: int = Field(ge=0)
    max_worker_restarts: int = Field(ge=0)
    max_end_to_end_latency_p95_ms: float = Field(gt=0)
    max_four_worker_rss_upper_bound_bytes: int = Field(gt=0)
    max_throughput_relative_spread: float = Field(ge=0)
    comparisons: tuple[FinQAShadowCapacityComparisonV1, ...]
    require_expected_active_worker_high_watermark: Literal[True]
    require_no_residual_workers_after_each_trial: Literal[True]
    require_all_primary_results_e8: Literal[True]
    require_zero_model_calls: Literal[True]
    require_aggregate_only_output: Literal[True]
    require_no_quality_labels_or_scores: Literal[True]

    @model_validator(mode="after")
    def validate_frozen_comparisons(self) -> FinQAShadowCapacityGatesV1:
        expected = (
            ("workers_1_to_2_callers_4", 1, 2, 4),
            ("workers_1_to_4_callers_8", 1, 4, 8),
        )
        actual = tuple(
            (
                item.comparison_id,
                item.baseline_worker_count,
                item.candidate_worker_count,
                item.caller_concurrency,
            )
            for item in self.comparisons
        )
        if actual != expected:
            raise ValueError("E15 frozen scaling comparisons changed")
        return self


class FinQAShadowCapacityPublicOutputV1(_StrictFrozenModel):
    per_request_rows_permitted: Literal[False]
    per_trial_aggregate_rows_permitted: Literal[True]
    allowed_metric_groups: tuple[str, ...]
    prohibited_content: tuple[str, ...]

    @model_validator(mode="after")
    def validate_public_boundary(self) -> FinQAShadowCapacityPublicOutputV1:
        if self.allowed_metric_groups != (
            "preparation",
            "trial_aggregates",
            "configuration_aggregates",
            "scaling_comparisons",
            "local_recommendation",
            "gate_checks",
        ):
            raise ValueError("E15 allowed metric groups changed")
        if set(self.prohibited_content) != {
            "question_text",
            "numeric_values",
            "case_ids",
            "company_ids",
            "descriptor_ids",
            "candidate_ids",
            "evidence_ids",
            "source_ids",
            "provenance",
            "ranked_scores",
            "per_request_latency",
            "per_request_outcome",
            "worker_slot_assignments",
        }:
            raise ValueError("E15 public-output prohibitions changed")
        return self


class FinQAShadowCapacityProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_shadow_capacity_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E15_IMPLEMENTATION"]
    claim_label: Literal[
        "TRAIN_ONLY_UNLABELED_LOCAL_CAPACITY_ENVELOPE_NOT_PRODUCTION_SLO"
    ]
    source_e14_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e14_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e13_selection_reused: Literal[True]
    matrix: FinQAShadowCapacityMatrixV1
    gates: FinQAShadowCapacityGatesV1
    public_output: FinQAShadowCapacityPublicOutputV1
    serving_champion: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_status: Literal["SHADOW_DEFAULT_OFF"]
    internal_cohort_status: Literal["CONSUMED_NOT_ACCESSED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_shadow_capacity_protocol_v1(
    path: Path,
) -> tuple[FinQAShadowCapacityProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAShadowCapacityProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQAShadowCapacityProtocolV1",
    "SHADOW_CAPACITY_PROTOCOL_VERSION",
    "load_shadow_capacity_protocol_v1",
]
