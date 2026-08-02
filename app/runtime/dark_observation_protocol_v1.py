from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DARK_OBSERVATION_PROTOCOL_VERSION = "dark_observation_service_protocol_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class DarkObservationRuntimeContractV1(_StrictFrozenModel):
    serving_route: Literal["POST /agent/v2/chat"]
    trigger_point: Literal["after_primary_response_is_fully_constructed"]
    default_mode: Literal["OFF"]
    enabled_mode: Literal["LOCAL_TEST_ONLY"]
    sampling_algorithm: Literal["process_local_hmac_sha256_request_id"]
    admission_algorithm: Literal["bounded_queue_put_nowait"]
    worker_lifetime: Literal["service_lifespan_owned_daemon_workers"]
    observation_deadline_origin: Literal["admission_monotonic_time"]
    primary_mutation_permitted: Literal[False]
    primary_wait_for_shadow_permitted: Literal[False]
    startup_dependency_permitted: Literal[False]
    readiness_dependency_permitted: Literal[False]


class DarkObservationDataBoundaryV1(_StrictFrozenModel):
    ephemeral_provider_fields: tuple[str, ...]
    prohibited_provider_fields: tuple[str, ...]
    persistent_request_rows_permitted: Literal[False]
    aggregate_metrics_only: Literal[True]
    raw_provider_errors_permitted: Literal[False]

    @model_validator(mode="after")
    def validate_minimal_data_boundary(self) -> DarkObservationDataBoundaryV1:
        if self.ephemeral_provider_fields != (
            "request_id",
            "question",
            "primary_mode",
            "primary_stop_reason",
        ):
            raise ValueError("E16 ephemeral provider fields changed")
        if set(self.prohibited_provider_fields) != {
            "principal",
            "subject",
            "tenant_id",
            "groups",
            "roles",
            "answer_text",
            "claims",
            "citations",
            "sources",
            "trace",
            "feedback_receipt",
        }:
            raise ValueError("E16 prohibited provider fields changed")
        return self


class DarkObservationAuditProfileV1(_StrictFrozenModel):
    request_count: int = Field(ge=1, le=1_000)
    worker_count: int = Field(ge=1, le=8)
    queue_capacity: int = Field(ge=1, le=256)
    sample_basis_points: int = Field(ge=1, le=10_000)
    observation_deadline_ms: int = Field(ge=1, le=60_000)
    shutdown_grace_ms: int = Field(ge=1, le=60_000)
    max_offer_latency_p95_ms: float = Field(gt=0, le=100)
    required_default_off_provider_calls: Literal[0]
    required_primary_response_mismatches: Literal[0]
    required_public_content_findings: Literal[0]
    require_backpressure_isolation: Literal[True]
    require_provider_error_isolation: Literal[True]
    require_deadline_isolation: Literal[True]
    require_closed_admission_rejection: Literal[True]
    require_zero_residual_controlled_workers: Literal[True]

    @model_validator(mode="after")
    def validate_frozen_audit_profile(self) -> DarkObservationAuditProfileV1:
        expected = (24, 2, 4, 10_000, 100, 2_000, 10.0)
        actual = (
            self.request_count,
            self.worker_count,
            self.queue_capacity,
            self.sample_basis_points,
            self.observation_deadline_ms,
            self.shutdown_grace_ms,
            self.max_offer_latency_p95_ms,
        )
        if actual != expected:
            raise ValueError("E16 frozen audit profile changed")
        return self


class DarkObservationPublicOutputV1(_StrictFrozenModel):
    allowed_sections: tuple[str, ...]
    prohibited_content: tuple[str, ...]

    @model_validator(mode="after")
    def validate_public_output(self) -> DarkObservationPublicOutputV1:
        if self.allowed_sections != (
            "source_binding",
            "runtime_profile",
            "aggregate_metrics",
            "failure_injection",
            "gate_checks",
            "non_claims",
        ):
            raise ValueError("E16 public sections changed")
        if set(self.prohibited_content) != {
            "request_id",
            "question_text",
            "answer_text",
            "principal",
            "subject",
            "tenant_id",
            "groups",
            "roles",
            "claims",
            "citations",
            "sources",
            "trace",
            "feedback_receipt",
            "raw_provider_error",
            "per_request_latency",
            "per_request_outcome",
        }:
            raise ValueError("E16 public-output prohibitions changed")
        return self


class DarkObservationServiceProtocolV1(_StrictFrozenModel):
    schema_version: Literal["dark_observation_service_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E16_IMPLEMENTATION"]
    claim_label: Literal[
        "MECHANISM_ONLY_DEFAULT_OFF_SERVICE_DARK_INTEGRATION_NOT_PRODUCTION_TRAFFIC"
    ]
    source_e15_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e15_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_contract: DarkObservationRuntimeContractV1
    data_boundary: DarkObservationDataBoundaryV1
    audit_profile: DarkObservationAuditProfileV1
    public_output: DarkObservationPublicOutputV1
    serving_champion: Literal["enterprise_agent_v2_primary_unchanged"]
    finqa_adapter_status: Literal["NOT_IMPLEMENTED_CONTRACT_MISMATCH_RECORDED"]
    challenger_status: Literal["DEFAULT_OFF"]
    internal_cohort_status: Literal["CONSUMED_NOT_ACCESSED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_dark_observation_service_protocol_v1(
    path: Path,
) -> tuple[DarkObservationServiceProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = DarkObservationServiceProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "DARK_OBSERVATION_PROTOCOL_VERSION",
    "DarkObservationServiceProtocolV1",
    "load_dark_observation_service_protocol_v1",
]
