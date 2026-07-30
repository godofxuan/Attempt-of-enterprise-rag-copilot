from __future__ import annotations

import pytest

from app.external_datasets.finqa_typed_calibration import (
    CalibrationAdoptionGates,
    case_ids_sha256,
)
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
    FinQATypedCalibrationRunManifest,
    publish_calibration_run,
    summarize_calibration_run,
    verify_calibration_run,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FrozenModelIdentity,
)


_SHA = "a" * 64


def _arm(
    arm_id: str,
    *,
    correct: bool,
    status: str = "ANSWERED",
    latency_ms: float = 10,
) -> FinQATypedArmEvaluation:
    answered = status == "ANSWERED"
    return FinQATypedArmEvaluation(
        arm_id=arm_id,
        status=status,
        failure_reason=None if answered else "invalid_program_schema",
        final_answer="1" if answered else "",
        calculation="program" if answered else "",
        cited_unit_ids=["table_1"] if answered else [],
        answer_parseable=answered,
        strict_execution_match=correct if answered else False,
        presentation_tolerance_match=correct if answered else False,
        citation_precision=1 if answered else 0,
        citation_recall=1 if answered else 0,
        grounded_execution_match=correct if answered else False,
        grounded_presentation_match=correct if answered else False,
        generation_calls=1,
        compiler_calls=1 if answered else 0,
        generated_program_count=1 if answered else 0,
        latency_ms=latency_ms,
        candidate_count=2,
        selected_support_count=1 if answered else 0,
        valid_program_count=1 if answered else 0,
        invalid_program_count=0,
        duplicate_program_count=0,
    )


def _rows(cohort: str) -> list[FinQATypedCalibrationRunCase]:
    return [
        FinQATypedCalibrationRunCase(
            case_id=f"case-{index}",
            cohort=cohort,
            diagnostic_category=(
                "operand_selection_signal"
                if index == 1
                else "correct_grounded"
            ),
            selected_unit_ids=["table_1"],
            gold_unit_ids=["table_1"],
            b0=_arm(
                "B0_FREE_LITERAL",
                correct=index in {0, 2},
                latency_ms=1,
            ),
            b1_v1=_arm(
                "B1_TYPED_SINGLE",
                correct=False,
                status="PROTOCOL_ERROR",
                latency_ms=20,
            ),
            b1_v2=_arm(
                "B1_TYPED_SINGLE",
                correct=index in {0, 1},
                latency_ms=10,
            ),
        )
        for index in range(3)
    ]


def _gates() -> CalibrationAdoptionGates:
    return CalibrationAdoptionGates(
        min_coverage=0.5,
        min_execution_accuracy_delta_vs_b0=-0.05,
        min_grounded_accuracy_delta_vs_b0=-0.05,
        max_correct_to_wrong_rate=0.4,
        min_wrong_to_correct_count=1,
        min_prevented_operand_failure_count=1,
        max_protocol_error_rate=0.1,
        max_latency_mean_multiplier=15,
        max_latency_p95_ms=40_000,
    )


def test_calibration_summary_does_not_make_adoption_claim() -> None:
    summary = summarize_calibration_run(
        _rows("calibration"),
        cohort="calibration",
        adoption_gates=_gates(),
    )

    assert summary.gate_status == "CALIBRATION_ONLY"
    assert summary.gate_checks == ()
    assert summary.b1_v2.execution_accuracy == pytest.approx(2 / 3)
    assert summary.comparison.wrong_to_correct_count == 1
    assert summary.comparison.prevented_operand_failure_count == 1


def test_internal_validation_requires_every_gate() -> None:
    summary = summarize_calibration_run(
        _rows("internal_validation"),
        cohort="internal_validation",
        adoption_gates=_gates(),
        fail_closed_regression_suite_passed=True,
    )

    assert summary.gate_status == "ADOPTION_GATE_PASSED"
    assert all(check.passed for check in summary.gate_checks)


def test_calibration_run_publication_is_hash_bound(tmp_path) -> None:
    rows = _rows("calibration")
    summary = summarize_calibration_run(
        rows,
        cohort="calibration",
        adoption_gates=_gates(),
    )
    manifest = FinQATypedCalibrationRunManifest(
        run_id="gate-e2-test",
        protocol_id="gate-e2-protocol",
        protocol_sha256=_SHA,
        source_gate_e_run_id="gate-e",
        source_gate_e_details_sha256=_SHA,
        cohort="calibration",
        selected_case_count=3,
        selected_case_ids_sha256=case_ids_sha256(
            ["case-0", "case-1", "case-2"]
        ),
        answer_model=FrozenModelIdentity(name="fake", sha256=_SHA),
        execution_code_revision="b" * 40,
        implementation_file_sha256={"app/example.py": _SHA},
        intent_version="intent-v2",
        validator_version="validator-v2",
        compiler_version="compiler-v2",
        planner_version="planner-v2",
        timeout_seconds=120,
        max_attempts=2,
        adoption_gates=_gates(),
        fail_closed_regression_suite_passed=False,
        summary=summary,
    )

    output = publish_calibration_run(
        root=tmp_path,
        manifest=manifest,
        details=rows,
    )
    verified = verify_calibration_run(output)
    assert verified.summary == summary

    with (output / "details.jsonl").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_calibration_run(output)
