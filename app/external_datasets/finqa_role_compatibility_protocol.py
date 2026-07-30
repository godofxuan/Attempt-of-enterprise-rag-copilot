from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_SCHEMA_VERSION = "finqa_role_compatibility_protocol_v1"
CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class FinQARoleCompatibilityGates(_StrictFrozenModel):
    min_hard_filter_gold_role_retention: float = Field(ge=0, le=1)
    min_gold_role_recall_at_4: float = Field(ge=0, le=1)
    min_gold_role_recall_at_8: float = Field(ge=0, le=1)
    min_complete_case_rate_at_8: float = Field(ge=0, le=1)
    min_role_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    max_mean_hard_compatible_candidates_per_role: float = Field(
        ge=1,
        le=24,
    )
    max_mean_candidates_per_role: float = Field(ge=1, le=24)
    max_p95_candidates_per_role: int = Field(ge=1, le=24)
    max_empty_role_allowlist_rate: float = Field(ge=0, le=1)
    require_zero_known_period_conflicts: Literal[True] = True
    require_admitted_operand_only: Literal[True] = True
    require_global_shortlist_subset: Literal[True] = True
    require_no_gold_runtime_input: Literal[True] = True
    require_deterministic_output: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_zero_silent_global_fallbacks: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_role_exact_parser_enforcement: Literal[True] = True


class FinQARoleCompatibilityProtocol(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_GATE_E6_IMPLEMENTATION"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e5_run_id: Literal[
        "finqa-semantic-planning-calibration-v1"
    ]
    source_gate_e5_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e5_public_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e5_private_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_gate_e5_private_details_sha256: str = Field(
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
    compatibility_version: Literal["finqa_role_candidate_compatibility_v1"]
    diagnostic_skeleton_source: Literal["gold_program_offline_diagnostic_only"]
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
    model_call_count: Literal[0] = 0
    max_global_candidates: Literal[24] = 24
    max_candidates_per_role: Literal[8] = 8
    diagnostic_cutoffs: tuple[Literal[4, 8], Literal[4, 8]]
    gold_match_method: Literal[
        "provenance_bound_normalized_or_surface_value_v1"
    ]
    gates: FinQARoleCompatibilityGates
    input_gate_rule: Literal["all_pre_registered_checks_must_pass"]
    live_model_gate_rule: Literal[
        "no_gate_e6_model_run_unless_input_gate_passes"
    ]
    immutable_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_role_compatibility_protocol(
    path: Path,
) -> tuple[FinQARoleCompatibilityProtocol, str]:
    content = path.resolve().read_bytes()
    protocol = FinQARoleCompatibilityProtocol.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "CLAIM_LABEL",
    "PROTOCOL_SCHEMA_VERSION",
    "FinQARoleCompatibilityGates",
    "FinQARoleCompatibilityProtocol",
    "load_role_compatibility_protocol",
]
