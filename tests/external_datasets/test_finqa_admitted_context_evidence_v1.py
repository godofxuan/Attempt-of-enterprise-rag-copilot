from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa_admitted_context_protocol_v1 import (
    load_finqa_admitted_context_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "external_datasets" / "evidence"
PROTOCOL = EVIDENCE / "finqa_admitted_context_protocol_v1.json"
PUBLIC = EVIDENCE / "finqa_admitted_context_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_admitted_context_protocol_v1.py",
    "app/external_datasets/finqa_admitted_context_v1.py",
    "scripts/audit_finqa_admitted_context_v1.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e18_public_evidence_binds_protocol_sources_and_implementation() -> None:
    protocol, protocol_sha256 = load_finqa_admitted_context_protocol_v1(
        PROTOCOL
    )
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))

    assert payload["protocol_sha256"] == protocol_sha256
    assert payload["source_binding"]["source_e17_protocol_sha256"] == (
        protocol.source_e17_protocol_sha256
    )
    assert payload["source_binding"]["source_e17_public_evidence_sha256"] == (
        protocol.source_e17_public_evidence_sha256
    )
    assert payload["source_binding"]["source_guard_sha256"] == (
        protocol.source_guard_sha256
    )
    assert payload["source_binding"]["implementation_sha256"] == {
        relative: _sha256(ROOT / relative) for relative in IMPLEMENTATION_PATHS
    }


def test_e18_public_evidence_passes_frozen_mechanism_gates() -> None:
    protocol, _ = load_finqa_admitted_context_protocol_v1(PROTOCOL)
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))
    rules = payload["typed_context_aggregates"]
    admission = payload["admission_aggregates"]

    assert payload["gate_checks"]
    assert all(payload["gate_checks"].values())
    assert rules["families"] == list(
        protocol.audit_profile.required_rule_families
    )
    assert rules["preparation_latency_ms"]["p95"] <= (
        protocol.audit_profile.max_preparation_p95_ms
    )
    assert rules["secondary_retrieval_calls"] == 0
    assert rules["model_calls"] == 0
    assert admission["enabled"]["admitted_count"] == 8
    assert admission["enabled"]["completed_count"] == 8
    assert admission["enabled"]["pending_contexts"] == 0
    assert admission["backpressure"]["rejected_outcome"] == "BACKPRESSURE"
    assert admission["backpressure"]["rejected_discarded"] is True
    assert payload["primary_isolation"]["response_mismatch_count"] == 0
    assert payload["public_content_findings"] == 0


def test_e18_public_evidence_contains_no_private_request_content() -> None:
    payload = PUBLIC.read_text(encoding="ascii")

    for forbidden in (
        "E18 PRIVATE FINANCE SENTINEL",
        "E18 PRIVATE REVENUE",
        "e18-private-tenant",
        "e18-private-finance",
        "e18-private-chunk-a",
        "E18 private primary response sentinel.",
        "must remain byte-identical",
    ):
        assert forbidden not in payload

