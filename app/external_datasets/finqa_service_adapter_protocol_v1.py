from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FINQA_SERVICE_ADAPTER_PROTOCOL_VERSION = "finqa_service_adapter_protocol_v1"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class FinQAServiceContextContractV1(_StrictFrozenModel):
    resolution_source: Literal["injected_online_context_resolver"]
    allowed_skeleton_origins: tuple[str, ...]
    allowed_catalog_origins: tuple[str, ...]
    primary_source: Literal["computed_e8_in_adapter"]
    primary_input_binding: Literal[
        "exact_question_skeleton_catalog_sha256"
    ]
    prohibited_input_fields: tuple[str, ...]
    unresolved_context_disposition: Literal["NOT_APPLICABLE"]
    resolver_retention: Literal["ephemeral_only"]

    @model_validator(mode="after")
    def validate_online_boundary(self) -> FinQAServiceContextContractV1:
        if self.allowed_skeleton_origins != (
            "ONLINE_RULES",
            "ONLINE_MODEL",
        ) or self.allowed_catalog_origins != (
            "RETRIEVED_ADMITTED_EVIDENCE",
        ):
            raise ValueError("E17 online origin boundary changed")
        if set(self.prohibited_input_fields) != {
            "answer",
            "exe_ans",
            "gold_inds",
            "gold_program",
            "program",
            "program_re",
            "target_labels",
        }:
            raise ValueError("E17 prohibited quality fields changed")
        return self


class FinQAServiceEligibilityContractV1(_StrictFrozenModel):
    eligible_reason: Literal["TYPED_CONTEXT_COMPLETE"]
    not_applicable_reasons: tuple[str, ...]
    eligibility_model_calls: Literal[0]
    adapter_model_calls: Literal[0]
    missing_context_starts_challenger: Literal[False]
    input_mismatch_starts_challenger: Literal[False]
    deadline_expired_starts_challenger: Literal[False]

    @model_validator(mode="after")
    def validate_reason_boundary(self) -> FinQAServiceEligibilityContractV1:
        if set(self.not_applicable_reasons) != {
            "NOT_FINANCIAL_NUMERIC",
            "MISSING_TYPED_SKELETON",
            "MISSING_SAFE_CATALOG",
            "POLICY_DENIED",
            "UNSUPPORTED_TYPED_CONTRACT",
        }:
            raise ValueError("E17 eligibility reason boundary changed")
        return self


class FinQAServiceOutcomeContractV1(_StrictFrozenModel):
    worker_match: Literal["MATCH"]
    worker_diverged: Literal["DIFFERENT"]
    ineligible: Literal["NOT_APPLICABLE"]
    worker_failures: Literal["SAFE_PROVIDER_ERROR"]
    primary_response_mutation_permitted: Literal[False]
    serving_promotion_permitted: Literal[False]


class FinQAServiceAdapterAuditProfileV1(_StrictFrozenModel):
    required_eligibility_reasons: tuple[str, ...]
    required_real_worker_observations: int = Field(ge=1, le=16)
    required_ineligible_worker_calls: Literal[0]
    required_model_calls: Literal[0]
    required_public_content_findings: Literal[0]
    require_exact_outcome_mapping: Literal[True]
    require_input_binding: Literal[True]
    require_deadline_fail_closed: Literal[True]
    require_worker_failure_isolation: Literal[True]

    @model_validator(mode="after")
    def validate_frozen_profile(self) -> FinQAServiceAdapterAuditProfileV1:
        if set(self.required_eligibility_reasons) != {
            "TYPED_CONTEXT_COMPLETE",
            "NOT_FINANCIAL_NUMERIC",
            "MISSING_TYPED_SKELETON",
            "MISSING_SAFE_CATALOG",
            "POLICY_DENIED",
            "UNSUPPORTED_TYPED_CONTRACT",
        }:
            raise ValueError("E17 frozen audit matrix changed")
        if self.required_real_worker_observations != 2:
            raise ValueError("E17 real-worker audit count changed")
        return self


class FinQAServiceAdapterPublicOutputV1(_StrictFrozenModel):
    per_request_rows_permitted: Literal[False]
    raw_errors_permitted: Literal[False]
    allowed_sections: tuple[str, ...]
    prohibited_content: tuple[str, ...]

    @model_validator(mode="after")
    def validate_public_boundary(self) -> FinQAServiceAdapterPublicOutputV1:
        if self.allowed_sections != (
            "source_binding",
            "eligibility_aggregates",
            "adapter_aggregates",
            "fault_injection",
            "gate_checks",
            "non_claims",
        ):
            raise ValueError("E17 public sections changed")
        if set(self.prohibited_content) != {
            "request_id",
            "question_text",
            "answer_text",
            "descriptor_ids",
            "candidate_ids",
            "evidence_ids",
            "source_ids",
            "principal",
            "tenant_id",
            "raw_error",
            "per_request_latency",
            "per_request_outcome",
        }:
            raise ValueError("E17 public-output prohibitions changed")
        return self


class FinQAServiceAdapterProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_service_adapter_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E17_IMPLEMENTATION"]
    claim_label: Literal[
        "ONLINE_TYPED_ADAPTER_MECHANISM_ONLY_NOT_PRODUCTION_TRAFFIC_OR_QUALITY"
    ]
    source_e16_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e16_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e13_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e13_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_contract: FinQAServiceContextContractV1
    eligibility_contract: FinQAServiceEligibilityContractV1
    outcome_contract: FinQAServiceOutcomeContractV1
    audit_profile: FinQAServiceAdapterAuditProfileV1
    public_output: FinQAServiceAdapterPublicOutputV1
    serving_champion: Literal["enterprise_agent_v2_primary_unchanged"]
    challenger_status: Literal["SHADOW_DEFAULT_OFF"]
    internal_cohort_status: Literal["CONSUMED_NOT_ACCESSED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_finqa_service_adapter_protocol_v1(
    path: Path,
) -> tuple[FinQAServiceAdapterProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAServiceAdapterProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FINQA_SERVICE_ADAPTER_PROTOCOL_VERSION",
    "FinQAServiceAdapterProtocolV1",
    "load_finqa_service_adapter_protocol_v1",
]
