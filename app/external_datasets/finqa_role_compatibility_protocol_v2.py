from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_SCHEMA_VERSION = "finqa_role_compatibility_protocol_v2"
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class FinQARoleCompatibilityGatesV2(_StrictFrozenModel):
    min_runtime_capability_route_accuracy: float = Field(ge=0, le=1)
    min_typed_eligible_case_rate: float = Field(ge=0, le=1)
    min_evidence_role_source_recall: float = Field(ge=0, le=1)
    min_controlled_constant_recall: Literal[1.0] = 1.0
    min_evidence_role_recall_at_4: float = Field(ge=0, le=1)
    min_evidence_role_recall_at_8: float = Field(ge=0, le=1)
    min_complete_typed_case_rate_at_8: float = Field(ge=0, le=1)
    min_role_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
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


class FinQARoleCompatibilityProtocolV2(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_protocol_v2"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_GATE_E6_V2_IMPLEMENTATION"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e6_v1_run_id: Literal[
        "finqa-role-compatibility-audit-v3"
    ]
    source_gate_e6_v1_protocol_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e6_v1_public_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e6_v1_private_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e6_v1_private_details_sha256: str = Field(
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
    compatibility_version: Literal["finqa_role_candidate_compatibility_v2"]
    semantic_program_version: Literal["finqa_semantic_program_v2"]
    controlled_constant_registry: tuple[
        Literal[
            "const_1",
            "const_2",
            "const_3",
            "const_4",
            "const_5",
            "const_10",
            "const_100",
            "const_1000",
        ],
        ...,
    ] = Field(min_length=8, max_length=8)
    runtime_source_pool: Literal[
        "guard_admitted_operand_candidates_before_global_shortlist"
    ]
    runtime_inputs: tuple[
        Literal[
            "question",
            "question_intent",
            "semantic_skeleton",
            "admitted_numeric_candidates",
            "admitted_evidence_context",
        ],
        ...,
    ] = Field(min_length=5, max_length=5)
    capability_routes: tuple[
        Literal[
            "TYPED_NUMERIC",
            "B0_BOOLEAN_COMPARISON_FALLBACK",
            "B0_SYMBOLIC_TABLE_AGGREGATION_FALLBACK",
        ],
        ...,
    ] = Field(min_length=3, max_length=3)
    model_call_count: Literal[0] = 0
    max_source_candidates: Literal[128] = 128
    max_evidence_candidates_per_role: Literal[8] = 8
    max_unique_exposed_candidate_ids: Literal[32] = 32
    max_program_steps: Literal[5] = 5
    max_semantic_roles: Literal[8] = 8
    diagnostic_skeleton_source: Literal[
        "gold_program_offline_diagnostic_only"
    ]
    gates: FinQARoleCompatibilityGatesV2
    input_gate_rule: Literal["all_pre_registered_checks_must_pass"]
    live_model_gate_rule: Literal[
        "no_gate_e6_v2_model_run_unless_input_gate_passes"
    ]
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_role_compatibility_protocol_v2(
    path: Path,
) -> tuple[FinQARoleCompatibilityProtocolV2, str]:
    content = path.resolve().read_bytes()
    protocol = FinQARoleCompatibilityProtocolV2.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQARoleCompatibilityGatesV2",
    "FinQARoleCompatibilityProtocolV2",
    "load_role_compatibility_protocol_v2",
]
