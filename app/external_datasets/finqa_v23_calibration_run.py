from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationArmSummary,
    FinQATypedCalibrationGateCheck,
    summarize_arm,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FrozenModelIdentity,
    canonical_json_bytes,
)
from app.external_datasets.finqa_v23_calibration_protocol import (
    FinQAV23PairedCalibrationProtocol,
)
from app.filesystem import atomic_directory_move


RUN_SCHEMA_VERSION = "finqa_v23_paired_calibration_run_v1"
_ARTIFACTS = {"details.jsonl", "summary.json"}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinQAV23CalibrationCase(_StrictModel):
    case_id: str = Field(min_length=1)
    diagnostic_category: str = Field(min_length=1, max_length=128)
    selected_unit_ids: tuple[str, ...] = Field(min_length=1)
    admitted_closure_unit_ids: tuple[str, ...] = Field(min_length=1)
    gold_unit_ids: tuple[str, ...] = Field(min_length=1)
    candidate_count_before_shortlist: int = Field(ge=0, le=128)
    candidate_count_after_shortlist: int = Field(ge=0, le=24)
    guard_scan_count: int = Field(ge=1, le=32)
    quarantined_unit_count: int = Field(ge=0, le=32)
    b0_stored: FinQATypedArmEvaluation
    b1_v22_stored: FinQATypedArmEvaluation
    b1_v23_intervention: FinQATypedArmEvaluation

    @model_validator(mode="after")
    def validate_arms(self) -> FinQAV23CalibrationCase:
        if (
            self.b0_stored.arm_id != "B0_FREE_LITERAL"
            or self.b1_v22_stored.arm_id != "B1_TYPED_SINGLE"
            or self.b1_v23_intervention.arm_id != "B1_TYPED_SINGLE"
        ):
            raise ValueError("v2.3 calibration arm identity is invalid")
        if self.guard_scan_count < len(self.admitted_closure_unit_ids):
            raise ValueError("v2.3 closure scan accounting is invalid")
        return self


class FinQAV23PairedComparison(_StrictModel):
    case_count: Literal[60] = 60
    execution_accuracy_delta: float = Field(ge=-1, le=1)
    grounded_accuracy_delta: float = Field(ge=-1, le=1)
    correct_to_wrong_count: int = Field(ge=0, le=60)
    correct_to_wrong_rate: float = Field(ge=0, le=1)
    wrong_to_correct_count: int = Field(ge=0, le=60)


class FinQAV23CalibrationSummary(_StrictModel):
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    case_count: Literal[60] = 60
    b0_stored: FinQATypedCalibrationArmSummary
    b1_v22_stored: FinQATypedCalibrationArmSummary
    b1_v23_intervention: FinQATypedCalibrationArmSummary
    comparison_vs_v22: FinQAV23PairedComparison
    comparison_vs_b0: FinQAV23PairedComparison
    input_gate_e3_passed: bool
    fail_closed_regression_suite_passed: bool
    gate_checks: tuple[FinQATypedCalibrationGateCheck, ...]
    decision: Literal[
        "ELIGIBLE_FOR_INTERNAL_VALIDATION",
        "CALIBRATION_REJECTED",
    ]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]

    @model_validator(mode="after")
    def validate_decision(self) -> FinQAV23CalibrationSummary:
        expected = (
            "ELIGIBLE_FOR_INTERNAL_VALIDATION"
            if self.gate_checks and all(check.passed for check in self.gate_checks)
            else "CALIBRATION_REJECTED"
        )
        if self.decision != expected:
            raise ValueError("v2.3 decision contradicts frozen gates")
        return self


class FinQAV23CalibrationRunManifest(_StrictModel):
    schema_version: Literal[
        "finqa_v23_paired_calibration_run_v1"
    ] = RUN_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e2_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e3_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    answer_model: FrozenModelIdentity
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_file_sha256: dict[str, str] = Field(min_length=1)
    planner_version: str = Field(min_length=1)
    validator_version: str = Field(min_length=1)
    compiler_version: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    summary: FinQAV23CalibrationSummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("implementation_file_sha256", "artifacts")
    @classmethod
    def validate_hash_map(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not key
            or Path(key).is_absolute()
            or ".." in Path(key).parts
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for key, digest in value.items()
        ):
            raise ValueError("v2.3 manifest hash map is invalid")
        return dict(sorted(value.items()))


def _comparison(
    baseline: Sequence[FinQATypedArmEvaluation],
    intervention: Sequence[FinQATypedArmEvaluation],
) -> FinQAV23PairedComparison:
    if len(baseline) != 60 or len(intervention) != 60:
        raise ValueError("v2.3 paired comparison requires 60 cases")
    baseline_summary = summarize_arm(baseline)
    intervention_summary = summarize_arm(intervention)
    correct_to_wrong = sum(
        before.strict_execution_match and not after.strict_execution_match
        for before, after in zip(baseline, intervention, strict=True)
    )
    wrong_to_correct = sum(
        not before.strict_execution_match and after.strict_execution_match
        for before, after in zip(baseline, intervention, strict=True)
    )
    return FinQAV23PairedComparison(
        execution_accuracy_delta=(
            intervention_summary.execution_accuracy
            - baseline_summary.execution_accuracy
        ),
        grounded_accuracy_delta=(
            intervention_summary.grounded_execution_accuracy
            - baseline_summary.grounded_execution_accuracy
        ),
        correct_to_wrong_count=correct_to_wrong,
        correct_to_wrong_rate=correct_to_wrong / 60,
        wrong_to_correct_count=wrong_to_correct,
    )


def _check(
    gate: str,
    comparator: Literal["ge", "le", "required"],
    observed: float | bool,
    threshold: float | bool,
) -> FinQATypedCalibrationGateCheck:
    passed = (
        observed >= threshold
        if comparator == "ge"
        else (observed <= threshold if comparator == "le" else observed is True)
    )
    return FinQATypedCalibrationGateCheck(
        gate=gate,
        comparator=comparator,
        observed=observed,
        threshold=threshold,
        passed=passed,
    )


def summarize_v23_calibration(
    rows: Sequence[FinQAV23CalibrationCase],
    *,
    protocol: FinQAV23PairedCalibrationProtocol,
    input_gate_e3_passed: bool,
    fail_closed_regression_suite_passed: bool,
) -> FinQAV23CalibrationSummary:
    if len(rows) != 60 or len({row.case_id for row in rows}) != 60:
        raise ValueError("v2.3 calibration rows must contain 60 unique cases")
    b0 = [row.b0_stored for row in rows]
    v22 = [row.b1_v22_stored for row in rows]
    v23 = [row.b1_v23_intervention for row in rows]
    b0_summary = summarize_arm(b0)
    v22_summary = summarize_arm(v22)
    v23_summary = summarize_arm(v23)
    vs_v22 = _comparison(v22, v23)
    vs_b0 = _comparison(b0, v23)
    progress = protocol.progress_gates
    shadow = protocol.adoption_shadow_gates
    latency_multiplier = (
        v23_summary.latency_ms_mean / v22_summary.latency_ms_mean
        if v22_summary.latency_ms_mean > 0
        else float("inf")
    )
    checks = (
        _check("coverage", "ge", v23_summary.coverage, progress.min_coverage),
        _check(
            "execution_accuracy_delta_vs_v22",
            "ge",
            vs_v22.execution_accuracy_delta,
            progress.min_execution_accuracy_delta_vs_v22,
        ),
        _check(
            "grounded_accuracy_delta_vs_v22",
            "ge",
            vs_v22.grounded_accuracy_delta,
            progress.min_grounded_accuracy_delta_vs_v22,
        ),
        _check(
            "correct_to_wrong_rate_vs_v22",
            "le",
            vs_v22.correct_to_wrong_rate,
            progress.max_correct_to_wrong_rate_vs_v22,
        ),
        _check(
            "wrong_to_correct_count_vs_v22",
            "ge",
            float(vs_v22.wrong_to_correct_count),
            float(progress.min_wrong_to_correct_count_vs_v22),
        ),
        _check(
            "protocol_error_rate",
            "le",
            v23_summary.protocol_error_count / 60,
            progress.max_protocol_error_rate,
        ),
        _check(
            "latency_mean_multiplier_vs_v22",
            "le",
            latency_multiplier,
            progress.max_latency_mean_multiplier_vs_v22,
        ),
        _check(
            "latency_p95_ms",
            "le",
            v23_summary.latency_ms_p95,
            progress.max_latency_p95_ms,
        ),
        _check(
            "gate_e3_input",
            "required",
            input_gate_e3_passed,
            True,
        ),
        _check(
            "fail_closed_regression_suite",
            "required",
            fail_closed_regression_suite_passed,
            True,
        ),
        _check(
            "execution_accuracy_delta_vs_b0",
            "ge",
            vs_b0.execution_accuracy_delta,
            shadow.min_execution_accuracy_delta_vs_b0,
        ),
        _check(
            "grounded_accuracy_delta_vs_b0",
            "ge",
            vs_b0.grounded_accuracy_delta,
            shadow.min_grounded_accuracy_delta_vs_b0,
        ),
        _check(
            "correct_to_wrong_rate_vs_b0",
            "le",
            vs_b0.correct_to_wrong_rate,
            shadow.max_correct_to_wrong_rate_vs_b0,
        ),
    )
    decision = (
        "ELIGIBLE_FOR_INTERNAL_VALIDATION"
        if all(check.passed for check in checks)
        else "CALIBRATION_REJECTED"
    )
    return FinQAV23CalibrationSummary(
        claim_label=protocol.claim_label,
        b0_stored=b0_summary,
        b1_v22_stored=v22_summary,
        b1_v23_intervention=v23_summary,
        comparison_vs_v22=vs_v22,
        comparison_vs_b0=vs_b0,
        input_gate_e3_passed=input_gate_e3_passed,
        fail_closed_regression_suite_passed=(
            fail_closed_regression_suite_passed
        ),
        gate_checks=checks,
        decision=decision,
        internal_validation_status="NOT_RUN",
        frozen_test_status="UNTOUCHED",
    )


def publish_v23_calibration_run(
    *,
    root: Path,
    manifest: FinQAV23CalibrationRunManifest,
    details: Sequence[FinQAV23CalibrationCase],
) -> Path:
    root = root.resolve()
    final = root / manifest.run_id
    if final.exists():
        raise FileExistsError("v2.3 calibration run already exists")
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    try:
        details_bytes = b"".join(
            canonical_json_bytes(row.model_dump(mode="json"), newline=True)
            for row in details
        )
        summary_bytes = canonical_json_bytes(
            manifest.summary.model_dump(mode="json"),
            newline=True,
        )
        artifacts = {
            "details.jsonl": hashlib.sha256(details_bytes).hexdigest(),
            "summary.json": hashlib.sha256(summary_bytes).hexdigest(),
        }
        final_manifest = manifest.model_copy(update={"artifacts": artifacts})
        (staging / "details.jsonl").write_bytes(details_bytes)
        (staging / "summary.json").write_bytes(summary_bytes)
        (staging / "manifest.json").write_bytes(
            canonical_json_bytes(
                final_manifest.model_dump(mode="json"),
                newline=True,
            )
        )
        verify_v23_calibration_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_v23_calibration_run(final)
    return final


def verify_v23_calibration_run(
    run_dir: Path,
    *,
    protocol: FinQAV23PairedCalibrationProtocol | None = None,
) -> FinQAV23CalibrationRunManifest:
    run_dir = run_dir.resolve()
    actual = {path.name for path in run_dir.iterdir() if path.is_file()}
    if actual != {*_ARTIFACTS, "manifest.json"}:
        raise ValueError("v2.3 run has an unexpected artifact set")
    manifest = FinQAV23CalibrationRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if manifest.run_id != run_dir.name and ".staging-" not in run_dir.name:
        raise ValueError("v2.3 run directory does not match manifest")
    for name, digest in manifest.artifacts.items():
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError("v2.3 run artifact hash mismatch")
    rows = [
        FinQAV23CalibrationCase.model_validate(json.loads(line))
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(rows) != 60:
        raise ValueError("v2.3 run row count is invalid")
    if (
        len({row.case_id for row in rows}) != 60
        or case_ids_sha256([row.case_id for row in rows])
        != manifest.selected_case_ids_sha256
    ):
        raise ValueError("v2.3 run case identity is invalid")

    observed_b0 = summarize_arm([row.b0_stored for row in rows])
    observed_v22 = summarize_arm([row.b1_v22_stored for row in rows])
    observed_v23 = summarize_arm([row.b1_v23_intervention for row in rows])
    if (
        observed_b0 != manifest.summary.b0_stored
        or observed_v22 != manifest.summary.b1_v22_stored
        or observed_v23 != manifest.summary.b1_v23_intervention
        or _comparison(
            [row.b1_v22_stored for row in rows],
            [row.b1_v23_intervention for row in rows],
        )
        != manifest.summary.comparison_vs_v22
        or _comparison(
            [row.b0_stored for row in rows],
            [row.b1_v23_intervention for row in rows],
        )
        != manifest.summary.comparison_vs_b0
    ):
        raise ValueError("v2.3 run summary does not match detail rows")

    for check in manifest.summary.gate_checks:
        expected_passed = (
            check.observed >= check.threshold
            if check.comparator == "ge"
            else (
                check.observed <= check.threshold
                if check.comparator == "le"
                else check.observed is True
            )
        )
        if check.passed != expected_passed:
            raise ValueError("v2.3 gate result contradicts its comparator")

    if protocol is not None:
        if (
            manifest.protocol_id != protocol.protocol_id
            or manifest.selected_case_ids_sha256
            != protocol.calibration_case_ids_sha256
            or manifest.answer_model.name != protocol.answer_model_name
            or manifest.answer_model.sha256
            != protocol.answer_model_sha256
        ):
            raise ValueError("v2.3 run does not match the frozen protocol")
        recomputed = summarize_v23_calibration(
            rows,
            protocol=protocol,
            input_gate_e3_passed=manifest.summary.input_gate_e3_passed,
            fail_closed_regression_suite_passed=(
                manifest.summary.fail_closed_regression_suite_passed
            ),
        )
        if recomputed != manifest.summary:
            raise ValueError("v2.3 run summary does not match frozen gates")
    return manifest


__all__ = [
    "RUN_SCHEMA_VERSION",
    "FinQAV23CalibrationCase",
    "FinQAV23CalibrationRunManifest",
    "FinQAV23CalibrationSummary",
    "FinQAV23PairedComparison",
    "publish_v23_calibration_run",
    "summarize_v23_calibration",
    "verify_v23_calibration_run",
]
