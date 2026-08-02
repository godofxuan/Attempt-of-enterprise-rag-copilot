from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_SCHEMA_VERSION = "finqa_role_compatibility_protocol_v3"
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class FinQARoleCompatibilityGatesV3(_StrictFrozenModel):
    min_runtime_capability_route_accuracy: float = Field(ge=0, le=1)
    min_typed_eligible_case_rate: float = Field(ge=0, le=1)
    min_evidence_role_source_recall: float = Field(ge=0, le=1)
    min_controlled_constant_recall: Literal[1.0] = 1.0
    min_evidence_role_recall_at_4: float = Field(ge=0, le=1)
    min_evidence_role_recall_at_8: float = Field(ge=0, le=1)
    min_complete_typed_case_rate_at_8: float = Field(ge=0, le=1)
    min_role_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    min_role_query_schema_valid_rate: Literal[1.0] = 1.0
    max_mean_exposed_candidates_per_role: float = Field(ge=1, le=8)
    max_p95_exposed_candidates_per_role: int = Field(ge=1, le=8)
    max_empty_role_allowlist_rate: Literal[0.0] = 0.0
    require_zero_known_period_conflicts: Literal[True] = True
    require_admitted_operand_only: Literal[True] = True
    require_no_gold_runtime_input: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_zero_silent_fallback_expansion: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_role_exact_parser_enforcement: Literal[True] = True
    require_controlled_constant_enum_enforcement: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQARoleCompatibilityProtocolV3(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_protocol_v3"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_GATE_E6_V3_IMPLEMENTATION"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e6_v2_run_id: Literal[
        "finqa-role-compatibility-v2-audit-v4"
    ]
    source_gate_e6_v2_protocol_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e6_v2_public_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e6_v2_private_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e6_v2_private_details_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    development_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    internal_validation_case_count: Literal[40] = 40
    internal_validation_case_ids_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    compatibility_version: Literal["finqa_role_candidate_compatibility_v3"]
    semantic_program_version: Literal["finqa_semantic_program_v3"]
    runtime_source_pool: Literal[
        "guard_admitted_operand_candidates_before_global_shortlist"
    ]
    role_query_source: Literal["planner_generated_from_question_only"]
    oracle_role_query_source: Literal[
        "gold_evidence_descriptor_offline_upper_bound_only"
    ]
    max_role_query_chars: Literal[160] = 160
    allow_explicit_role_period: Literal[True] = True
    max_source_candidates: Literal[128] = 128
    max_evidence_candidates_per_role: Literal[8] = 8
    max_unique_exposed_candidate_ids: Literal[32] = 32
    max_program_steps: Literal[5] = 5
    max_semantic_roles: Literal[8] = 8
    gates: FinQARoleCompatibilityGatesV3
    input_gate_rule: Literal["all_pre_registered_checks_must_pass"]
    live_model_gate_rule: Literal[
        "no_gate_e6_v3_model_run_unless_input_gate_passes"
    ]
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_role_compatibility_protocol_v3(
    path: Path,
) -> tuple[FinQARoleCompatibilityProtocolV3, str]:
    content = path.resolve().read_bytes()
    protocol = FinQARoleCompatibilityProtocolV3.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQARoleCompatibilityGatesV3",
    "FinQARoleCompatibilityProtocolV3",
    "load_role_compatibility_protocol_v3",
]
