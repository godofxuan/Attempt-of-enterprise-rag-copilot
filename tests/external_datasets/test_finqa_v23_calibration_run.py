from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FrozenModelIdentity,
    canonical_json_bytes,
)
from app.external_datasets.finqa_v23_calibration_protocol import (
    load_v23_calibration_protocol,
)
from app.external_datasets.finqa_v23_calibration_run import (
    FinQAV23CalibrationCase,
    FinQAV23CalibrationRunManifest,
    publish_v23_calibration_run,
    summarize_v23_calibration,
    verify_v23_calibration_run,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_v23_paired_calibration_protocol_v1.json"
)
_SHA = "a" * 64


def _arm(
    arm_id: str,
    *,
    correct: bool,
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
        latency_ms=10,
        candidate_count=2,
        selected_support_count=1,
        valid_program_count=1,
        invalid_program_count=0,
        duplicate_program_count=0,
    )


def _rows() -> list[FinQAV23CalibrationCase]:
    return [
        FinQAV23CalibrationCase(
            case_id=f"case-{index}",
            diagnostic_category="correct_grounded",
            selected_unit_ids=["table_1"],
            admitted_closure_unit_ids=["table_1"],
            gold_unit_ids=["table_1"],
            candidate_count_before_shortlist=2,
            candidate_count_after_shortlist=2,
            guard_scan_count=1,
            quarantined_unit_count=0,
            b0_stored=_arm(
                "B0_FREE_LITERAL",
                correct=index < 31,
            ),
            b1_v22_stored=_arm(
                "B1_TYPED_SINGLE",
                correct=index < 16,
            ),
            b1_v23_intervention=_arm(
                "B1_TYPED_SINGLE",
                correct=index < 12,
            ),
        )
        for index in range(60)
    ]


def test_v23_verifier_recomputes_summary_from_detail_rows(
    tmp_path,
) -> None:
    protocol, protocol_sha256 = load_v23_calibration_protocol(PROTOCOL_PATH)
    rows = _rows()
    summary = summarize_v23_calibration(
        rows,
        protocol=protocol,
        input_gate_e3_passed=True,
        fail_closed_regression_suite_passed=True,
    )
    case_hash = case_ids_sha256([row.case_id for row in rows])
    manifest = FinQAV23CalibrationRunManifest(
        run_id="v23-test",
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e2_details_sha256=_SHA,
        source_gate_e3_manifest_sha256=_SHA,
        selected_case_ids_sha256=case_hash,
        answer_model=FrozenModelIdentity(
            name=protocol.answer_model_name,
            sha256=protocol.answer_model_sha256,
        ),
        execution_code_revision="b" * 40,
        implementation_file_sha256={"app/example.py": _SHA},
        planner_version="planner-v23",
        validator_version="validator-v23",
        compiler_version="compiler-v23",
        timeout_seconds=120,
        max_attempts=2,
        summary=summary,
    )
    output = publish_v23_calibration_run(
        root=tmp_path,
        manifest=manifest,
        details=rows,
    )
    assert verify_v23_calibration_run(output).summary == summary

    raw = json.loads((output / "manifest.json").read_bytes())
    raw["summary"]["b1_v23_intervention"]["execution_accuracy"] = 0.9
    (output / "manifest.json").write_bytes(
        canonical_json_bytes(raw, newline=True)
    )
    with pytest.raises(ValueError, match="summary does not match detail"):
        verify_v23_calibration_run(output)


def test_v23_verifier_checks_frozen_protocol(tmp_path) -> None:
    protocol, protocol_sha256 = load_v23_calibration_protocol(PROTOCOL_PATH)
    rows = _rows()
    summary = summarize_v23_calibration(
        rows,
        protocol=protocol,
        input_gate_e3_passed=True,
        fail_closed_regression_suite_passed=True,
    )
    manifest = FinQAV23CalibrationRunManifest(
        run_id="v23-protocol-test",
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e2_details_sha256=_SHA,
        source_gate_e3_manifest_sha256=_SHA,
        selected_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in rows]
        ),
        answer_model=FrozenModelIdentity(
            name=protocol.answer_model_name,
            sha256=protocol.answer_model_sha256,
        ),
        execution_code_revision="b" * 40,
        implementation_file_sha256={"app/example.py": _SHA},
        planner_version="planner-v23",
        validator_version="validator-v23",
        compiler_version="compiler-v23",
        timeout_seconds=120,
        max_attempts=2,
        summary=summary,
    )
    output = publish_v23_calibration_run(
        root=tmp_path,
        manifest=manifest,
        details=rows,
    )

    with pytest.raises(ValueError, match="frozen protocol"):
        verify_v23_calibration_run(
            output,
            protocol=protocol.model_copy(
                update={"answer_model_sha256": "c" * 64}
            ),
        )
