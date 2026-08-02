from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHADOW_WORKER_PROTOCOL_VERSION = "finqa_shadow_worker_replay_protocol_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowReplayDatasetV1(_StrictFrozenModel):
    repository: Literal["https://github.com/czyssrs/FinQA"]
    revision: Literal["0f16e2867befa6840783e58be38c9efb9229d742"]
    split: Literal["train"]
    split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_case_count: int = Field(ge=1)
    selection_algorithm: Literal[
        "sha256_seed_ascii_backslash_zero_case_id_ascending_then_case_id"
    ]
    selection_seed: str = Field(min_length=1, max_length=200)
    selected_case_count: int = Field(ge=1, le=10_000)
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_company_count: int = Field(ge=1)
    max_selected_units_per_case: int = Field(ge=1, le=64)
    typed_input_source: Literal["gold_program_structure_only"]
    prohibited_quality_fields: tuple[str, ...]

    @model_validator(mode="after")
    def validate_quality_boundary(self) -> FinQAShadowReplayDatasetV1:
        if set(self.prohibited_quality_fields) != {
            "answer",
            "exe_ans",
            "gold_inds",
            "ann_table_rows",
            "ann_text_rows",
            "target_labels",
        }:
            raise ValueError("E13 prohibited quality fields changed")
        return self


class FinQAShadowWorkerContractV1(_StrictFrozenModel):
    start_method: Literal["spawn"]
    topology: Literal["single_persistent_process_single_inflight_request"]
    startup_timeout_seconds: float = Field(gt=0, le=60)
    observation_timeout_seconds: float = Field(gt=0, le=30)
    termination_grace_seconds: float = Field(gt=0, le=10)
    max_request_bytes: int = Field(ge=1024, le=16 * 1024 * 1024)
    max_response_bytes: int = Field(ge=1024, le=1024 * 1024)
    restart_after_timeout: Literal[True]
    restart_after_crash: Literal[True]
    os_network_sandbox_claimed: Literal[False]


class FinQAShadowReplayGatesV1(_StrictFrozenModel):
    min_preparation_success_rate: float = Field(ge=0, le=1)
    min_observation_completion_rate: float = Field(ge=0, le=1)
    max_worker_error_count: int = Field(ge=0)
    max_worker_timeout_count: int = Field(ge=0)
    max_observation_latency_p95_ms: float = Field(gt=0)
    max_worker_peak_rss_bytes: int = Field(gt=0)
    require_all_primary_results_e8: Literal[True]
    require_zero_model_calls: Literal[True]
    require_aggregate_only_output: Literal[True]
    require_no_quality_labels_or_scores: Literal[True]


class FinQAShadowFaultGatesV1(_StrictFrozenModel):
    require_hard_timeout_terminates_worker: Literal[True]
    require_crash_detection_and_restart: Literal[True]
    require_oversized_request_rejected_before_ipc: Literal[True]
    require_malformed_response_rejected: Literal[True]
    require_primary_result_immutability: Literal[True]


class FinQAShadowPublicOutputV1(_StrictFrozenModel):
    per_request_rows_permitted: Literal[False]
    allowed_metric_groups: tuple[str, ...]
    prohibited_content: tuple[str, ...]

    @model_validator(mode="after")
    def validate_public_boundary(self) -> FinQAShadowPublicOutputV1:
        if self.allowed_metric_groups != (
            "preparation",
            "observations",
            "latency_ms",
            "worker_peak_rss_bytes",
            "fault_injection",
            "gate_checks",
        ):
            raise ValueError("E13 allowed metric groups changed")
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
        }:
            raise ValueError("E13 public-output prohibitions changed")
        return self


class FinQAShadowWorkerReplayProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_shadow_worker_replay_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E13_IMPLEMENTATION"]
    claim_label: Literal[
        "TRAIN_ONLY_UNLABELED_OPERATIONAL_REPLAY_NOT_QUALITY_EVIDENCE"
    ]
    source_e12_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e12_mechanism_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset: FinQAShadowReplayDatasetV1
    worker: FinQAShadowWorkerContractV1
    replay_gates: FinQAShadowReplayGatesV1
    fault_injection_gates: FinQAShadowFaultGatesV1
    public_output: FinQAShadowPublicOutputV1
    serving_champion: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_status: Literal["SHADOW_DEFAULT_OFF"]
    internal_cohort_status: Literal["CONSUMED_NOT_ACCESSED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_shadow_worker_replay_protocol_v1(
    path: Path,
) -> tuple[FinQAShadowWorkerReplayProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAShadowWorkerReplayProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQAShadowWorkerReplayProtocolV1",
    "SHADOW_WORKER_PROTOCOL_VERSION",
    "load_shadow_worker_replay_protocol_v1",
]
