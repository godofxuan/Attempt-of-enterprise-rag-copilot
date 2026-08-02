from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/external_datasets/evidence"
PUBLIC_EVIDENCE = EVIDENCE / "finqa_shadow_capacity_public_v1.json"
EXPECTED_EVIDENCE_SHA256 = (
    "5e299683c2fd6fa0ad520fc2264ccc06b68dfe214e0c16b34b065f28e9bfc82f"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload() -> dict[str, object]:
    return json.loads(PUBLIC_EVIDENCE.read_text(encoding="ascii"))


def test_e15_public_evidence_is_frozen_and_binds_implementation() -> None:
    payload = _payload()

    assert _sha256(PUBLIC_EVIDENCE) == EXPECTED_EVIDENCE_SHA256
    assert payload["schema_version"] == "finqa_shadow_capacity_public_v1"
    assert payload["protocol_sha256"] == _sha256(
        EVIDENCE / "finqa_shadow_capacity_protocol_v1.json"
    )
    for relative, expected in payload["implementation_sha256"].items():
        assert _sha256(ROOT / relative) == expected


def test_e15_public_evidence_passes_capacity_and_scaling_gates() -> None:
    payload = _payload()
    trials = payload["trial_aggregates"]
    configurations = payload["configuration_aggregates"]
    comparisons = {
        item["comparison_id"]: item for item in payload["scaling_comparisons"]
    }

    assert payload["decision"] == (
        "E15_LOCAL_CAPACITY_ENVELOPE_SUPPORTED_SHADOW_REMAINS_DEFAULT_OFF"
    )
    assert all(payload["gate_checks"].values())
    assert len(trials) == 27
    assert len(configurations) == 9
    assert sum(item["attempted_count"] for item in trials) == 3_159
    assert sum(item["completed_count"] for item in trials) == 3_159
    assert sum(item["backpressure_rejected_count"] for item in trials) == 0
    assert sum(item["deadline_exceeded_count"] for item in trials) == 0
    assert sum(item["worker_error_count"] for item in trials) == 0
    assert sum(item["worker_restart_count"] for item in trials) == 0
    assert all(item["close_completed"] for item in trials)
    assert all(item["residual_worker_pid_count"] == 0 for item in trials)
    assert comparisons[
        "workers_1_to_2_callers_4"
    ]["median_throughput_speedup"] > 2.0
    assert comparisons[
        "workers_1_to_4_callers_8"
    ]["median_throughput_speedup"] > 3.4
    assert payload["local_recommendation"]["config_id"] == "w4-c4"


def test_e15_public_evidence_is_aggregate_only_and_label_free() -> None:
    payload = _payload()
    serialized = PUBLIC_EVIDENCE.read_text(encoding="ascii")

    assert payload["per_request_rows_persisted"] == 0
    assert payload["quality_labels_consumed"] == 0
    assert payload["internal_cohort_status"] == "CONSUMED_NOT_ACCESSED"
    assert payload["frozen_test_status"] == "UNTOUCHED"
    for prohibited_key in (
        '"question_text"',
        '"numeric_values"',
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
