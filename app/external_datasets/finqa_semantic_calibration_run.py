from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.external_datasets.finqa_semantic_planning_protocol import (
    FinQASemanticPlanningCalibrationProtocol,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationArmSummary,
    FinQATypedCalibrationGateCheck,
    summarize_arm,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FrozenModelIdentity,
    canonical_json_bytes,
)
from app.filesystem import atomic_directory_move


RUN_SCHEMA_VERSION = "finqa_semantic_planning_calibration_run_v1"
_ARTIFACTS = {"details.jsonl", "summary.json"}
SemanticInterventionArmId: TypeAlias = Literal[
    "B2_MULTI_STEP_DIRECT",
    "B3_ROLE_DECOMPOSED",
    "B4_ROLE_DYNAMIC_DEMOS",
]
_INTERVENTION_ARMS: tuple[SemanticInterventionArmId, ...] = (
    "B2_MULTI_STEP_DIRECT",
    "B3_ROLE_DECOMPOSED",
    "B4_ROLE_DYNAMIC_DEMOS",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinQASemanticPlanningCase(_StrictModel):
    case_id: str = Field(min_length=1)
    diagnostic_category: str = Field(min_length=1, max_length=128)
    selected_unit_ids: tuple[str, ...] = Field(min_length=1)
    admitted_closure_unit_ids: tuple[str, ...] = Field(min_length=1)
    gold_unit_ids: tuple[str, ...] = Field(min_length=1)
    candidate_count_before_shortlist: int = Field(ge=0, le=128)
    candidate_count_after_shortlist: int = Field(ge=0, le=24)
    guard_scan_count: int = Field(ge=1, le=32)
    quarantined_unit_count: int = Field(ge=0, le=32)
    arm_order: tuple[
        SemanticInterventionArmId,
        SemanticInterventionArmId,
        SemanticInterventionArmId,
    ]
    b4_demo_count: int = Field(ge=0, le=3)
    b4_demo_payload_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    b0_stored: FinQATypedArmEvaluation
    b1_v23_stored: FinQATypedArmEvaluation
    b2_direct: FinQATypedArmEvaluation
    b3_roles: FinQATypedArmEvaluation
    b4_dynamic_demos: FinQATypedArmEvaluation

    @model_validator(mode="after")
    def validate_contract(self) -> FinQASemanticPlanningCase:
        if set(self.arm_order) != set(_INTERVENTION_ARMS):
            raise ValueError("semantic planning arm order is invalid")
        if (
            self.b0_stored.arm_id != "B0_FREE_LITERAL"
            or self.b1_v23_stored.arm_id != "B1_TYPED_SINGLE"
            or any(
                arm.arm_id != "B2_TYPED_MULTI"
                for arm in (
                    self.b2_direct,
                    self.b3_roles,
                    self.b4_dynamic_demos,
                )
            )
        ):
            raise ValueError("semantic planning arm identity is invalid")
        if self.guard_scan_count < len(self.admitted_closure_unit_ids):
            raise ValueError("semantic planning scan accounting is invalid")
        if (self.b4_demo_count == 0) != (
            self.b4_demo_payload_sha256 is None
        ):
            raise ValueError("dynamic demo identity accounting is invalid")
        return self


class FinQASemanticPairedComparison(_StrictModel):
    case_count: Literal[60] = 60
    execution_accuracy_delta: float = Field(ge=-1, le=1)
    grounded_accuracy_delta: float = Field(ge=-1, le=1)
    correct_to_wrong_count: int = Field(ge=0, le=60)
    correct_to_wrong_rate: float = Field(ge=0, le=1)
    wrong_to_correct_count: int = Field(ge=0, le=60)


class FinQASemanticCandidateSummary(_StrictModel):
    arm_id: SemanticInterventionArmId
    metrics: FinQATypedCalibrationArmSummary
    comparison_vs_v23: FinQASemanticPairedComparison
    comparison_vs_b0: FinQASemanticPairedComparison
    latency_mean_multiplier_vs_v23: float = Field(ge=0)
    gate_checks: tuple[FinQATypedCalibrationGateCheck, ...]
    eligible: bool

    @model_validator(mode="after")
    def validate_eligibility(self) -> FinQASemanticCandidateSummary:
        if self.eligible != bool(
            self.gate_checks
            and all(check.passed for check in self.gate_checks)
        ):
            raise ValueError("semantic candidate eligibility is inconsistent")
        return self


class FinQASemanticCalibrationSummary(_StrictModel):
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    case_count: Literal[60] = 60
    b0_stored: FinQATypedCalibrationArmSummary
    b1_v23_stored: FinQATypedCalibrationArmSummary
    candidates: dict[
        SemanticInterventionArmId,
        FinQASemanticCandidateSummary,
    ]
    demo_isolation_suite_passed: bool
    fail_closed_regression_suite_passed: bool
    selected_arm: SemanticInterventionArmId | None
    decision: Literal[
        "ELIGIBLE_FOR_INTERNAL_VALIDATION",
        "CALIBRATION_REJECTED",
    ]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]

    @model_validator(mode="after")
    def validate_decision(self) -> FinQASemanticCalibrationSummary:
        if set(self.candidates) != set(_INTERVENTION_ARMS) or any(
            key != value.arm_id for key, value in self.candidates.items()
        ):
            raise ValueError("semantic candidate summary set is invalid")
        eligible = {
            arm_id
            for arm_id, result in self.candidates.items()
            if result.eligible
        }
        if self.selected_arm not in eligible and self.selected_arm is not None:
            raise ValueError("selected semantic arm is not eligible")
        expected = (
            "ELIGIBLE_FOR_INTERNAL_VALIDATION"
            if self.selected_arm is not None
            else "CALIBRATION_REJECTED"
        )
        if self.decision != expected:
            raise ValueError("semantic calibration decision is inconsistent")
        return self


class FinQASemanticCalibrationManifest(_StrictModel):
    schema_version: Literal[
        "finqa_semantic_planning_calibration_run_v1"
    ] = RUN_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e4_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e4_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demo_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    demo_index_count: int = Field(ge=100)
    answer_model: FrozenModelIdentity
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_file_sha256: dict[str, str] = Field(min_length=1)
    planner_version: str = Field(min_length=1)
    demo_retriever_version: str = Field(min_length=1)
    validator_version: str = Field(min_length=1)
    compiler_version: str = Field(min_length=1)
    timeout_seconds_per_call: float = Field(gt=0, le=300)
    max_attempts_per_stage: int = Field(ge=1, le=2)
    summary: FinQASemanticCalibrationSummary
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
            raise ValueError("semantic calibration hash map is invalid")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def validate_artifacts(self) -> FinQASemanticCalibrationManifest:
        if self.artifacts and set(self.artifacts) != _ARTIFACTS:
            raise ValueError("semantic calibration artifact set is invalid")
        return self


def semantic_arm_order(
    index: int,
) -> tuple[
    SemanticInterventionArmId,
    SemanticInterventionArmId,
    SemanticInterventionArmId,
]:
    offset = index % len(_INTERVENTION_ARMS)
    return (
        *_INTERVENTION_ARMS[offset:],
        *_INTERVENTION_ARMS[:offset],
    )


def _comparison(
    baseline: Sequence[FinQATypedArmEvaluation],
    intervention: Sequence[FinQATypedArmEvaluation],
) -> FinQASemanticPairedComparison:
    if len(baseline) != 60 or len(intervention) != 60:
        raise ValueError("semantic paired comparison requires 60 cases")
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
    return FinQASemanticPairedComparison(
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


def _candidate_summary(
    *,
    arm_id: SemanticInterventionArmId,
    baseline_v23: Sequence[FinQATypedArmEvaluation],
    baseline_b0: Sequence[FinQATypedArmEvaluation],
    intervention: Sequence[FinQATypedArmEvaluation],
    protocol: FinQASemanticPlanningCalibrationProtocol,
    demo_isolation_suite_passed: bool,
    fail_closed_regression_suite_passed: bool,
) -> FinQASemanticCandidateSummary:
    v23 = summarize_arm(baseline_v23)
    metrics = summarize_arm(intervention)
    vs_v23 = _comparison(baseline_v23, intervention)
    vs_b0 = _comparison(baseline_b0, intervention)
    latency_multiplier = (
        metrics.latency_ms_mean / v23.latency_ms_mean
        if v23.latency_ms_mean > 0
        else 0.0
    )
    progress = protocol.progress_gates
    shadow = protocol.adoption_shadow_gates
    checks = (
        _check("coverage", "ge", metrics.coverage, progress.min_coverage),
        _check(
            "execution_accuracy_delta_vs_v23",
            "ge",
            vs_v23.execution_accuracy_delta,
            progress.min_execution_accuracy_delta_vs_v23,
        ),
        _check(
            "grounded_accuracy_delta_vs_v23",
            "ge",
            vs_v23.grounded_accuracy_delta,
            progress.min_grounded_accuracy_delta_vs_v23,
        ),
        _check(
            "correct_to_wrong_rate_vs_v23",
            "le",
            vs_v23.correct_to_wrong_rate,
            progress.max_correct_to_wrong_rate_vs_v23,
        ),
        _check(
            "wrong_to_correct_count_vs_v23",
            "ge",
            float(vs_v23.wrong_to_correct_count),
            float(progress.min_wrong_to_correct_count_vs_v23),
        ),
        _check(
            "protocol_error_rate",
            "le",
            metrics.protocol_error_count / 60,
            progress.max_protocol_error_rate,
        ),
        _check(
            "latency_mean_multiplier_vs_v23",
            "le",
            latency_multiplier,
            progress.max_latency_mean_multiplier_vs_v23,
        ),
        _check(
            "latency_p95_ms",
            "le",
            metrics.latency_ms_p95,
            progress.max_latency_p95_ms,
        ),
        _check(
            "demo_isolation_suite",
            "required",
            demo_isolation_suite_passed,
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
    return FinQASemanticCandidateSummary(
        arm_id=arm_id,
        metrics=metrics,
        comparison_vs_v23=vs_v23,
        comparison_vs_b0=vs_b0,
        latency_mean_multiplier_vs_v23=latency_multiplier,
        gate_checks=checks,
        eligible=all(check.passed for check in checks),
    )


def summarize_semantic_calibration(
    rows: Sequence[FinQASemanticPlanningCase],
    *,
    protocol: FinQASemanticPlanningCalibrationProtocol,
    demo_isolation_suite_passed: bool,
    fail_closed_regression_suite_passed: bool,
) -> FinQASemanticCalibrationSummary:
    if len(rows) != 60 or len({row.case_id for row in rows}) != 60:
        raise ValueError("semantic calibration requires 60 unique cases")
    b0 = [row.b0_stored for row in rows]
    v23 = [row.b1_v23_stored for row in rows]
    interventions = {
        "B2_MULTI_STEP_DIRECT": [row.b2_direct for row in rows],
        "B3_ROLE_DECOMPOSED": [row.b3_roles for row in rows],
        "B4_ROLE_DYNAMIC_DEMOS": [row.b4_dynamic_demos for row in rows],
    }
    candidates = {
        arm_id: _candidate_summary(
            arm_id=arm_id,
            baseline_v23=v23,
            baseline_b0=b0,
            intervention=arms,
            protocol=protocol,
            demo_isolation_suite_passed=demo_isolation_suite_passed,
            fail_closed_regression_suite_passed=(
                fail_closed_regression_suite_passed
            ),
        )
        for arm_id, arms in interventions.items()
    }
    eligible = [
        result for result in candidates.values() if result.eligible
    ]
    selected = (
        max(
            eligible,
            key=lambda result: (
                result.metrics.execution_accuracy,
                result.metrics.grounded_execution_accuracy,
                result.metrics.coverage,
                -(result.metrics.protocol_error_count / 60),
                -result.metrics.latency_ms_mean,
                result.arm_id,
            ),
        ).arm_id
        if eligible
        else None
    )
    return FinQASemanticCalibrationSummary(
        claim_label=protocol.claim_label,
        b0_stored=summarize_arm(b0),
        b1_v23_stored=summarize_arm(v23),
        candidates=candidates,
        demo_isolation_suite_passed=demo_isolation_suite_passed,
        fail_closed_regression_suite_passed=(
            fail_closed_regression_suite_passed
        ),
        selected_arm=selected,
        decision=(
            "ELIGIBLE_FOR_INTERNAL_VALIDATION"
            if selected is not None
            else "CALIBRATION_REJECTED"
        ),
        internal_validation_status="NOT_RUN",
        frozen_test_status="UNTOUCHED",
    )


def publish_semantic_calibration_run(
    *,
    root: Path,
    manifest: FinQASemanticCalibrationManifest,
    details: Sequence[FinQASemanticPlanningCase],
) -> Path:
    root = root.resolve()
    final = root / manifest.run_id
    if final.exists():
        raise FileExistsError("semantic calibration run already exists")
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
        verify_semantic_calibration_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_semantic_calibration_run(final)
    return final


def verify_semantic_calibration_run(
    run_dir: Path,
    *,
    protocol: FinQASemanticPlanningCalibrationProtocol | None = None,
    protocol_sha256: str | None = None,
) -> FinQASemanticCalibrationManifest:
    run_dir = run_dir.resolve()
    actual = {path.name for path in run_dir.iterdir() if path.is_file()}
    if actual != {*_ARTIFACTS, "manifest.json"}:
        raise ValueError("semantic calibration artifact set is invalid")
    manifest = FinQASemanticCalibrationManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if manifest.run_id != run_dir.name and ".staging-" not in run_dir.name:
        raise ValueError("semantic calibration directory is invalid")
    for name, digest in manifest.artifacts.items():
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError("semantic calibration artifact hash mismatch")
    rows = [
        FinQASemanticPlanningCase.model_validate_json(line)
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if (
        len(rows) != 60
        or len({row.case_id for row in rows}) != 60
        or case_ids_sha256([row.case_id for row in rows])
        != manifest.selected_case_ids_sha256
    ):
        raise ValueError("semantic calibration case identity is invalid")
    if protocol is not None:
        if protocol_sha256 is None:
            raise ValueError("frozen protocol SHA-256 is required")
        if (
            manifest.protocol_id != protocol.protocol_id
            or manifest.protocol_sha256
            != protocol_sha256
            or manifest.selected_case_ids_sha256
            != protocol.calibration_case_ids_sha256
            or manifest.answer_model.name != protocol.answer_model_name
            or manifest.answer_model.sha256
            != protocol.answer_model_sha256
        ):
            raise ValueError("semantic run does not match frozen protocol")
        recomputed = summarize_semantic_calibration(
            rows,
            protocol=protocol,
            demo_isolation_suite_passed=(
                manifest.summary.demo_isolation_suite_passed
            ),
            fail_closed_regression_suite_passed=(
                manifest.summary.fail_closed_regression_suite_passed
            ),
        )
        if recomputed != manifest.summary:
            raise ValueError("semantic summary contradicts frozen gates")
    else:
        for candidate in manifest.summary.candidates.values():
            for check in candidate.gate_checks:
                expected = (
                    check.observed >= check.threshold
                    if check.comparator == "ge"
                    else (
                        check.observed <= check.threshold
                        if check.comparator == "le"
                        else check.observed is True
                    )
                )
                if check.passed != expected:
                    raise ValueError("semantic gate comparator is inconsistent")
    return manifest


__all__ = [
    "RUN_SCHEMA_VERSION",
    "FinQASemanticCalibrationManifest",
    "FinQASemanticCalibrationSummary",
    "FinQASemanticCandidateSummary",
    "FinQASemanticPairedComparison",
    "FinQASemanticPlanningCase",
    "SemanticInterventionArmId",
    "publish_semantic_calibration_run",
    "semantic_arm_order",
    "summarize_semantic_calibration",
    "verify_semantic_calibration_run",
]
