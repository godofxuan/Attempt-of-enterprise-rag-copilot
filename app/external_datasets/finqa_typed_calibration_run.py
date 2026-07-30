from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.external_datasets.finqa_typed_calibration import (
    CLAIM_LABEL,
    CalibrationAdoptionGates,
    CohortName,
    FinQATypedCalibrationProtocol,
    case_ids_sha256,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    FrozenModelIdentity,
    canonical_json_bytes,
)
from app.filesystem import atomic_directory_move


RUN_SCHEMA_VERSION = "finqa_typed_contract_calibration_run_v1"
_ARTIFACTS = {"details.jsonl", "summary.json"}
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinQATypedCalibrationRunCase(_StrictModel):
    case_id: str = Field(min_length=1)
    cohort: CohortName
    diagnostic_category: str = Field(min_length=1, max_length=128)
    selected_unit_ids: list[str] = Field(min_length=1)
    gold_unit_ids: list[str] = Field(min_length=1)
    b0: FinQATypedArmEvaluation
    b1_v1: FinQATypedArmEvaluation
    b1_v2: FinQATypedArmEvaluation

    @model_validator(mode="after")
    def validate_arms(self) -> FinQATypedCalibrationRunCase:
        if (
            self.b0.arm_id != "B0_FREE_LITERAL"
            or self.b1_v1.arm_id != "B1_TYPED_SINGLE"
            or self.b1_v2.arm_id != "B1_TYPED_SINGLE"
        ):
            raise ValueError("calibration run arm identity is invalid")
        return self


class FinQATypedCalibrationArmSummary(_StrictModel):
    case_count: int = Field(ge=1)
    answered_count: int = Field(ge=0)
    refusal_count: int = Field(ge=0)
    protocol_error_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    execution_accuracy: float = Field(ge=0, le=1)
    grounded_execution_accuracy: float = Field(ge=0, le=1)
    citation_precision_mean: float = Field(ge=0, le=1)
    citation_recall_mean: float = Field(ge=0, le=1)
    generation_calls: int = Field(ge=0)
    compiler_calls: int = Field(ge=0)
    latency_ms_mean: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    failure_reason_counts: dict[str, int]


class FinQATypedCalibrationComparison(_StrictModel):
    case_count: int = Field(ge=1)
    execution_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    grounded_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    correct_to_wrong_count: int = Field(ge=0)
    correct_to_wrong_rate: float = Field(ge=0, le=1)
    wrong_to_correct_count: int = Field(ge=0)
    prevented_operand_failure_count: int = Field(ge=0)
    latency_mean_multiplier_vs_b0: float | None = Field(default=None, ge=0)


class FinQATypedCalibrationGateCheck(_StrictModel):
    gate: str = Field(min_length=1, max_length=128)
    comparator: Literal["ge", "le", "required"]
    observed: float | bool
    threshold: float | bool
    passed: bool


class FinQATypedCalibrationRunSummary(_StrictModel):
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    cohort: CohortName
    case_count: int = Field(ge=1)
    b0: FinQATypedCalibrationArmSummary
    b1_v1: FinQATypedCalibrationArmSummary
    b1_v2: FinQATypedCalibrationArmSummary
    comparison: FinQATypedCalibrationComparison
    gate_checks: tuple[FinQATypedCalibrationGateCheck, ...]
    gate_status: Literal[
        "CALIBRATION_ONLY",
        "ADOPTION_GATE_PASSED",
        "ADOPTION_GATE_FAILED",
    ]

    @model_validator(mode="after")
    def validate_summary(self) -> FinQATypedCalibrationRunSummary:
        if any(
            arm.case_count != self.case_count
            for arm in (self.b0, self.b1_v1, self.b1_v2)
        ):
            raise ValueError("calibration arm case counts do not reconcile")
        if self.cohort == "calibration" and (
            self.gate_checks or self.gate_status != "CALIBRATION_ONLY"
        ):
            raise ValueError("calibration cohort cannot make adoption claims")
        if self.cohort == "internal_validation" and not self.gate_checks:
            raise ValueError("internal validation requires adoption checks")
        return self


class FinQATypedCalibrationRunManifest(_StrictModel):
    schema_version: Literal[
        "finqa_typed_contract_calibration_run_v1"
    ] = RUN_SCHEMA_VERSION
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_gate_e_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    source_gate_e_details_sha256: str = Field(pattern=_SHA256_PATTERN)
    cohort: CohortName
    selected_case_count: int = Field(ge=1)
    selected_case_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    answer_model: FrozenModelIdentity
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_file_sha256: dict[str, str] = Field(min_length=1)
    intent_version: str = Field(min_length=1, max_length=200)
    validator_version: str = Field(min_length=1, max_length=200)
    compiler_version: str = Field(min_length=1, max_length=200)
    planner_version: str = Field(min_length=1, max_length=200)
    timeout_seconds: float = Field(gt=0, le=300)
    max_attempts: int = Field(ge=1, le=3)
    adoption_gates: CalibrationAdoptionGates
    fail_closed_regression_suite_passed: bool
    summary: FinQATypedCalibrationRunSummary
    artifacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("implementation_file_sha256")
    @classmethod
    def validate_implementation_hashes(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        if any(
            not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for path, digest in value.items()
        ):
            raise ValueError("implementation source hash map is invalid")
        return dict(sorted(value.items()))

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, value: dict[str, str]) -> dict[str, str]:
        if value and (
            set(value) != _ARTIFACTS
            or any(
                len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                for digest in value.values()
            )
        ):
            raise ValueError("calibration run artifact set is invalid")
        return value


def _percentile_95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def summarize_arm(
    arms: Sequence[FinQATypedArmEvaluation],
) -> FinQATypedCalibrationArmSummary:
    if not arms:
        raise ValueError("cannot summarize an empty calibration arm")
    count = len(arms)
    failures = Counter(
        arm.failure_reason
        for arm in arms
        if arm.failure_reason is not None
    )
    return FinQATypedCalibrationArmSummary(
        case_count=count,
        answered_count=sum(arm.status == "ANSWERED" for arm in arms),
        refusal_count=sum(arm.status == "REFUSED" for arm in arms),
        protocol_error_count=sum(
            arm.status == "PROTOCOL_ERROR" for arm in arms
        ),
        coverage=sum(arm.status == "ANSWERED" for arm in arms) / count,
        execution_accuracy=sum(
            arm.strict_execution_match for arm in arms
        )
        / count,
        grounded_execution_accuracy=sum(
            arm.grounded_execution_match for arm in arms
        )
        / count,
        citation_precision_mean=sum(
            arm.citation_precision for arm in arms
        )
        / count,
        citation_recall_mean=sum(arm.citation_recall for arm in arms) / count,
        generation_calls=sum(arm.generation_calls for arm in arms),
        compiler_calls=sum(arm.compiler_calls for arm in arms),
        latency_ms_mean=sum(arm.latency_ms for arm in arms) / count,
        latency_ms_p95=_percentile_95([arm.latency_ms for arm in arms]),
        failure_reason_counts=dict(sorted(failures.items())),
    )


def _gate_check(
    gate: str,
    comparator: Literal["ge", "le"],
    observed: float,
    threshold: float,
) -> FinQATypedCalibrationGateCheck:
    passed = observed >= threshold if comparator == "ge" else observed <= threshold
    return FinQATypedCalibrationGateCheck(
        gate=gate,
        comparator=comparator,
        observed=observed,
        threshold=threshold,
        passed=passed,
    )


def summarize_calibration_run(
    rows: Sequence[FinQATypedCalibrationRunCase],
    *,
    cohort: CohortName,
    adoption_gates: CalibrationAdoptionGates,
    fail_closed_regression_suite_passed: bool = False,
) -> FinQATypedCalibrationRunSummary:
    if not rows or any(row.cohort != cohort for row in rows):
        raise ValueError("calibration run cohort is empty or inconsistent")
    b0 = summarize_arm([row.b0 for row in rows])
    b1_v1 = summarize_arm([row.b1_v1 for row in rows])
    b1_v2 = summarize_arm([row.b1_v2 for row in rows])
    count = len(rows)
    correct_to_wrong = sum(
        row.b0.strict_execution_match
        and not row.b1_v2.strict_execution_match
        for row in rows
    )
    wrong_to_correct = sum(
        not row.b0.strict_execution_match
        and row.b1_v2.strict_execution_match
        for row in rows
    )
    prevented_operand = sum(
        row.diagnostic_category == "operand_selection_signal"
        and not row.b0.strict_execution_match
        and row.b1_v2.strict_execution_match
        for row in rows
    )
    latency_multiplier = (
        b1_v2.latency_ms_mean / b0.latency_ms_mean
        if b0.latency_ms_mean > 0
        else None
    )
    comparison = FinQATypedCalibrationComparison(
        case_count=count,
        execution_accuracy_delta_vs_b0=(
            b1_v2.execution_accuracy - b0.execution_accuracy
        ),
        grounded_accuracy_delta_vs_b0=(
            b1_v2.grounded_execution_accuracy
            - b0.grounded_execution_accuracy
        ),
        correct_to_wrong_count=correct_to_wrong,
        correct_to_wrong_rate=correct_to_wrong / count,
        wrong_to_correct_count=wrong_to_correct,
        prevented_operand_failure_count=prevented_operand,
        latency_mean_multiplier_vs_b0=latency_multiplier,
    )
    checks: tuple[FinQATypedCalibrationGateCheck, ...] = ()
    status: Literal[
        "CALIBRATION_ONLY",
        "ADOPTION_GATE_PASSED",
        "ADOPTION_GATE_FAILED",
    ] = "CALIBRATION_ONLY"
    if cohort == "internal_validation":
        checks = (
            _gate_check(
                "coverage",
                "ge",
                b1_v2.coverage,
                adoption_gates.min_coverage,
            ),
            _gate_check(
                "execution_accuracy_delta_vs_b0",
                "ge",
                comparison.execution_accuracy_delta_vs_b0,
                adoption_gates.min_execution_accuracy_delta_vs_b0,
            ),
            _gate_check(
                "grounded_accuracy_delta_vs_b0",
                "ge",
                comparison.grounded_accuracy_delta_vs_b0,
                adoption_gates.min_grounded_accuracy_delta_vs_b0,
            ),
            _gate_check(
                "correct_to_wrong_rate",
                "le",
                comparison.correct_to_wrong_rate,
                adoption_gates.max_correct_to_wrong_rate,
            ),
            _gate_check(
                "wrong_to_correct_count",
                "ge",
                float(comparison.wrong_to_correct_count),
                float(adoption_gates.min_wrong_to_correct_count),
            ),
            _gate_check(
                "prevented_operand_failure_count",
                "ge",
                float(comparison.prevented_operand_failure_count),
                float(adoption_gates.min_prevented_operand_failure_count),
            ),
            _gate_check(
                "protocol_error_rate",
                "le",
                b1_v2.protocol_error_count / count,
                adoption_gates.max_protocol_error_rate,
            ),
            _gate_check(
                "latency_mean_multiplier",
                "le",
                latency_multiplier if latency_multiplier is not None else math.inf,
                adoption_gates.max_latency_mean_multiplier,
            ),
            _gate_check(
                "latency_p95_ms",
                "le",
                b1_v2.latency_ms_p95,
                adoption_gates.max_latency_p95_ms,
            ),
            FinQATypedCalibrationGateCheck(
                gate="fail_closed_regression_suite",
                comparator="required",
                observed=fail_closed_regression_suite_passed,
                threshold=True,
                passed=fail_closed_regression_suite_passed,
            ),
        )
        status = (
            "ADOPTION_GATE_PASSED"
            if all(check.passed for check in checks)
            else "ADOPTION_GATE_FAILED"
        )
    return FinQATypedCalibrationRunSummary(
        cohort=cohort,
        case_count=count,
        b0=b0,
        b1_v1=b1_v1,
        b1_v2=b1_v2,
        comparison=comparison,
        gate_checks=checks,
        gate_status=status,
    )


def publish_calibration_run(
    *,
    root: Path,
    manifest: FinQATypedCalibrationRunManifest,
    details: Sequence[FinQATypedCalibrationRunCase],
) -> Path:
    root = Path(root).resolve()
    final = root / manifest.run_id
    if final.exists():
        raise ValueError("calibration run already exists")
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
        payloads = {
            "details.jsonl": details_bytes,
            "summary.json": summary_bytes,
        }
        artifacts = {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in payloads.items()
        }
        final_manifest = manifest.model_copy(update={"artifacts": artifacts})
        for name, payload in payloads.items():
            (staging / name).write_bytes(payload)
        (staging / "manifest.json").write_bytes(
            canonical_json_bytes(
                final_manifest.model_dump(mode="json"),
                newline=True,
            )
        )
        verify_calibration_run(staging)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_calibration_run(final)
    return final


def verify_calibration_run(
    run_dir: Path,
) -> FinQATypedCalibrationRunManifest:
    run_dir = Path(run_dir).resolve()
    expected = {*_ARTIFACTS, "manifest.json"}
    actual = {path.name for path in run_dir.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError("calibration run has an unexpected artifact set")
    manifest = FinQATypedCalibrationRunManifest.model_validate_json(
        (run_dir / "manifest.json").read_bytes()
    )
    if manifest.run_id != run_dir.name and ".staging-" not in run_dir.name:
        raise ValueError("calibration run directory does not match manifest")
    for name, digest in manifest.artifacts.items():
        if hashlib.sha256((run_dir / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"calibration run artifact mismatch: {name}")
    rows = [
        FinQATypedCalibrationRunCase.model_validate(json.loads(line))
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    reproduced = summarize_calibration_run(
        rows,
        cohort=manifest.cohort,
        adoption_gates=manifest.adoption_gates,
        fail_closed_regression_suite_passed=(
            manifest.fail_closed_regression_suite_passed
        ),
    )
    if (
        len(rows) != manifest.selected_case_count
        or case_ids_sha256([row.case_id for row in rows])
        != manifest.selected_case_ids_sha256
        or reproduced != manifest.summary
    ):
        raise ValueError("calibration run summary cannot be reproduced")
    return manifest


__all__ = [
    "RUN_SCHEMA_VERSION",
    "FinQATypedCalibrationArmSummary",
    "FinQATypedCalibrationComparison",
    "FinQATypedCalibrationGateCheck",
    "FinQATypedCalibrationRunCase",
    "FinQATypedCalibrationRunManifest",
    "FinQATypedCalibrationRunSummary",
    "publish_calibration_run",
    "summarize_arm",
    "summarize_calibration_run",
    "verify_calibration_run",
]
