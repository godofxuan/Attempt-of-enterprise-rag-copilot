from __future__ import annotations

from typing import Literal

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


FINQA_SERVICE_ASSEMBLY_VERSION = "finqa-service-assembly-v2"
FINQA_SERVICE_PROTOCOL_ID = "enterprise-rag-e19-versioned-service-v2"


class FinQAServiceWiringProtocolV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["finqa_service_wiring_protocol_v2"] = (
        "finqa_service_wiring_protocol_v2"
    )
    protocol_id: Literal["enterprise-rag-e19-versioned-service-v2"] = (
        FINQA_SERVICE_PROTOCOL_ID
    )
    assembly_version: Literal["finqa-service-assembly-v2"] = (
        FINQA_SERVICE_ASSEMBLY_VERSION
    )
    source_e18_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_e18_public_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    serving_route: Literal["POST /agent/v2/chat"] = "POST /agent/v2/chat"
    production_default_mode: Literal["OFF"] = "OFF"
    production_default_sample_basis_points: Literal[0] = 0
    enabled_mode: Literal["LOCAL_TEST_ONLY"] = "LOCAL_TEST_ONLY"
    evidence_origin: Literal["CONTROLLER_ADMITTED_EVIDENCE"] = (
        "CONTROLLER_ADMITTED_EVIDENCE"
    )
    observation_position: Literal["AFTER_PRIMARY_BUILD"] = "AFTER_PRIMARY_BUILD"
    legacy_generic_offer_calls: Literal[0] = 0
    secondary_retrieval_calls: Literal[0] = 0
    planner_model_calls: Literal[0] = 0
    primary_response_mutation_allowed: Literal[False] = False
    feedback_receipt_mutation_allowed: Literal[False] = False
    raw_content_in_metrics_allowed: Literal[False] = False
    required_paired_api_requests: int = Field(default=8, ge=1, le=100)
    required_response_mismatches: Literal[0] = 0
    required_receipt_mismatches: Literal[0] = 0
    required_public_content_findings: Literal[0] = 0
    startup_failure_policy: Literal["FAIL_LOCAL_TEST_ONLY_STARTUP"] = (
        "FAIL_LOCAL_TEST_ONLY_STARTUP"
    )
    shutdown_order: tuple[
        Literal["FINQA_COORDINATOR"], Literal["BASE_RESOURCES"]
    ] = ("FINQA_COORDINATOR", "BASE_RESOURCES")
    non_claims: tuple[str, ...] = (
        "not answer accuracy, retrieval quality, or serving promotion evidence",
        "not production traffic, capacity, availability, latency SLO, or autoscaling",
        "not arbitrary financial-program coverage or E11 champion promotion",
        "not durable distributed queueing or hard cancellation of arbitrary code",
    )


def load_finqa_service_wiring_protocol_v2(
    path: Path,
) -> tuple[FinQAServiceWiringProtocolV2, str]:
    content = path.resolve().read_bytes()
    return (
        FinQAServiceWiringProtocolV2.model_validate_json(content),
        hashlib.sha256(content).hexdigest(),
    )


__all__ = [
    "FINQA_SERVICE_ASSEMBLY_VERSION",
    "FINQA_SERVICE_PROTOCOL_ID",
    "FinQAServiceWiringProtocolV2",
    "load_finqa_service_wiring_protocol_v2",
]
