from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa_diagnostics import parse_finqa_gold_program
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedRetrospectiveCase,
    canonical_json_bytes,
)


CLAIM_LABEL = "DISCLOSED_DEVELOPMENT_CALIBRATION"
PROTOCOL_SCHEMA_VERSION = "finqa_typed_contract_calibration_protocol_v1"
EVIDENCE_SCHEMA_VERSION = "finqa_typed_contract_failure_matrix_v1"
SPLIT_ALGORITHM_VERSION = "stratified_hash_largest_remainder_v1"
DEFAULT_SPLIT_SEED = "gate-e2-typed-contract-calibration-v1"

CohortName = Literal["calibration", "internal_validation"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalibrationAdoptionGates(_StrictModel):
    min_coverage: float = Field(ge=0, le=1)
    min_execution_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    min_grounded_accuracy_delta_vs_b0: float = Field(ge=-1, le=1)
    max_correct_to_wrong_rate: float = Field(ge=0, le=1)
    min_wrong_to_correct_count: int = Field(ge=0)
    min_prevented_operand_failure_count: int = Field(ge=0)
    max_protocol_error_rate: float = Field(ge=0, le=1)
    max_latency_mean_multiplier: float = Field(ge=1)
    max_latency_p95_ms: float = Field(gt=0)
    require_fail_closed_regression_suite: Literal[True] = True


class CalibrationStratum(_StrictModel):
    diagnostic_category: str = Field(min_length=1, max_length=128)
    b1_v1_outcome: str = Field(min_length=1, max_length=128)
    total_count: int = Field(ge=1)
    calibration_count: int = Field(ge=0)
    internal_validation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count_accounting(self) -> CalibrationStratum:
        if (
            self.calibration_count + self.internal_validation_count
            != self.total_count
        ):
            raise ValueError("calibration stratum counts do not reconcile")
        return self


class CalibrationCohortBaseline(_StrictModel):
    cohort: CohortName
    case_count: int = Field(ge=1)
    b0_answered_count: int = Field(ge=0)
    b0_execution_accuracy: float = Field(ge=0, le=1)
    b0_grounded_accuracy: float = Field(ge=0, le=1)
    b1_v1_answered_count: int = Field(ge=0)
    b1_v1_refusal_count: int = Field(ge=0)
    b1_v1_protocol_error_count: int = Field(ge=0)
    b1_v1_coverage: float = Field(ge=0, le=1)
    b1_v1_execution_accuracy: float = Field(ge=0, le=1)
    b1_v1_grounded_accuracy: float = Field(ge=0, le=1)
    b1_v1_correct_to_wrong_count: int = Field(ge=0)
    b1_v1_wrong_to_correct_count: int = Field(ge=0)
    operand_selection_signal_count: int = Field(ge=0)
    b1_v1_prevented_operand_failure_count: int = Field(ge=0)


class FinQATypedCalibrationProtocol(_StrictModel):
    schema_version: Literal[
        "finqa_typed_contract_calibration_protocol_v1"
    ] = PROTOCOL_SCHEMA_VERSION
    status: Literal["FROZEN_BEFORE_V2_IMPLEMENTATION"]
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    implementation_base_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_gate_e_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    source_gate_e_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_selected_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_algorithm_version: Literal[
        "stratified_hash_largest_remainder_v1"
    ] = SPLIT_ALGORITHM_VERSION
    split_seed: str = Field(min_length=1, max_length=200)
    validation_fraction: float = Field(gt=0, lt=1)
    stratification_fields: tuple[
        Literal["diagnostic_category"],
        Literal["b1_v1_outcome"],
    ]
    calibration_case_count: int = Field(ge=1)
    internal_validation_case_count: int = Field(ge=1)
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    internal_validation_case_ids_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    strata: tuple[CalibrationStratum, ...] = Field(min_length=1)
    adoption_gates: CalibrationAdoptionGates
    immutable_safety_invariants: tuple[str, ...] = Field(min_length=1)
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_protocol_accounting(self) -> FinQATypedCalibrationProtocol:
        if self.stratification_fields != (
            "diagnostic_category",
            "b1_v1_outcome",
        ):
            raise ValueError("calibration stratification fields changed")
        if sum(item.calibration_count for item in self.strata) != (
            self.calibration_case_count
        ):
            raise ValueError("calibration cohort count does not reconcile")
        if sum(item.internal_validation_count for item in self.strata) != (
            self.internal_validation_case_count
        ):
            raise ValueError(
                "internal-validation cohort count does not reconcile"
            )
        return self


class FinQATypedFailureMatrix(_StrictModel):
    schema_version: Literal[
        "finqa_typed_contract_failure_matrix_v1"
    ] = EVIDENCE_SCHEMA_VERSION
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    source_gate_e_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=1)
    b1_v1_failure_reason_counts: dict[str, int]
    gold_operation_sequence_counts: dict[str, int]
    failure_by_gold_operation_sequence: dict[str, dict[str, int]]
    cohort_baselines: dict[CohortName, CalibrationCohortBaseline]
    content_exclusions: tuple[
        Literal["case_ids"],
        Literal["questions"],
        Literal["answers"],
        Literal["evidence_text"],
        Literal["gold_program_text"],
    ]

    @model_validator(mode="after")
    def validate_matrix_accounting(self) -> FinQATypedFailureMatrix:
        if sum(self.b1_v1_failure_reason_counts.values()) != self.case_count:
            raise ValueError("failure-reason counts do not reconcile")
        if sum(self.gold_operation_sequence_counts.values()) != self.case_count:
            raise ValueError("gold-operation counts do not reconcile")
        if set(self.cohort_baselines) != {
            "calibration",
            "internal_validation",
        }:
            raise ValueError("failure matrix is missing a frozen cohort")
        return self


def case_ids_sha256(case_ids: Sequence[str]) -> str:
    normalized = sorted(case_ids)
    if (
        not normalized
        or len(normalized) != len(set(normalized))
        or any(not case_id for case_id in normalized)
    ):
        raise ValueError("case IDs must be non-empty and unique")
    return hashlib.sha256(
        canonical_json_bytes(normalized)
    ).hexdigest()


def _stratum_key(
    row: FinQATypedRetrospectiveCase,
) -> tuple[str, str]:
    return (
        row.diagnostic_category,
        row.b1.failure_reason or "ANSWERED",
    )


def _rank(seed: str, case_id: str) -> str:
    return hashlib.sha256(
        f"{seed}\0{case_id}".encode("utf-8")
    ).hexdigest()


def stratified_calibration_split(
    rows: Sequence[FinQATypedRetrospectiveCase],
    *,
    seed: str = DEFAULT_SPLIT_SEED,
    validation_fraction: float = 0.4,
) -> tuple[
    tuple[FinQATypedRetrospectiveCase, ...],
    tuple[FinQATypedRetrospectiveCase, ...],
    tuple[CalibrationStratum, ...],
]:
    if not rows or not seed or not 0 < validation_fraction < 1:
        raise ValueError("calibration split inputs are invalid")
    ids = [row.case_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("calibration source case IDs must be unique")
    groups: dict[
        tuple[str, str],
        list[FinQATypedRetrospectiveCase],
    ] = defaultdict(list)
    for row in rows:
        groups[_stratum_key(row)].append(row)

    target_validation_count = round(len(rows) * validation_fraction)
    validation_counts: dict[tuple[str, str], int] = {}
    quotas: dict[tuple[str, str], float] = {}
    for key, group in groups.items():
        quota = len(group) * validation_fraction
        quotas[key] = quota
        validation_counts[key] = (
            min(len(group) - 1, max(1, math.floor(quota)))
            if len(group) >= 2
            else 0
        )

    while sum(validation_counts.values()) < target_validation_count:
        eligible = [
            key
            for key, group in groups.items()
            if validation_counts[key] < len(group) - 1
        ]
        if not eligible:
            raise ValueError("cannot satisfy internal-validation target")
        key = min(
            eligible,
            key=lambda item: (
                -(quotas[item] - math.floor(quotas[item])),
                validation_counts[item],
                item,
            ),
        )
        validation_counts[key] += 1

    while sum(validation_counts.values()) > target_validation_count:
        eligible = [
            key
            for key, count in validation_counts.items()
            if count > (1 if len(groups[key]) >= 2 else 0)
        ]
        if not eligible:
            raise ValueError("cannot reduce internal-validation target")
        key = min(
            eligible,
            key=lambda item: (
                quotas[item] - math.floor(quotas[item]),
                -validation_counts[item],
                item,
            ),
        )
        validation_counts[key] -= 1

    calibration: list[FinQATypedRetrospectiveCase] = []
    validation: list[FinQATypedRetrospectiveCase] = []
    strata: list[CalibrationStratum] = []
    for key in sorted(groups):
        ranked = sorted(
            groups[key],
            key=lambda row: (_rank(seed, row.case_id), row.case_id),
        )
        validation_count = validation_counts[key]
        validation.extend(ranked[:validation_count])
        calibration.extend(ranked[validation_count:])
        strata.append(
            CalibrationStratum(
                diagnostic_category=key[0],
                b1_v1_outcome=key[1],
                total_count=len(ranked),
                calibration_count=len(ranked) - validation_count,
                internal_validation_count=validation_count,
            )
        )
    calibration.sort(key=lambda row: row.case_id)
    validation.sort(key=lambda row: row.case_id)
    return tuple(calibration), tuple(validation), tuple(strata)


def cohort_baseline(
    rows: Sequence[FinQATypedRetrospectiveCase],
    *,
    cohort: CohortName,
) -> CalibrationCohortBaseline:
    if not rows:
        raise ValueError("calibration cohort cannot be empty")
    count = len(rows)
    b0_correct = sum(row.b0.strict_execution_match for row in rows)
    b0_grounded = sum(row.b0.grounded_execution_match for row in rows)
    b1_answered = sum(row.b1.status == "ANSWERED" for row in rows)
    b1_refused = sum(row.b1.status == "REFUSED" for row in rows)
    b1_protocol = sum(row.b1.status == "PROTOCOL_ERROR" for row in rows)
    b1_correct = sum(row.b1.strict_execution_match for row in rows)
    b1_grounded = sum(row.b1.grounded_execution_match for row in rows)
    operand_rows = [
        row
        for row in rows
        if row.diagnostic_category == "operand_selection_signal"
    ]
    return CalibrationCohortBaseline(
        cohort=cohort,
        case_count=count,
        b0_answered_count=sum(row.b0.status == "ANSWERED" for row in rows),
        b0_execution_accuracy=b0_correct / count,
        b0_grounded_accuracy=b0_grounded / count,
        b1_v1_answered_count=b1_answered,
        b1_v1_refusal_count=b1_refused,
        b1_v1_protocol_error_count=b1_protocol,
        b1_v1_coverage=b1_answered / count,
        b1_v1_execution_accuracy=b1_correct / count,
        b1_v1_grounded_accuracy=b1_grounded / count,
        b1_v1_correct_to_wrong_count=sum(
            row.b0.strict_execution_match
            and not row.b1.strict_execution_match
            for row in rows
        ),
        b1_v1_wrong_to_correct_count=sum(
            not row.b0.strict_execution_match
            and row.b1.strict_execution_match
            for row in rows
        ),
        operand_selection_signal_count=len(operand_rows),
        b1_v1_prevented_operand_failure_count=sum(
            row.b1.strict_execution_match for row in operand_rows
        ),
    )


def build_failure_matrix(
    *,
    rows: Sequence[FinQATypedRetrospectiveCase],
    gold_program_by_case_id: Mapping[str, str],
    calibration_rows: Sequence[FinQATypedRetrospectiveCase],
    validation_rows: Sequence[FinQATypedRetrospectiveCase],
    protocol: FinQATypedCalibrationProtocol,
) -> FinQATypedFailureMatrix:
    if set(gold_program_by_case_id) != {row.case_id for row in rows}:
        raise ValueError("gold-program mapping does not match the source cohort")
    failure_counts: Counter[str] = Counter()
    sequence_counts: Counter[str] = Counter()
    cross: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        failure = row.b1.failure_reason or "ANSWERED"
        sequence = ">".join(
            parse_finqa_gold_program(
                gold_program_by_case_id[row.case_id]
            ).operations
        )
        failure_counts[failure] += 1
        sequence_counts[sequence] += 1
        cross[failure][sequence] += 1
    protocol_sha256 = hashlib.sha256(
        canonical_json_bytes(protocol.model_dump(mode="json"))
    ).hexdigest()
    return FinQATypedFailureMatrix(
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e_run_id=protocol.source_gate_e_run_id,
        source_gate_e_details_sha256=(
            protocol.source_gate_e_details_sha256
        ),
        case_count=len(rows),
        b1_v1_failure_reason_counts=dict(sorted(failure_counts.items())),
        gold_operation_sequence_counts=dict(sorted(sequence_counts.items())),
        failure_by_gold_operation_sequence={
            reason: dict(sorted(counts.items()))
            for reason, counts in sorted(cross.items())
        },
        cohort_baselines={
            "calibration": cohort_baseline(
                calibration_rows,
                cohort="calibration",
            ),
            "internal_validation": cohort_baseline(
                validation_rows,
                cohort="internal_validation",
            ),
        },
        content_exclusions=(
            "case_ids",
            "questions",
            "answers",
            "evidence_text",
            "gold_program_text",
        ),
    )


__all__ = [
    "CLAIM_LABEL",
    "DEFAULT_SPLIT_SEED",
    "EVIDENCE_SCHEMA_VERSION",
    "PROTOCOL_SCHEMA_VERSION",
    "SPLIT_ALGORITHM_VERSION",
    "CalibrationAdoptionGates",
    "CalibrationCohortBaseline",
    "CalibrationStratum",
    "FinQATypedCalibrationProtocol",
    "FinQATypedFailureMatrix",
    "build_failure_matrix",
    "case_ids_sha256",
    "cohort_baseline",
    "stratified_calibration_split",
]
