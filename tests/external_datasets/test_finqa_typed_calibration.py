from __future__ import annotations

from collections import Counter

import pytest

from app.external_datasets.finqa_typed_calibration import (
    CalibrationAdoptionGates,
    FinQATypedCalibrationProtocol,
    build_failure_matrix,
    case_ids_sha256,
    stratified_calibration_split,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FinQATypedRetrospectiveCase,
)


_SHA = "a" * 64
_REVISION = "b" * 40


def _arm(
    arm_id: str,
    *,
    correct: bool,
    failure_reason: str | None = None,
) -> FinQATypedArmEvaluation:
    answered = failure_reason is None
    return FinQATypedArmEvaluation(
        arm_id=arm_id,
        status="ANSWERED" if answered else "REFUSED",
        failure_reason=failure_reason,
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
        generation_calls=1 if answered else 0,
        compiler_calls=1 if answered else 0,
        generated_program_count=1 if answered else 0,
        latency_ms=10,
        candidate_count=2,
        selected_support_count=1 if answered else 0,
        valid_program_count=1 if answered else 0,
        invalid_program_count=0,
        duplicate_program_count=0,
    )


def _row(
    index: int,
    *,
    category: str,
    failure_reason: str | None,
) -> FinQATypedRetrospectiveCase:
    return FinQATypedRetrospectiveCase(
        case_id=f"private-case-{index:03d}",
        diagnostic_category=category,
        execution_order=(
            "B0_FREE_LITERAL",
            "B1_TYPED_SINGLE",
            "B2_TYPED_MULTI",
        ),
        selected_unit_ids=["table_1"],
        gold_unit_ids=["table_1"],
        selected_evidence_recall=1,
        admitted_unit_count=1,
        quarantined_unit_count=0,
        guard_rule_ids=[],
        historical_b0_strict_execution_match=index % 2 == 0,
        historical_b0_grounded_execution_match=index % 2 == 0,
        b0=_arm(
            "B0_FREE_LITERAL",
            correct=index % 2 == 0,
        ),
        b1=_arm(
            "B1_TYPED_SINGLE",
            correct=failure_reason is None and index % 3 == 0,
            failure_reason=failure_reason,
        ),
        b2=_arm("B2_TYPED_MULTI", correct=False),
    )


def _rows() -> list[FinQATypedRetrospectiveCase]:
    return [
        _row(
            index,
            category=(
                "operand_selection_signal"
                if index % 4 == 0
                else "correct_grounded"
            ),
            failure_reason=(
                None
                if index % 5 == 0
                else (
                    "unsupported_operation"
                    if index % 3 == 0
                    else "ambiguous_intent"
                )
            ),
        )
        for index in range(20)
    ]


def _protocol(
    rows: list[FinQATypedRetrospectiveCase],
) -> FinQATypedCalibrationProtocol:
    calibration, validation, strata = stratified_calibration_split(rows)
    return FinQATypedCalibrationProtocol(
        status="FROZEN_BEFORE_V2_IMPLEMENTATION",
        protocol_id="gate-e2-test",
        implementation_base_revision=_REVISION,
        source_gate_e_run_id="gate-e-run",
        source_gate_e_manifest_sha256=_SHA,
        source_gate_e_details_sha256=_SHA,
        source_selected_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in rows]
        ),
        split_seed="gate-e2-typed-contract-calibration-v1",
        validation_fraction=0.4,
        stratification_fields=(
            "diagnostic_category",
            "b1_v1_outcome",
        ),
        calibration_case_count=len(calibration),
        internal_validation_case_count=len(validation),
        calibration_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in calibration]
        ),
        internal_validation_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in validation]
        ),
        strata=strata,
        adoption_gates=CalibrationAdoptionGates(
            min_coverage=0.5,
            min_execution_accuracy_delta_vs_b0=-0.05,
            min_grounded_accuracy_delta_vs_b0=-0.05,
            max_correct_to_wrong_rate=0.05,
            min_wrong_to_correct_count=1,
            min_prevented_operand_failure_count=1,
            max_protocol_error_rate=0.1,
            max_latency_mean_multiplier=15,
            max_latency_p95_ms=40_000,
        ),
        immutable_safety_invariants=("fail closed",),
        non_claims=("not held out",),
    )


def test_stratified_split_is_deterministic_disjoint_and_exact() -> None:
    rows = _rows()
    first = stratified_calibration_split(rows)
    second = stratified_calibration_split(tuple(reversed(rows)))

    first_calibration = {row.case_id for row in first[0]}
    first_validation = {row.case_id for row in first[1]}
    assert first_calibration == {row.case_id for row in second[0]}
    assert first_validation == {row.case_id for row in second[1]}
    assert not first_calibration & first_validation
    assert first_calibration | first_validation == {
        row.case_id for row in rows
    }
    assert len(first_calibration) == 12
    assert len(first_validation) == 8
    assert sum(item.total_count for item in first[2]) == 20


def test_split_preserves_each_non_singleton_stratum_in_calibration() -> None:
    rows = _rows()
    calibration, validation, _ = stratified_calibration_split(rows)
    total_counts = Counter(
        (row.diagnostic_category, row.b1.failure_reason or "ANSWERED")
        for row in rows
    )
    calibration_counts = Counter(
        (row.diagnostic_category, row.b1.failure_reason or "ANSWERED")
        for row in calibration
    )
    validation_counts = Counter(
        (row.diagnostic_category, row.b1.failure_reason or "ANSWERED")
        for row in validation
    )
    for key, count in total_counts.items():
        if count >= 2:
            assert calibration_counts[key] >= 1
            assert validation_counts[key] >= 1


def test_case_id_hash_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="unique"):
        case_ids_sha256(["same", "same"])


def test_failure_matrix_contains_only_aggregate_contract_fields() -> None:
    rows = _rows()
    calibration, validation, _ = stratified_calibration_split(rows)
    matrix = build_failure_matrix(
        rows=rows,
        gold_program_by_case_id={
            row.case_id: (
                "subtract(120, 100), divide(#0, 100)"
                if index % 2
                else "divide(120, 100)"
            )
            for index, row in enumerate(rows)
        },
        calibration_rows=calibration,
        validation_rows=validation,
        protocol=_protocol(rows),
    )

    payload = matrix.model_dump(mode="json")
    serialized = matrix.model_dump_json()
    assert payload["case_count"] == 20
    assert sum(payload["b1_v1_failure_reason_counts"].values()) == 20
    assert payload["gold_operation_sequence_counts"] == {
        "divide": 10,
        "subtract>divide": 10,
    }
    assert "private-case" not in serialized
    assert set(payload["content_exclusions"]) == {
        "case_ids",
        "questions",
        "answers",
        "evidence_text",
        "gold_program_text",
    }
