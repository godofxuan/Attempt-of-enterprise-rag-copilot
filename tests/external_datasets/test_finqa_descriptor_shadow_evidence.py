from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"


def _sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _load(name: str) -> dict[str, object]:
    payload = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _all_keys(payload: object) -> set[str]:
    if isinstance(payload, dict):
        return set(payload).union(
            *( _all_keys(value) for value in payload.values())
        )
    if isinstance(payload, list):
        return set().union(*(_all_keys(value) for value in payload))
    return set()


def test_e12_public_mechanism_evidence_is_bound_and_default_off() -> None:
    evidence = _load("finqa_descriptor_shadow_mechanism_public_v1.json")

    assert evidence["decision"] == (
        "E12_MECHANISM_GATE_PASSED_SHADOW_REMAINS_DEFAULT_OFF"
    )
    assert evidence["claim"] == (
        "MECHANISM_ONLY_NOT_PRODUCTION_TRAFFIC_OR_ANSWER_ACCURACY"
    )
    assert evidence["protocol_sha256"] == _sha256(
        "docs/external_datasets/evidence/finqa_descriptor_shadow_protocol_v1.json"
    )
    assert evidence["serving_route_status"] == "DISABLED"
    assert evidence["frozen_test_status"] == "UNTOUCHED"
    assert evidence["model_call_count"] == 0
    assert all(evidence["gate_checks"].values())
    for relative, expected in evidence["implementation_sha256"].items():
        assert _sha256(relative) == expected


def test_e12_failure_injection_and_aggregate_probe_are_complete() -> None:
    evidence = _load("finqa_descriptor_shadow_mechanism_public_v1.json")
    failure = evidence["failure_injection"]
    probe = evidence["real_mechanism_probe"]
    metrics = probe["aggregate_metrics"]

    assert failure == {
        "circuit_challenger_call_count": 4,
        "circuit_observation_count": 9,
        "circuit_sequence_matches_protocol": True,
        "default_off_outcome": "DISABLED",
        "error_outcome": "CHALLENGER_ERROR",
        "timeout_outcome": "CHALLENGER_TIMEOUT",
    }
    assert probe["case_count"] == 1
    assert probe["champion_version"] == (
        "finqa_deterministic_descriptor_retriever_v5"
    )
    assert probe["observation_outcome"] in {"MATCH", "DIVERGED"}
    assert metrics["observation_count"] == 1
    assert metrics["role_count"] == 1
    assert sum(metrics["outcomes"].values()) == 1


def test_e12_public_evidence_contains_no_request_level_identifiers() -> None:
    evidence = _load("finqa_descriptor_shadow_mechanism_public_v1.json")
    prohibited = {
        "question",
        "question_text",
        "descriptor_id",
        "descriptor_ids",
        "candidate_id",
        "candidate_ids",
        "evidence_id",
        "evidence_ids",
        "source_id",
        "source_ids",
        "provenance",
        "input_binding_sha256",
    }

    assert not (_all_keys(evidence) & prohibited)
    script = (ROOT / "scripts/audit_finqa_descriptor_shadow_v1.py").read_text(
        encoding="utf-8"
    )
    assert "finqa_test_holdout" not in script
    assert ".private" not in script
