from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_SCHEMA_VERSION = "finqa_descriptor_catalog_protocol_v1"
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class FinQADescriptorCatalogGatesV1(_StrictFrozenModel):
    min_source_candidate_catalog_coverage: float = Field(ge=0, le=1)
    min_oracle_role_recall_at_4: float = Field(ge=0, le=1)
    min_oracle_role_recall_at_8: float = Field(ge=0, le=1)
    min_oracle_complete_typed_case_rate_at_8: float = Field(ge=0, le=1)
    min_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    min_descriptor_schema_valid_rate: Literal[1.0] = 1.0
    max_empty_catalog_rate: Literal[0.0] = 0.0
    max_quarantined_descriptor_candidate_rate: float = Field(ge=0, le=1)
    require_zero_value_leakage: Literal[True] = True
    require_zero_candidate_id_leakage: Literal[True] = True
    require_zero_evidence_id_leakage: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_guard_scan_before_prompt: Literal[True] = True
    require_exact_descriptor_enum_output: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQADescriptorCatalogProtocolV1(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_descriptor_catalog_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_GATE_E7_IMPLEMENTATION"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e6_v3_protocol_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e6_v3_upper_bound_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_deterministic_v2_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_local_llm_v1_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    internal_validation_case_count: Literal[40] = 40
    internal_validation_case_ids_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    catalog_version: Literal["finqa_safe_descriptor_catalog_v1"]
    selection_version: Literal["finqa_descriptor_selection_v1"]
    max_source_candidates: Literal[128] = 128
    max_catalog_descriptors: Literal[64] = 64
    max_descriptor_field_chars: Literal[96] = 96
    max_descriptor_prompt_chars: Literal[12000] = 12000
    max_descriptor_refs_per_role: Literal[4] = 4
    max_candidates_per_role: Literal[8] = 8
    descriptor_fields: tuple[
        Literal[
            "metric",
            "entity",
            "row_header",
            "column_header",
            "period",
            "source_kind",
        ],
        ...,
    ]
    forbidden_prompt_fields: tuple[str, ...] = Field(min_length=1)
    oracle_gate_rule: Literal[
        "no_live_descriptor_selection_unless_oracle_catalog_gate_passes"
    ]
    live_model_gate_rule: Literal[
        "no_serving_activation_without_paired_validation_and_answer_gate"
    ]
    gates: FinQADescriptorCatalogGatesV1
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_descriptor_catalog_protocol_v1(
    path: Path,
) -> tuple[FinQADescriptorCatalogProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQADescriptorCatalogProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQADescriptorCatalogGatesV1",
    "FinQADescriptorCatalogProtocolV1",
    "load_descriptor_catalog_protocol_v1",
]
