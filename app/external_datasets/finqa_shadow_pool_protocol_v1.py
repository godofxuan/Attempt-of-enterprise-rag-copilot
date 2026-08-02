from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHADOW_POOL_PROTOCOL_VERSION = "finqa_shadow_pool_replay_protocol_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowPoolContractV1(_StrictFrozenModel):
    topology: Literal["bounded_fifo_dispatch_over_isolated_spawn_workers"]
    worker_count: int = Field(ge=2, le=16)
    queue_capacity: int = Field(ge=1, le=256)
    caller_concurrency: int = Field(ge=1, le=256)
    admission_timeout_seconds: float = Field(ge=0, le=30)
    response_deadline_seconds: float = Field(gt=0, le=60)
    shutdown_grace_seconds: float = Field(gt=0, le=60)
    overload_policy: Literal["reject_newest"]
    queue_discipline: Literal["fifo"]
    late_result_policy: Literal["discard_without_primary_mutation"]
    eager_worker_start: Literal[True]
    per_worker_single_inflight: Literal[True]
    durable_queue_claimed: Literal[False]
    distributed_scheduler_claimed: Literal[False]

    @model_validator(mode="after")
    def validate_capacity(self) -> FinQAShadowPoolContractV1:
        if self.caller_concurrency > self.worker_count + self.queue_capacity:
            raise ValueError("nominal caller concurrency exceeds bounded capacity")
        return self


class FinQAShadowPoolReplayGatesV1(_StrictFrozenModel):
    min_preparation_success_rate: float = Field(ge=0, le=1)
    min_admitted_completion_rate: float = Field(ge=0, le=1)
    max_nominal_backpressure_rejections: int = Field(ge=0)
    max_nominal_deadline_exceeded: int = Field(ge=0)
    max_nominal_worker_errors: int = Field(ge=0)
    min_active_worker_high_watermark: int = Field(ge=1)
    max_queue_high_watermark: int = Field(ge=1)
    max_end_to_end_latency_p95_ms: float = Field(gt=0)
    max_worker_pool_rss_upper_bound_bytes: int = Field(gt=0)
    require_all_primary_results_e8: Literal[True]
    require_zero_model_calls: Literal[True]
    require_aggregate_only_output: Literal[True]
    require_no_quality_labels_or_scores: Literal[True]


class FinQAShadowPoolFaultGatesV1(_StrictFrozenModel):
    require_queue_bound_enforced: Literal[True]
    require_overload_rejected_without_primary_mutation: Literal[True]
    require_queued_deadline_expires_before_execution: Literal[True]
    require_late_result_discarded: Literal[True]
    require_worker_fault_isolated_to_slot: Literal[True]
    require_close_rejects_new_work: Literal[True]
    require_no_residual_workers_after_close: Literal[True]


class FinQAShadowPoolPublicOutputV1(_StrictFrozenModel):
    per_request_rows_permitted: Literal[False]
    allowed_metric_groups: tuple[str, ...]
    prohibited_content: tuple[str, ...]

    @model_validator(mode="after")
    def validate_public_boundary(self) -> FinQAShadowPoolPublicOutputV1:
        if self.allowed_metric_groups != (
            "preparation",
            "load",
            "queue_wait_ms",
            "end_to_end_latency_ms",
            "worker_pool_resources",
            "fault_injection",
            "gate_checks",
        ):
            raise ValueError("E14 allowed metric groups changed")
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
            raise ValueError("E14 public-output prohibitions changed")
        return self


class FinQAShadowPoolReplayProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_shadow_pool_replay_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E14_IMPLEMENTATION"]
    claim_label: Literal[
        "TRAIN_ONLY_UNLABELED_BOUNDED_CONCURRENCY_EVIDENCE_NOT_QUALITY_EVIDENCE"
    ]
    source_e13_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e13_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e13_selection_reused: Literal[True]
    pool: FinQAShadowPoolContractV1
    replay_gates: FinQAShadowPoolReplayGatesV1
    fault_injection_gates: FinQAShadowPoolFaultGatesV1
    public_output: FinQAShadowPoolPublicOutputV1
    serving_champion: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_status: Literal["SHADOW_DEFAULT_OFF"]
    internal_cohort_status: Literal["CONSUMED_NOT_ACCESSED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_shadow_pool_replay_protocol_v1(
    path: Path,
) -> tuple[FinQAShadowPoolReplayProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAShadowPoolReplayProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQAShadowPoolReplayProtocolV1",
    "SHADOW_POOL_PROTOCOL_VERSION",
    "load_shadow_pool_replay_protocol_v1",
]
