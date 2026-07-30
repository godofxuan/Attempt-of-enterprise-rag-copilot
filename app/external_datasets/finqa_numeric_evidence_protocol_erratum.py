from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FinQANumericEvidenceProtocolErratum(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_version: Literal[
        "finqa_numeric_evidence_protocol_erratum_v1"
    ]
    erratum_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_V2_CALIBRATION_AUDIT"]
    source_protocol_id: Literal["finqa-numeric-evidence-gate-e3-v1"]
    source_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    affected_field: Literal["baseline.runtime_input_complete_case_count"]
    original_value: Literal[49]
    original_semantics: Literal["selected_evidence_pre_shortlist"]
    post_shortlist_complete_case_count: Literal[48]
    complete_cases_lost_by_shortlist: Literal[1]
    shortlist_error_count: Literal[0]
    corrected_gate_semantics: Literal[
        "min_runtime_input_complete_rate_applies_post_shortlist"
    ]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_shortlist_accounting(
        self,
    ) -> FinQANumericEvidenceProtocolErratum:
        if (
            self.original_value
            - self.post_shortlist_complete_case_count
            != self.complete_cases_lost_by_shortlist
        ):
            raise ValueError("numeric evidence erratum does not reconcile")
        return self


__all__ = ["FinQANumericEvidenceProtocolErratum"]
