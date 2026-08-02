from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.runtime.dark_observation_protocol_v1 import (
    load_dark_observation_service_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "dark_observation_service_protocol_v1.json"
PUBLIC = EVIDENCE / "dark_observation_service_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/config.py",
    "app/main.py",
    "app/runtime/dark_observation.py",
    "app/runtime/dark_observation_protocol_v1.py",
    "app/runtime/resources.py",
    "scripts/audit_dark_observation_service_v1.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()


def test_e16_public_evidence_binds_protocol_sources_and_implementation() -> None:
    protocol, protocol_sha256 = load_dark_observation_service_protocol_v1(
        PROTOCOL
    )
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))

    assert payload["protocol_sha256"] == protocol_sha256
    assert payload["source_binding"]["source_e15_protocol_sha256"] == _sha256(
        EVIDENCE / "finqa_shadow_capacity_protocol_v1.json"
    )
    assert payload["source_binding"][
        "source_e15_public_evidence_sha256"
    ] == _sha256(EVIDENCE / "finqa_shadow_capacity_public_v1.json")
    assert payload["source_binding"]["implementation_sha256"] == {
        relative: _sha256(ROOT / relative) for relative in IMPLEMENTATION_PATHS
    }
    assert payload["claim"] == protocol.claim_label


def test_e16_public_evidence_passes_frozen_mechanism_gates() -> None:
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))
    aggregate = payload["aggregate_metrics"]
    failure = payload["failure_injection"]

    assert payload["gate_checks"]
    assert all(payload["gate_checks"].values())
    assert aggregate["default_off_provider_calls"] == 0
    assert aggregate["default_off_workers_alive_after_shutdown"] == 0
    assert aggregate["enabled_provider_calls"] == 24
    assert aggregate["enabled_workers_alive_after_shutdown"] == 0
    assert aggregate["primary_response_mismatches"] == 0
    assert aggregate["model_call_count"] == 0
    assert aggregate["dark_observation"]["offer_latency_ms"]["p95"] <= 10.0
    assert failure["backpressure"]["admitted_count"] == failure[
        "backpressure"
    ]["terminal_count"]
    assert failure["provider_error"]["completed_count"] == 0
    assert failure["deadline"]["completed_count"] == 0


def test_e16_public_evidence_contains_no_request_level_or_sensitive_content() -> None:
    protocol, _ = load_dark_observation_service_protocol_v1(PROTOCOL)
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)

    assert not _all_keys(payload).intersection(
        protocol.public_output.prohibited_content
    )
    for forbidden in (
        "E16 PRIVATE DARK TRAFFIC SENTINEL",
        "No supported answer from the unchanged primary path.",
        "e16-private-request-",
        "e16-audit-user",
        "e16-audit-tenant",
        "e16-audit-group",
        "injected private failure",
    ):
        assert forbidden not in serialized
