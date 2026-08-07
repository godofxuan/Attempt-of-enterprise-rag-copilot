from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.runtime.finqa_service_protocol_v2 import (
    FINQA_SERVICE_ASSEMBLY_VERSION,
    FINQA_SERVICE_PROTOCOL_ID,
    FinQAServiceWiringProtocolV2,
)


SOURCE_E18_PROTOCOL = "e1dabbd79901280e6d666a479d9cac15fda4c408ec2dc1412f148a6541491035"
SOURCE_E18_EVIDENCE = "82595dc7f0f2c119737a0e620bd1c1b8ce12a9c67d8b8a91335c3b0c1eac2747"


def _protocol() -> FinQAServiceWiringProtocolV2:
    return FinQAServiceWiringProtocolV2(
        source_e18_protocol_sha256=SOURCE_E18_PROTOCOL,
        source_e18_public_evidence_sha256=SOURCE_E18_EVIDENCE,
    )


def test_e19_protocol_freezes_default_off_and_primary_isolation() -> None:
    protocol = _protocol()

    assert protocol.protocol_id == FINQA_SERVICE_PROTOCOL_ID
    assert protocol.assembly_version == FINQA_SERVICE_ASSEMBLY_VERSION
    assert protocol.production_default_mode == "OFF"
    assert protocol.production_default_sample_basis_points == 0
    assert protocol.legacy_generic_offer_calls == 0
    assert protocol.secondary_retrieval_calls == 0
    assert protocol.planner_model_calls == 0
    assert protocol.primary_response_mutation_allowed is False
    assert protocol.feedback_receipt_mutation_allowed is False
    assert protocol.raw_content_in_metrics_allowed is False


def test_e19_protocol_rejects_unknown_or_relaxed_fields() -> None:
    with pytest.raises(ValidationError):
        FinQAServiceWiringProtocolV2.model_validate(
            {
                **_protocol().model_dump(mode="json"),
                "legacy_generic_offer_calls": 1,
            }
        )
    with pytest.raises(ValidationError):
        FinQAServiceWiringProtocolV2.model_validate(
            {
                **_protocol().model_dump(mode="json"),
                "unreviewed": True,
            }
        )
