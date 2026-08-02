from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PUBLIC_EVIDENCE = EVIDENCE / "finqa_shadow_pool_replay_public_v1.json"
EXPECTED_EVIDENCE_SHA256 = (
    "98371c664d10bfafe21e57fd5a3104a12427fd9b91b1096b2a8285ec7af5008f"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload() -> dict[str, object]:
    return json.loads(PUBLIC_EVIDENCE.read_text(encoding="ascii"))


def test_e14_public_evidence_is_frozen_and_binds_implementation() -> None:
    payload = _payload()

    assert _sha256(PUBLIC_EVIDENCE) == EXPECTED_EVIDENCE_SHA256
    assert payload["schema_version"] == "finqa_shadow_pool_replay_public_v1"
    assert payload["protocol_sha256"] == _sha256(
        EVIDENCE / "finqa_shadow_pool_replay_protocol_v1.json"
    )
    for relative, expected in payload["implementation_sha256"].items():
        assert _sha256(ROOT / relative) == expected


def test_e14_public_evidence_passes_load_resource_and_fault_gates() -> None:
    payload = _payload()
    preparation = payload["preparation"]
    load = payload["load"]
    resources = payload["worker_pool_resources"]

    assert payload["decision"] == (
        "E14_BOUNDED_POOL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF"
    )
    assert all(payload["gate_checks"].values())
    assert all(payload["fault_injection"].values())
    assert preparation == {
        "preparation_failure_count": 11,
        "prepared_case_count": 117,
        "primary_failure_count": 0,
        "selected_case_count": 128,
    }
    assert load["attempted_count"] == 117
    assert load["admitted_count"] == 117
    assert load["completed_count"] == 117
    assert load["backpressure_rejected_count"] == 0
    assert load["deadline_exceeded_count"] == 0
    assert load["worker_restart_count"] == 0
    assert load["active_worker_high_watermark"] == 2
    assert load["queue_high_watermark"] <= 4
    assert payload["end_to_end_latency_ms"]["p95"] <= 500
    assert resources["workers_with_rss_samples"] == 2
    assert resources["worker_pool_rss_upper_bound_bytes"] <= 2 * 1024**3
    assert payload["all_primary_results_e8"] is True
    assert payload["challenger_status"] == "SHADOW_DEFAULT_OFF"


def test_e14_public_evidence_is_aggregate_only_and_label_free() -> None:
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
        '"per_request_outcome"',
        '"worker_slot_assignments"',
    ):
        assert prohibited_key not in serialized
