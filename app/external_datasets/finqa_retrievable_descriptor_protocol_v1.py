from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinQARetrievableDescriptorBaselineV1(_StrictFrozenModel):
    descriptor_recall_at_4: Literal[0.8373983739837398]
    descriptor_complete_case_rate_at_4: Literal[0.8275862068965517]
    candidate_recall_at_4: Literal[0.7073170731707317]
    candidate_recall_at_8: Literal[0.7886178861788617]
    candidate_complete_case_rate_at_8: Literal[0.7586206896551724]
    conditional_candidate_retention_at_8: Literal[0.941747572815534]


class FinQARetrievableDescriptorBudgetsV1(_StrictFrozenModel):
    max_source_candidates: Literal[128] = 128
    max_catalog_descriptors: Literal[64] = 64
    max_local_context_hint_chars: Literal[128] = 128
    max_topic_hint_chars: Literal[160] = 160
    max_topic_contexts: Literal[32] = 32
    max_descriptor_prompt_chars: Literal[20000] = 20000
    max_selected_descriptors_per_role: Literal[4] = 4
    max_ranked_candidates_per_role: Literal[8] = 8


class FinQARetrievableDescriptorProgressGatesV1(_StrictFrozenModel):
    min_source_candidate_catalog_coverage: Literal[0.98] = 0.98
    min_oracle_candidate_recall_at_8: Literal[0.98] = 0.98
    min_descriptor_recall_at_4: Literal[0.88] = 0.88
    min_descriptor_complete_case_rate_at_4: Literal[0.86] = 0.86
    min_candidate_recall_at_4: Literal[0.75] = 0.75
    min_candidate_recall_at_8: Literal[0.84] = 0.84
    min_candidate_complete_case_rate_at_8: Literal[0.80] = 0.80
    min_conditional_candidate_retention_at_8: Literal[0.98] = 0.98
    min_candidate_edge_reduction_rate: Literal[0.70] = 0.70
    require_zero_model_calls: Literal[True] = True
    require_zero_forbidden_field_leakage: Literal[True] = True
    require_candidate_identity_preservation: Literal[True] = True
    require_input_order_invariance: Literal[True] = True
    require_guard_scan_before_projection: Literal[True] = True
    require_serving_route_disabled: Literal[True] = True


class FinQARetrievableDescriptorLongTermTargetsV1(_StrictFrozenModel):
    min_descriptor_recall_at_4: Literal[0.95] = 0.95
    min_candidate_recall_at_8: Literal[0.95] = 0.95
    min_candidate_complete_case_rate_at_8: Literal[0.90] = 0.90


class FinQARetrievableDescriptorProtocolV1(_StrictFrozenModel):
    schema_version: Literal["finqa_retrievable_descriptor_protocol_v1"]
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    status: Literal[
        "FROZEN_BEFORE_E8_CATALOG_AND_RERANKER_IMPLEMENTATION"
    ]
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    source_e7_catalog_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e7_catalog_upper_bound_v2_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    source_e7_retriever_v2_result_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    calibration_case_count: Literal[60] = 60
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline: FinQARetrievableDescriptorBaselineV1
    budgets: FinQARetrievableDescriptorBudgetsV1
    progress_gates: FinQARetrievableDescriptorProgressGatesV1
    long_term_targets: FinQARetrievableDescriptorLongTermTargetsV1
    decision_rule: Literal[
        "all_progress_and_safety_checks_must_pass_without_serving_activation"
    ]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_progress_is_below_long_term_target(
        self,
    ) -> FinQARetrievableDescriptorProtocolV1:
        if (
            self.progress_gates.min_descriptor_recall_at_4
            >= self.long_term_targets.min_descriptor_recall_at_4
            or self.progress_gates.min_candidate_recall_at_8
            >= self.long_term_targets.min_candidate_recall_at_8
            or self.progress_gates.min_candidate_complete_case_rate_at_8
            >= self.long_term_targets.min_candidate_complete_case_rate_at_8
        ):
            raise ValueError("E8 progress gates must not impersonate adoption gates")
        return self


def load_retrievable_descriptor_protocol_v1(
    path: Path,
) -> tuple[FinQARetrievableDescriptorProtocolV1, str]:
    content = path.resolve().read_bytes()
    protocol = FinQARetrievableDescriptorProtocolV1.model_validate_json(content)
    return protocol, hashlib.sha256(content).hexdigest()


__all__ = [
    "FinQARetrievableDescriptorProtocolV1",
    "load_retrievable_descriptor_protocol_v1",
]
