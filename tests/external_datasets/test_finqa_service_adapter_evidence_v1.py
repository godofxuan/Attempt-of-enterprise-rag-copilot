from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa_service_adapter_protocol_v1 import (
    load_finqa_service_adapter_protocol_v1,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PROTOCOL = EVIDENCE / "finqa_service_adapter_protocol_v1.json"
PUBLIC = EVIDENCE / "finqa_service_adapter_public_v1.json"
IMPLEMENTATION_PATHS = (
    "app/external_datasets/finqa_service_adapter_protocol_v1.py",
    "app/external_datasets/finqa_service_adapter_v1.py",
    "scripts/audit_finqa_service_adapter_v1.py",
)
SOURCE_FILES = {
    "source_e16_protocol_sha256": "dark_observation_service_protocol_v1.json",
    "source_e16_public_evidence_sha256": "dark_observation_service_public_v1.json",
    "source_e13_protocol_sha256": "finqa_shadow_worker_replay_protocol_v1.json",
    "source_e13_public_evidence_sha256": "finqa_shadow_worker_replay_public_v1.json",
}


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


def test_e17_public_evidence_binds_protocol_sources_and_implementation() -> None:
    protocol, protocol_sha256 = load_finqa_service_adapter_protocol_v1(
        PROTOCOL
    )
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))

    assert payload["protocol_sha256"] == protocol_sha256
    assert payload["claim"] == protocol.claim_label
    for field, filename in SOURCE_FILES.items():
        assert payload["source_binding"][field] == _sha256(
            EVIDENCE / filename
        )
        assert payload["source_binding"][field] == getattr(protocol, field)
    assert payload["source_binding"]["implementation_sha256"] == {
        relative: _sha256(ROOT / relative) for relative in IMPLEMENTATION_PATHS
    }


def test_e17_public_evidence_passes_frozen_adapter_gates() -> None:
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))
    eligibility = payload["eligibility_aggregates"]
    adapter = payload["adapter_aggregates"]

    assert payload["decision"] == (
        "E17_TYPED_ADAPTER_MECHANISM_PASSED_NOT_SERVICE_ENABLED"
    )
    assert payload["gate_checks"]
    assert all(payload["gate_checks"].values())
    assert eligibility["ineligible_worker_calls"] == 0
    assert eligibility["reason_counts"] == {
        "MISSING_SAFE_CATALOG": 1,
        "MISSING_TYPED_SKELETON": 1,
        "NOT_FINANCIAL_NUMERIC": 1,
        "POLICY_DENIED": 1,
        "TYPED_CONTEXT_COMPLETE": 1,
        "UNSUPPORTED_TYPED_CONTRACT": 1,
    }
    assert adapter["outcome_mapping"] == {"DIFFERENT": 1, "MATCH": 1}
    assert adapter["model_call_count"] == 0
    assert adapter["real_isolated_worker"]["observation_count"] == 2
    assert adapter["real_isolated_worker"]["worker_pid_after_close"] is None
    assert adapter["e16_composition"]["residual_service_workers"] == 0


def test_e17_public_evidence_contains_only_aggregate_safe_content() -> None:
    protocol, _ = load_finqa_service_adapter_protocol_v1(PROTOCOL)
    payload = json.loads(PUBLIC.read_text(encoding="ascii"))
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)

    assert not _all_keys(payload).intersection(
        protocol.public_output.prohibited_content
    )
    for forbidden in (
        "How did the synthetic operating metric change?",
        "What was the difference between the two synthetic periods?",
        "composition-request",
        "real-worker-",
        "injected resolver failure",
        "injected worker failure",
    ):
        assert forbidden not in serialized
