from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FINQA_ADMITTED_CONTEXT_PROTOCOL_VERSION = (
    "finqa_admitted_context_protocol_v1"
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class AdmittedEvidenceInputContractV1(_StrictFrozenModel):
    required_input_type: Literal["AdmittedEvidenceChunk"]
    content_source: Literal["guard_admitted_context_text"]
    allowed_identity_fields: tuple[str, ...]
    secondary_retrieval_calls: Literal[0]
    max_evidence_units: int = Field(ge=1, le=64)
    max_total_evidence_chars: int = Field(ge=1, le=64_000)
    max_numeric_candidates: int = Field(ge=2, le=128)
    budget_overflow_disposition: Literal["UNSUPPORTED_TYPED_CONTRACT"]
    guard_rescan_failure_disposition: Literal["POLICY_DENIED"]

    @model_validator(mode="after")
    def validate_identity_boundary(self) -> AdmittedEvidenceInputContractV1:
        if self.allowed_identity_fields != (
            "doc_id",
            "chunk_id",
            "source_path",
            "section_path",
        ):
            raise ValueError("E18 admitted-evidence identity boundary changed")
        return self


class OnlineTypedPlanningContractV1(_StrictFrozenModel):
    skeleton_origin: Literal["ONLINE_RULES"]
    catalog_origin: Literal["RETRIEVED_ADMITTED_EVIDENCE"]
    supported_operation_families: tuple[str, ...]
    planner_model_calls: Literal[0]
    prohibited_inputs: tuple[str, ...]
    unsupported_disposition: Literal["MISSING_TYPED_SKELETON"]

    @model_validator(mode="after")
    def validate_planning_boundary(self) -> OnlineTypedPlanningContractV1:
        if self.supported_operation_families != (
            "average",
            "exact_add",
            "exact_divide",
            "exact_multiply",
            "exact_subtract",
            "percent_change",
            "ratio",
        ):
            raise ValueError("E18 online-rules capability boundary changed")
        if set(self.prohibited_inputs) != {
            "answer",
            "exe_ans",
            "gold_inds",
            "gold_program",
            "program",
            "program_re",
            "target_labels",
        }:
            raise ValueError("E18 prohibited planning inputs changed")
        return self


class EphemeralAdmissionContractV1(_StrictFrozenModel):
    registration_order: Literal["REGISTER_BEFORE_DARK_OFFER"]
    retained_offer_outcome: Literal["ADMITTED"]
    discard_offer_outcomes: tuple[str, ...]
    resolver_semantics: Literal["BOUNDED_TTL_CONSUME_ONCE"]
    duplicate_request_policy: Literal["REJECT_WITHOUT_OVERWRITE"]
    shutdown_order: Literal[
        "DARK_SERVICE_THEN_ADAPTER_THEN_RESOLVER"
    ]

    @model_validator(mode="after")
    def validate_cleanup_matrix(self) -> EphemeralAdmissionContractV1:
        if set(self.discard_offer_outcomes) != {
            "BACKPRESSURE",
            "CLOSED",
            "DISABLED",
            "SAMPLE_SKIPPED",
            "UNAVAILABLE",
        }:
            raise ValueError("E18 resolver cleanup matrix changed")
        return self


class PrimaryIsolationContractV1(_StrictFrozenModel):
    observer_position: Literal["AFTER_PRIMARY_RESPONSE_BUILD"]
    same_response_object_required: Literal[True]
    observer_exceptions_propagate: Literal[False]
    response_trace_mutation_permitted: Literal[False]
    serving_promotion_permitted: Literal[False]
    default_mode: Literal["OFF"]


class AdmittedContextAuditProfileV1(_StrictFrozenModel):
    required_rule_families: tuple[str, ...]
    required_preparation_reasons: tuple[str, ...]
    required_non_admitted_exposures: Literal[0]
    required_secondary_retrieval_calls: Literal[0]
    required_model_calls: Literal[0]
    required_primary_response_mismatches: Literal[0]
    required_residual_contexts: Literal[0]
    max_preparation_p95_ms: float = Field(gt=0, le=100)
    required_public_content_findings: Literal[0]

    @model_validator(mode="after")
    def validate_rule_coverage(self) -> AdmittedContextAuditProfileV1:
        if self.required_rule_families != (
            "average",
            "exact_add",
            "exact_divide",
            "exact_multiply",
            "exact_subtract",
            "percent_change",
            "ratio",
        ):
            raise ValueError("E18 required rule-family coverage changed")
        if set(self.required_preparation_reasons) != {
            "TYPED_CONTEXT_COMPLETE",
            "NOT_FINANCIAL_NUMERIC",
            "MISSING_TYPED_SKELETON",
            "MISSING_SAFE_CATALOG",
            "POLICY_DENIED",
            "UNSUPPORTED_TYPED_CONTRACT",
        }:
            raise ValueError("E18 required preparation-reason coverage changed")
        return self


class FinQAAdmittedContextProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_admitted_context_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_E18_IMPLEMENTATION"]
    claim_label: Literal[
        "ADMITTED_EVIDENCE_TO_TYPED_CONTEXT_MECHANISM_ONLY_NOT_SERVING_TRAFFIC_OR_QUALITY"
    ]
    source_e17_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e17_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_guard_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_contract: AdmittedEvidenceInputContractV1
    planning_contract: OnlineTypedPlanningContractV1
    admission_contract: EphemeralAdmissionContractV1
    primary_isolation: PrimaryIsolationContractV1
    audit_profile: AdmittedContextAuditProfileV1
    standard_fastapi_route_status: Literal["DISABLED_PENDING_VERSIONED_WIRING"]
    challenger_status: Literal["SHADOW_DEFAULT_OFF"]
    internal_cohort_status: Literal["CONSUMED_NOT_ACCESSED"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_finqa_admitted_context_protocol_v1(
    path: Path,
) -> tuple[FinQAAdmittedContextProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAAdmittedContextProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FINQA_ADMITTED_CONTEXT_PROTOCOL_VERSION",
    "FinQAAdmittedContextProtocolV1",
    "load_finqa_admitted_context_protocol_v1",
]
