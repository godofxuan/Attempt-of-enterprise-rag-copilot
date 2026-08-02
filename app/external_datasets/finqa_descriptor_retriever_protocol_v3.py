from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQAHybridDescriptorRetrieverGatesV3(_StrictFrozenModel):
    min_role_recall_at_4: float = Field(ge=0, le=1)
    min_role_recall_at_8: float = Field(ge=0, le=1)
    min_complete_typed_case_rate_at_8: float = Field(ge=0, le=1)
    min_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    min_schema_valid_rate: Literal[1.0] = 1.0
    max_mean_latency_ms: float = Field(gt=0)
    max_p95_latency_ms: float = Field(gt=0)
    max_embedding_requests_per_typed_case: Literal[1] = 1
    max_generation_requests_per_typed_case: Literal[0] = 0
    require_pinned_model_identity: Literal[True] = True
    require_safe_descriptor_only_embedding_payload: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQAHybridDescriptorRetrieverProtocolV3(_StrictFrozenModel):
    schema_version: Literal["finqa_descriptor_retriever_protocol_v3"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_FULL_LOCAL_EMBEDDING_CALIBRATION"]
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    source_catalog_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_catalog_upper_bound_v2_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_retriever_v2_result_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retriever_version: Literal["finqa_hybrid_descriptor_retriever_v3"]
    embedding_model: Literal["bge-m3"]
    embedding_model_sha256: Literal[
        "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
    ]
    embedding_dimension: Literal[1024] = 1024
    rrf_k: Literal[60.0] = 60.0
    dense_weight: Literal[0.8] = 0.8
    lexical_weight: Literal[0.2] = 0.2
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    gates: FinQAHybridDescriptorRetrieverGatesV3
    decision_rule: Literal["all_pre_registered_checks_must_pass"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_descriptor_retriever_protocol_v3(
    path: Path,
) -> tuple[FinQAHybridDescriptorRetrieverProtocolV3, str]:
    content = path.resolve().read_bytes()
    protocol = FinQAHybridDescriptorRetrieverProtocolV3.model_validate_json(
        content
    )
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQAHybridDescriptorRetrieverGatesV3",
    "FinQAHybridDescriptorRetrieverProtocolV3",
    "load_descriptor_retriever_protocol_v3",
]
