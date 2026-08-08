import hashlib
import json
import subprocess
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


def test_finqa_selective_execution_evidence_is_reproducible_and_private() -> None:
    protocol_path = (
        EVIDENCE_ROOT / "finqa_selective_execution_protocol_v2.json"
    )
    incident_path = (
        EVIDENCE_ROOT
        / "finqa_selective_execution_protocol_v1_incident.json"
    )
    result_path = (
        EVIDENCE_ROOT / "finqa_selective_execution_results_v1.json"
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert result["status"] == "COMPLETE_NOT_ADOPTED"
    assert result["decision"]["enable_default_production_routing"] is False
    assert result["frozen_gate_evaluation"][
        "overall_adoption_gate_passed"
    ] is False
    assert hashlib.sha256(protocol_path.read_bytes()).hexdigest() == (
        result["protocol"]["sha256"]
    )
    assert hashlib.sha256(incident_path.read_bytes()).hexdigest() == (
        result["protocol"]["superseded_v1_incident_sha256"]
    )
    assert incident["execution_impact"]["cohort_cases_executed"] == 0
    assert incident["execution_impact"]["checkpoint_rows_written"] == 0
    assert (
        incident["affected_protocol"]["selected_case_ids_sha256"]
        == protocol["selected_case_ids_sha256"]
        == result["dataset"]["selected_case_ids_sha256"]
    )
    assert protocol["review_runtime_options"] == {
        "num_gpu": 5,
        "num_ctx": 4096,
        "num_batch": 512,
    }
    freeze_revision = protocol["freeze_parent_revision"]
    for relative, expected in protocol["source_sha256"].items():
        frozen_source = subprocess.check_output(
            ["git", "show", f"{freeze_revision}:{relative}"],
            cwd=ROOT,
        )
        assert hashlib.sha256(frozen_source).hexdigest() == expected

    quality = result["quality"]
    cost = result["routing_and_cost"]
    latency = result["observed_latency"]
    assert quality["selective_strict"] - quality["baseline_strict"] == (
        pytest.approx(0.02)
    )
    assert (
        quality["selective_grounded_strict"]
        - quality["baseline_grounded_strict"]
        == pytest.approx(0.02)
    )
    assert cost["generation_call_reduction"] == pytest.approx(
        1
        - cost["incremental_generation_calls"]
        / cost["full_strategy_incremental_generation_calls"]
    )
    assert cost["calculator_call_reduction"] == pytest.approx(
        1
        - cost["incremental_calculator_calls"]
        / cost["full_strategy_incremental_calculator_calls"]
    )
    assert latency["selective_to_shadow_full_ratio"] == pytest.approx(
        latency["selective_ms_total"]
        / latency["shadow_full_experiment_ms_total"]
    )
    assert latency["selective_reduction_vs_shadow_full"] == pytest.approx(
        1 - latency["selective_to_shadow_full_ratio"]
    )
    assert result["resume_incident"]["recovered_checkpoint_rows"] == 26
    assert result["resume_incident"]["final_checkpoint_rows"] == 100

    forbidden_keys = {
        "case_id",
        "question",
        "answer",
        "expression",
        "calculation",
        "evidence",
    }
    stack = [result, protocol, incident]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
