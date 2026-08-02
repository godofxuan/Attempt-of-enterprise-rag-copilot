from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SHADOW_PROTOCOL_VERSION = "finqa_descriptor_shadow_protocol_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAShadowRuntimeContractV1(_StrictFrozenModel):
    default_mode: Literal["OFF"]
    champion_version: Literal["finqa_deterministic_descriptor_retriever_v5"]
    challenger_version: Literal["finqa_top4_boundary_ranker_v1"]
    primary_must_complete_before_shadow: Literal[True]
    challenger_replacement_permitted: Literal[False]
    challenger_model_calls_permitted: Literal[False]
    observation_timeout_ms: float = Field(gt=0, le=5_000)
    hard_preemption_claimed: Literal[False]


class FinQAShadowCircuitContractV1(_StrictFrozenModel):
    consecutive_failure_threshold: int = Field(ge=1, le=20)
    cooldown_observation_count: int = Field(ge=1, le=10_000)
    single_half_open_probe: Literal[True]
    failure_outcomes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_failure_outcomes(self) -> FinQAShadowCircuitContractV1:
        if self.failure_outcomes != (
            "CHALLENGER_ERROR",
            "CHALLENGER_TIMEOUT",
            "INPUT_MISMATCH",
        ):
            raise ValueError("E12 circuit failure outcomes changed")
        return self


class FinQAShadowTelemetryContractV1(_StrictFrozenModel):
    allowed_observation_fields: tuple[str, ...]
    latency_buckets: tuple[str, ...]
    prohibited_content: tuple[str, ...]
    per_request_persistence_permitted: Literal[False]
    aggregate_counters_only: Literal[True]

    @model_validator(mode="after")
    def validate_telemetry_boundary(self) -> FinQAShadowTelemetryContractV1:
        if self.allowed_observation_fields != (
            "schema_version",
            "outcome",
            "role_count",
            "changed_role_count",
            "common_descriptor_count_at_4",
            "latency_bucket",
            "circuit_state",
        ):
            raise ValueError("E12 observation field boundary changed")
        if self.latency_buckets != (
            "LT_1_MS",
            "1_TO_LT_5_MS",
            "5_TO_LT_20_MS",
            "20_TO_LT_100_MS",
            "GE_100_MS",
            "NOT_RUN",
        ):
            raise ValueError("E12 latency buckets changed")
        required_prohibitions = {
            "question_text",
            "numeric_values",
            "descriptor_ids",
            "candidate_ids",
            "evidence_ids",
            "source_ids",
            "provenance",
            "ranked_scores",
            "input_fingerprints",
        }
        if set(self.prohibited_content) != required_prohibitions:
            raise ValueError("E12 telemetry prohibitions changed")
        return self


class FinQAShadowGatesV1(_StrictFrozenModel):
    require_default_off: Literal[True]
    require_primary_result_immutability: Literal[True]
    require_artifact_and_evidence_hash_verification: Literal[True]
    require_fail_closed_challenger_loading: Literal[True]
    require_error_and_timeout_isolation: Literal[True]
    require_circuit_breaker_recovery: Literal[True]
    require_privacy_bounded_telemetry: Literal[True]
    require_thread_safe_aggregate_metrics: Literal[True]
    require_zero_model_calls: Literal[True]
    require_frozen_test_untouched: Literal[True]


class FinQADescriptorShadowProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_descriptor_shadow_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E12_IMPLEMENTATION"]
    claim_label: Literal[
        "MECHANISM_ONLY_SHADOW_INTEGRATION_NOT_SERVING_ACTIVATION"
    ]
    source_e8_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e11_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e11_cv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e11_artifact_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e11_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e11_internal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e11_postmortem_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime: FinQAShadowRuntimeContractV1
    circuit_breaker: FinQAShadowCircuitContractV1
    telemetry: FinQAShadowTelemetryContractV1
    gates: FinQAShadowGatesV1
    serving_route_status: Literal["DISABLED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_descriptor_shadow_protocol_v1(
    path: Path,
) -> tuple[FinQADescriptorShadowProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQADescriptorShadowProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQADescriptorShadowProtocolV1",
    "SHADOW_PROTOCOL_VERSION",
    "load_descriptor_shadow_protocol_v1",
]
