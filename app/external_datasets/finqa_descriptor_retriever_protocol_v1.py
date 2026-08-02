from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQADescriptorRetrieverGatesV1(_StrictFrozenModel):
    min_role_recall_at_4: float = Field(ge=0, le=1)
    min_role_recall_at_8: float = Field(ge=0, le=1)
    min_complete_typed_case_rate_at_8: float = Field(ge=0, le=1)
    min_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    min_schema_valid_rate: Literal[1.0] = 1.0
    max_mean_latency_ms: float = Field(gt=0)
    max_p95_latency_ms: float = Field(gt=0)
    max_model_requests_per_typed_case: Literal[0] = 0
    require_zero_prompt_leakage: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQADescriptorRetrieverProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_descriptor_retriever_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal[
        "FROZEN_BEFORE_FULL_DETERMINISTIC_RETRIEVER_CALIBRATION"
    ]
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    source_catalog_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_catalog_upper_bound_v2_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_failed_live_selector_v1_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retriever_version: Literal[
        "finqa_deterministic_descriptor_retriever_v1"
    ]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    gates: FinQADescriptorRetrieverGatesV1
    decision_rule: Literal["all_pre_registered_checks_must_pass"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_descriptor_retriever_protocol_v1(
    path: Path,
) -> tuple[FinQADescriptorRetrieverProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQADescriptorRetrieverProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQADescriptorRetrieverGatesV1",
    "FinQADescriptorRetrieverProtocolV1",
    "load_descriptor_retriever_protocol_v1",
]
