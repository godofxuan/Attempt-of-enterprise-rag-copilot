from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.external_datasets.wixqa import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "final_evidence_closure" / "evidence"


def _load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_fts_hard_crash_evidence_is_complete_and_fail_closed() -> None:
    report = _load("fts_hard_crash_matrix_v1.json")
    assert report["status"] == "PASSED"
    assert report["power_loss_status"] == "NOT_RUN"
    assert report["kill_point_count"] == 10
    assert report["repetition_count"] == 3
    assert len(report["rows"]) == 30
    assert {(row["repetition"], row["kill_point"]) for row in report["rows"]} == {
        (repetition, kill_point)
        for repetition in range(1, 4)
        for kill_point in range(1, 11)
    }
    assert all(row["integrity_check"] == "ok" for row in report["rows"])
    assert all(row["restart_status"] == "PASSED" for row in report["rows"])
    assert all(not row["manual_intervention_required"] for row in report["rows"])
    assert all(not row["unrecoverable_stale_lock"] for row in report["rows"])


def test_active_pointer_crash_evidence_is_old_or_new_and_restartable() -> None:
    report = _load("active_pointer_crash_matrix_v1.json")
    assert report["status"] == "PASSED"
    assert report["power_loss_status"] == "NOT_RUN"
    assert report["stage_count"] == 4
    assert report["repetition_count"] == 3
    assert len(report["rows"]) == 12
    assert all(row["manifest_verified_after_crash"] for row in report["rows"])
    assert all(not row["mixed_or_truncated_pointer"] for row in report["rows"])
    assert all(row["restart_active_run_id"] == "run-two" for row in report["rows"])
    assert all(row["temp_count_after_restart"] == 0 for row in report["rows"])


def test_answer_citation_protocol_and_partial_evidence_are_hash_bound() -> None:
    protocol = _load("answer_citation_60_protocol_v1.json")
    evidence = _load("answer_citation_60_automated_v1.json")
    assert protocol["case_count"] == 60
    assert protocol["single_document_count"] == 40
    assert protocol["multi_document_count"] == 20
    assert len(protocol["cases"]) == 60
    assert len({case["question_id"] for case in protocol["cases"]}) == 60
    assert evidence["protocol_sha256"] == hashlib.sha256(
        canonical_json_bytes(protocol)
    ).hexdigest()
    assert evidence["status"] == "PARTIAL_AUTOMATED_ONLY"
    assert evidence["answer_correctness"] == "NOT_RUN"
    assert evidence["human_review_status"] == "NOT_RUN"
    assert evidence["supported_claim_precision"] is None
    assert evidence["candidate"]["retrieval_recall_at_5"] == (
        evidence["control"]["retrieval_recall_at_5"]
    )


def test_security_gap_and_rejected_registry_cannot_be_promoted_silently() -> None:
    security = _load("guard_60_30_holdout_status_v1.json")
    assert security["status"] == "NOT_RUN_INSUFFICIENT_QUALIFYING_HOLDOUT"
    assert security["required_attack_count"] == 60
    assert security["required_benign_count"] == 30

    registry = _load("rejected_experiments_v1.json")
    rows = {row["experiment_id"]: row for row in registry["experiments"]}
    assert set(rows) == {
        "equal_rrf",
        "agent_quality_route",
        "cross_encoder_reranker",
        "typed_planning",
        "enterprise_dense",
    }
    assert all(not row["enabled"] for row in rows.values())
    assert all(row["result"] in {"REJECTED", "NO_GO"} for row in rows.values())


def test_claim_audit_preserves_forbidden_and_not_run_boundaries() -> None:
    audit = _load("claim_audit_v1.json")
    statuses = {row["claim"]: row["status"] for row in audit["claims"]}
    assert statuses["Current Agent improves WixQA answer quality"] == "REJECTED"
    assert statuses[
        "Guard passes a new independent 60-attack/30-benign holdout"
    ] == "NOT_RUN"
    assert statuses["Agent deadline is a hard wall-clock cancellation"] == (
        "FORBIDDEN"
    )
