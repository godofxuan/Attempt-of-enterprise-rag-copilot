from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PUBLIC_EVIDENCE = EVIDENCE / "finqa_shadow_worker_replay_public_v1.json"
EXPECTED_EVIDENCE_SHA256 = (
    "b933f83dff1307828309222c276ea0a5d70372324cdd7822c79dd41b463106d3"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload() -> dict[str, object]:
    return json.loads(PUBLIC_EVIDENCE.read_text(encoding="ascii"))


def test_e13_public_evidence_is_frozen_and_binds_implementation() -> None:
    payload = _payload()

    assert _sha256(PUBLIC_EVIDENCE) == EXPECTED_EVIDENCE_SHA256
    assert payload["schema_version"] == "finqa_shadow_worker_replay_public_v1"
    assert payload["protocol_sha256"] == _sha256(
        EVIDENCE / "finqa_shadow_worker_replay_protocol_v1.json"
    )
    for relative, expected in payload["implementation_sha256"].items():
        assert _sha256(ROOT / relative) == expected


def test_e13_public_evidence_passes_operational_and_fault_gates() -> None:
    payload = _payload()
    preparation = payload["preparation"]
    observations = payload["observations"]

    assert payload["decision"] == (
        "E13_OPERATIONAL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF"
    )
    assert all(payload["gate_checks"].values())
    assert all(payload["fault_injection"].values())
    assert preparation == {
        "preparation_failure_count": 11,
        "prepared_case_count": 117,
        "primary_failure_count": 0,
        "selected_case_count": 128,
    }
    assert observations["attempted_count"] == 117
    assert observations["completed_count"] == 117
    assert observations["worker_restart_count"] == 0
    assert observations["model_call_count"] == 0
    assert payload["latency_ms"]["p95"] <= 250
    assert payload["worker_peak_rss_bytes"]["maximum"] <= 1024**3
    assert payload["all_primary_results_e8"] is True
    assert payload["challenger_status"] == "SHADOW_DEFAULT_OFF"


def test_e13_public_evidence_is_aggregate_only_and_label_free() -> None:
    payload = _payload()
    serialized = PUBLIC_EVIDENCE.read_text(encoding="ascii")

    assert payload["per_request_rows_persisted"] == 0
    assert payload["quality_labels_consumed"] == 0
    for prohibited_key in (
        '"question_text"',
        '"case_ids"',
        '"company_ids"',
        '"descriptor_ids"',
        '"candidate_ids"',
        '"evidence_ids"',
        '"source_ids"',
        '"provenance"',
        '"ranked_scores"',
        '"per_request_latency"',
    ):
        assert prohibited_key not in serialized
