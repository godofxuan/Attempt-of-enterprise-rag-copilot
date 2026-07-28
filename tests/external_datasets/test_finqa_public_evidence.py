import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "docs" / "external_datasets" / "evidence"


def test_finqa_public_holdout_evidence_is_content_free_and_consistent() -> None:
    evidence = json.loads(
        (EVIDENCE_ROOT / "finqa_test_holdout_v1.json").read_text(
            encoding="utf-8"
        )
    )
    protocol_path = ROOT / evidence["protocol"]["path"]
    incident_path = ROOT / evidence["preexecution_incident"]["path"]
    oracle = evidence["arms"]["oracle"]["metrics"]
    hybrid = evidence["arms"]["hybrid_k10"]["metrics"]
    deltas = evidence["observed_deltas_hybrid_minus_oracle"]

    assert evidence["status"] == "OBSERVED"
    assert evidence["dataset"]["selected_case_count"] == 100
    assert evidence["privacy"] == {
        "raw_test_data_published": False,
        "case_ids_published": False,
        "questions_answers_or_evidence_published": False,
        "private_artifacts_published": False,
    }
    assert hashlib.sha256(protocol_path.read_bytes()).hexdigest() == (
        evidence["protocol"]["sha256"]
    )
    assert hashlib.sha256(incident_path.read_bytes()).hexdigest() == (
        evidence["preexecution_incident"]["sha256"]
    )
    assert hybrid["execution_accuracy"] - oracle["execution_accuracy"] == (
        pytest.approx(deltas["execution_accuracy"])
    )
    assert hybrid["evidence_recall"] - oracle["evidence_recall"] == (
        pytest.approx(deltas["evidence_recall"])
    )
    assert hybrid["latency_ms_mean"] - oracle["latency_ms_mean"] == (
        pytest.approx(deltas["latency_ms_mean"])
    )
    assert (
        evidence["preexecution_incident"]["model_generation_calls"] == 0
    )
