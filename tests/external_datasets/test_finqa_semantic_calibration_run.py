from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticCalibrationManifest,
    FinQASemanticPlanningCase,
    publish_semantic_calibration_run,
    semantic_arm_order,
    summarize_semantic_calibration,
    verify_semantic_calibration_run,
)
from app.external_datasets.finqa_semantic_planning_protocol import (
    load_semantic_planning_protocol,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FrozenModelIdentity,
    canonical_json_bytes,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_protocol_v1.json"
)
_SHA = "a" * 64


def _arm(
    arm_id: str,
    *,
    correct: bool,
    latency_ms: float = 10,
) -> FinQATypedArmEvaluation:
    return FinQATypedArmEvaluation(
        arm_id=arm_id,
        status="ANSWERED",
        final_answer="1",
        calculation="program",
        cited_unit_ids=["table_1"],
        answer_parseable=True,
        strict_execution_match=correct,
        presentation_tolerance_match=correct,
        citation_precision=1,
        citation_recall=1,
        grounded_execution_match=correct,
        grounded_presentation_match=correct,
        generation_calls=1,
        compiler_calls=1,
        generated_program_count=1,
        latency_ms=latency_ms,
        candidate_count=2,
        selected_support_count=1,
        valid_program_count=1,
        invalid_program_count=0,
        duplicate_program_count=0,
    )


def _rows() -> list[FinQASemanticPlanningCase]:
    rows = []
    for index in range(60):
        rows.append(
            FinQASemanticPlanningCase(
                case_id=f"case-{index}",
                diagnostic_category="fixture",
                selected_unit_ids=["table_1"],
                admitted_closure_unit_ids=["table_1"],
                gold_unit_ids=["table_1"],
                candidate_count_before_shortlist=2,
                candidate_count_after_shortlist=2,
                guard_scan_count=1,
                quarantined_unit_count=0,
                arm_order=semantic_arm_order(index),
                b4_demo_count=3,
                b4_demo_payload_sha256=_SHA,
                b0_stored=_arm(
                    "B0_FREE_LITERAL",
                    correct=index < 31,
                ),
                b1_v23_stored=_arm(
                    "B1_TYPED_SINGLE",
                    correct=index < 12,
                ),
                b2_direct=_arm(
                    "B2_TYPED_MULTI",
                    correct=index < 18,
                ),
                b3_roles=_arm(
                    "B2_TYPED_MULTI",
                    correct=index < 20,
                ),
                b4_dynamic_demos=_arm(
                    "B2_TYPED_MULTI",
                    correct=index < 21,
                ),
            )
        )
    return rows


def test_cyclic_arm_order_is_balanced() -> None:
    orders = [semantic_arm_order(index) for index in range(60)]
    for position in range(3):
        counts = {
            arm: sum(order[position] == arm for order in orders)
            for arm in orders[0]
        }
        assert set(counts.values()) == {20}


def test_semantic_summary_rejects_arms_that_fail_shadow_gate() -> None:
    protocol, _ = load_semantic_planning_protocol(PROTOCOL_PATH)
    summary = summarize_semantic_calibration(
        _rows(),
        protocol=protocol,
        demo_isolation_suite_passed=True,
        fail_closed_regression_suite_passed=True,
    )

    assert summary.selected_arm is None
    assert summary.decision == "CALIBRATION_REJECTED"
    assert all(
        not candidate.eligible
        for candidate in summary.candidates.values()
    )


def test_semantic_run_verifier_recomputes_frozen_gates(tmp_path) -> None:
    protocol, protocol_sha256 = load_semantic_planning_protocol(
        PROTOCOL_PATH
    )
    rows = _rows()
    protocol_for_rows = protocol.model_copy(
        update={
            "calibration_case_ids_sha256": case_ids_sha256(
                [row.case_id for row in rows]
            )
        }
    )
    summary = summarize_semantic_calibration(
        rows,
        protocol=protocol_for_rows,
        demo_isolation_suite_passed=True,
        fail_closed_regression_suite_passed=True,
    )
    manifest = FinQASemanticCalibrationManifest(
        run_id="semantic-test",
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e4_manifest_sha256=_SHA,
        source_gate_e4_details_sha256=_SHA,
        selected_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in rows]
        ),
        development_split_sha256=protocol.development_split_sha256,
        training_split_sha256=protocol.training_split_sha256,
        demo_index_sha256=_SHA,
        demo_index_count=100,
        answer_model=FrozenModelIdentity(
            name=protocol.answer_model_name,
            sha256=protocol.answer_model_sha256,
        ),
        execution_code_revision="b" * 40,
        implementation_file_sha256={"app/example.py": _SHA},
        planner_version="planner",
        demo_retriever_version="demo",
        validator_version="validator",
        compiler_version="compiler",
        timeout_seconds_per_call=120,
        max_attempts_per_stage=2,
        summary=summary,
    )
    output = publish_semantic_calibration_run(
        root=tmp_path,
        manifest=manifest,
        details=rows,
    )
    assert (
        verify_semantic_calibration_run(
            output,
            protocol=protocol_for_rows,
            protocol_sha256=protocol_sha256,
        ).summary
        == summary
    )

    raw = json.loads((output / "manifest.json").read_bytes())
    raw["summary"]["candidates"]["B2_MULTI_STEP_DIRECT"]["metrics"][
        "execution_accuracy"
    ] = 0.99
    (output / "manifest.json").write_bytes(
        canonical_json_bytes(raw, newline=True)
    )
    with pytest.raises(ValueError, match="summary contradicts"):
        verify_semantic_calibration_run(
            output,
            protocol=protocol_for_rows,
            protocol_sha256=protocol_sha256,
        )
