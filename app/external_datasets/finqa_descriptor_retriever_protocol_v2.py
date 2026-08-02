from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.external_datasets.finqa_descriptor_retriever_protocol_v1 import (
    FinQADescriptorRetrieverGatesV1,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQADescriptorRetrieverProtocolV2(_StrictFrozenModel):
    schema_version: Literal["finqa_descriptor_retriever_protocol_v2"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal[
        "FROZEN_BEFORE_FULL_NORMALIZED_LEXICAL_CALIBRATION"
    ]
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    source_catalog_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_catalog_upper_bound_v2_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_retriever_v1_result_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retriever_version: Literal[
        "finqa_deterministic_descriptor_retriever_v2"
    ]
    interventions: tuple[
        Literal[
            "financial_abbreviation_and_compound_token_normalization",
            "extended_part_total_role_anchor",
            "temporal_row_role_hints",
        ],
        ...,
    ] = Field(min_length=3, max_length=3)
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    gates: FinQADescriptorRetrieverGatesV1
    decision_rule: Literal["all_pre_registered_checks_must_pass"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_descriptor_retriever_protocol_v2(
    path: Path,
) -> tuple[FinQADescriptorRetrieverProtocolV2, str]:
    content = path.resolve().read_bytes()
    protocol = FinQADescriptorRetrieverProtocolV2.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQADescriptorRetrieverProtocolV2",
    "load_descriptor_retriever_protocol_v2",
]
