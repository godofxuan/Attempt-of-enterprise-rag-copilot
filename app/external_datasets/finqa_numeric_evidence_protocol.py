from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROTOCOL_SCHEMA_VERSION = "finqa_numeric_evidence_protocol_v1"
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class NumericEvidenceBaseline(_StrictModel):
    case_count: Literal[60] = 60
    gold_operand_count: int = Field(ge=1)
    selected_normalized_operand_count: int = Field(ge=0)
    selected_surface_view_operand_count: int = Field(ge=0)
    controlled_constant_operand_count: int = Field(ge=0)
    retrieval_missing_operand_count: int = Field(ge=0)
    extraction_unresolved_operand_count: int = Field(ge=0)
    runtime_input_complete_case_count: int = Field(ge=0, le=60)
    gold_evidence_complete_case_count: int = Field(ge=0, le=60)
    normalized_only_complete_case_count: int = Field(ge=0, le=60)

    @model_validator(mode="after")
    def validate_operand_accounting(self) -> NumericEvidenceBaseline:
        accounted = (
            self.selected_normalized_operand_count
            + self.selected_surface_view_operand_count
            + self.controlled_constant_operand_count
            + self.retrieval_missing_operand_count
            + self.extraction_unresolved_operand_count
        )
        if accounted != self.gold_operand_count:
            raise ValueError("numeric-evidence baseline operands do not reconcile")
        return self


class NumericEvidenceBudgets(_StrictModel):
    max_added_evidence_units: int = Field(ge=0, le=64)
    max_total_evidence_units: int = Field(ge=1, le=64)
    max_total_evidence_chars: int = Field(ge=1, le=64_000)
    max_candidates_before_shortlist: int = Field(ge=1, le=256)
    max_candidates_after_shortlist: int = Field(ge=1, le=128)
    text_neighbor_radius: int = Field(ge=0, le=5)
    expand_bounded_table_parent: bool

    @model_validator(mode="after")
    def validate_candidate_budgets(self) -> NumericEvidenceBudgets:
        if (
            self.max_candidates_after_shortlist
            > self.max_candidates_before_shortlist
        ):
            raise ValueError("candidate shortlist budget exceeds source budget")
        return self


class NumericEvidenceGates(_StrictModel):
    min_runtime_input_complete_rate: float = Field(ge=0, le=1)
    min_gold_evidence_complete_rate: Literal[1.0] = 1.0
    min_retrieval_missing_operand_recovery_rate: float = Field(ge=0, le=1)
    max_p95_total_evidence_units: int = Field(ge=1, le=64)
    max_p95_total_evidence_chars: int = Field(ge=1, le=64_000)
    max_p95_candidates_before_shortlist: int = Field(ge=1, le=256)
    require_v1_byte_stability: Literal[True] = True
    require_added_evidence_guard_scan: Literal[True] = True
    require_provenance_bound_dual_value_view: Literal[True] = True
    require_no_gold_runtime_input: Literal[True] = True


class FinQANumericEvidenceProtocol(_StrictModel):
    schema_version: Literal[
        "finqa_numeric_evidence_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    status: Literal[
        "FROZEN_AFTER_DISCLOSED_E2_DIAGNOSIS_BEFORE_V2_IMPLEMENTATION"
    ]
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e2_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e2_public_evidence_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    internal_validation_case_count: Literal[40] = 40
    internal_validation_case_ids_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    baseline_method: Literal[
        "provenance_bound_normalized_surface_constant_multiset_v1"
    ]
    baseline: NumericEvidenceBaseline
    budgets: NumericEvidenceBudgets
    gates: NumericEvidenceGates
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_numeric_evidence_protocol(
    path: Path,
) -> tuple[FinQANumericEvidenceProtocol, str]:
    content = Path(path).read_bytes()
    protocol = FinQANumericEvidenceProtocol.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQANumericEvidenceProtocol",
    "NumericEvidenceBaseline",
    "NumericEvidenceBudgets",
    "NumericEvidenceGates",
    "load_numeric_evidence_protocol",
]
