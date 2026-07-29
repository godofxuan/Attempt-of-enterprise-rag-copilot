import hashlib
import json
from pathlib import Path

import pytest

from app.external_datasets.finqa import FINQA_DEV_SHA256


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


def test_finqa_public_dev_diagnostic_is_aggregate_and_consistent() -> None:
    evidence = json.loads(
        (EVIDENCE_ROOT / "finqa_dev_diagnostic_v1.json").read_text(
            encoding="utf-8"
        )
    )
    oracle = evidence["arms"]["oracle"]
    hybrid = evidence["arms"]["hybrid_k10"]
    paired = evidence["paired_observation"]
    label_quality = evidence["label_quality_audit"]

    assert evidence["status"] == "OBSERVED_DEV_DIAGNOSTIC"
    assert evidence["dataset"]["selected_case_count"] == 100
    assert sum(oracle["diagnostic_category_counts"].values()) == 100
    assert sum(hybrid["diagnostic_category_counts"].values()) == 100
    assert (
        paired["correct_in_both"]
        + paired["wrong_in_both"]
        + paired["oracle_only_correct"]
        + paired["hybrid_only_correct"]
        == 100
    )
    assert (
        hybrid["metrics"]["execution_accuracy"]
        - oracle["metrics"]["execution_accuracy"]
        == pytest.approx(paired["hybrid_minus_oracle_execution_accuracy"])
    )
    assert (
        label_quality["full_dev_reported_answer_parseable"]
        + label_quality["full_dev_reported_answer_unparseable"]
        == evidence["dataset"]["source_case_count"]
    )
    assert (
        label_quality["selected_reported_answer_parseable"]
        + label_quality["selected_reported_answer_unparseable"]
        == evidence["dataset"]["selected_case_count"]
    )
    assert evidence["privacy"] == {
        "raw_dev_data_published": False,
        "case_ids_published": False,
        "questions_answers_evidence_or_expressions_published": False,
        "private_run_and_diagnostic_artifacts_published": False,
    }
    assert evidence["repository_verification"] == {
        "focused_public_and_diagnostic_tests_passed": 107,
        "full_tests_passed": 2578,
        "full_tests_skipped": 30,
        "full_test_warnings": 3,
        "public_audit_candidates": 968,
        "public_audit_findings": 0,
        "audit_boundary": (
            "Zero findings applies only to the implemented static audit rules."
        ),
    }
    forbidden_keys = {"case_id", "question", "answer", "expression"}
    stack = [evidence]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def test_finqa_uncertainty_evidence_and_protocol_erratum_are_consistent() -> None:
    protocol_path = (
        EVIDENCE_ROOT / "finqa_uncertainty_validation_protocol_v1.json"
    )
    result_path = EVIDENCE_ROOT / "finqa_uncertainty_results_v1.json"
    erratum_path = (
        EVIDENCE_ROOT
        / "finqa_plan_review_validation_protocol_erratum_v1.json"
    )
    original_protocol_path = (
        EVIDENCE_ROOT / "finqa_plan_review_validation_protocol_v1.json"
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    erratum = json.loads(erratum_path.read_text(encoding="utf-8"))
    original_protocol = json.loads(
        original_protocol_path.read_text(encoding="utf-8")
    )

    assert protocol["status"] == "FROZEN_BEFORE_VALIDATION_SIGNAL_EVALUATION"
    assert result["status"] == "COMPLETE_COST_GATE_PASS_NOT_ADOPTED"
    assert result["validation_gate"]["overall_cost_filter_gate_passed"] is True
    assert result["decision"]["enable_default_production_routing"] is False
    assert result["validation"]["split_sha256"] == FINQA_DEV_SHA256
    assert (
        erratum["affected_protocol"]["authoritative_value"]
        == FINQA_DEV_SHA256
    )
    assert (
        original_protocol["split_sha256"]
        == erratum["affected_protocol"]["original_incorrect_value"]
    )
    assert hashlib.sha256(original_protocol_path.read_bytes()).hexdigest() == (
        erratum["affected_protocol"]["sha256"]
    )
    for relative, expected in protocol["algorithm"]["source_sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == (
            expected
        )

    validation = result["validation"]
    assert validation["generation_call_reduction"] == pytest.approx(
        1
        - validation["incremental_generation_calls"]
        / validation["full_strategy_incremental_generation_calls"]
    )
    assert validation["calculator_call_reduction"] == pytest.approx(
        1
        - validation["incremental_calculator_calls"]
        / validation["full_strategy_incremental_calculator_calls"]
    )
    assert validation["gated_strict"] == validation["full_strategy_strict"]
    assert (
        validation["gated_grounded_strict"]
        == validation["full_strategy_grounded_strict"]
    )

    forbidden_keys = {"case_id", "question", "answer", "expression", "evidence"}
    stack = [result, protocol, erratum]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
