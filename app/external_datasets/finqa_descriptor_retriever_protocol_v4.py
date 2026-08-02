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


class FinQADescriptorRetrieverProtocolV4(_StrictFrozenModel):
    schema_version: Literal["finqa_descriptor_retriever_protocol_v4"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal["FROZEN_BEFORE_FULL_TYPED_STRUCTURAL_CALIBRATION"]
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    source_catalog_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_catalog_upper_bound_v2_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_retriever_v2_result_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_failed_retriever_v3_result_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retriever_version: Literal["finqa_structured_descriptor_retriever_v4"]
    structural_bonus: Literal[120.0] = 120.0
    interventions: tuple[
        Literal[
            "percent_change_balance_row_prior",
            "multi_operand_descriptor_cardinality_prior",
        ],
        ...,
    ] = Field(min_length=2, max_length=2)
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    gates: FinQADescriptorRetrieverGatesV1
    decision_rule: Literal["all_pre_registered_checks_must_pass"]
    non_claims: tuple[str, ...] = Field(min_length=1)


def load_descriptor_retriever_protocol_v4(
    path: Path,
) -> tuple[FinQADescriptorRetrieverProtocolV4, str]:
    content = path.resolve().read_bytes()
    protocol = FinQADescriptorRetrieverProtocolV4.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQADescriptorRetrieverProtocolV4",
    "load_descriptor_retriever_protocol_v4",
]
