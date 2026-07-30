from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import (
    FinQACase,
    build_finqa_evidence_units,
)
from app.external_datasets.finqa_diagnostics import parse_finqa_gold_program
from app.external_datasets.finqa_typed_calibration import (
    CLAIM_LABEL,
    FinQATypedCalibrationProtocol,
)
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
    FinQATypedCalibrationRunManifest,
    FinQATypedCalibrationRunSummary,
    verify_calibration_run,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
    question_conditioned_candidate_shortlist_v2,
)
from app.external_datasets.finqa_typed_program import (
    extract_finqa_numeric_candidates,
)
from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from app.security.retrieved_content import RetrievedContentGuard


PUBLIC_SCHEMA_VERSION = "finqa_typed_contract_calibration_public_v1"
IterationId = Literal["v2", "v2_1", "v2_2"]
ShadowGateMetric = Literal[
    "coverage",
    "execution_accuracy_delta_vs_b0",
    "grounded_accuracy_delta_vs_b0",
    "correct_to_wrong_rate",
    "wrong_to_correct_count",
    "prevented_operand_failure_count",
    "protocol_error_rate",
    "latency_mean_multiplier",
    "latency_p95_ms",
]
SHADOW_GATE_METRICS: tuple[ShadowGateMetric, ...] = (
    "coverage",
    "execution_accuracy_delta_vs_b0",
    "grounded_accuracy_delta_vs_b0",
    "correct_to_wrong_rate",
    "wrong_to_correct_count",
    "prevented_operand_failure_count",
    "protocol_error_rate",
    "latency_mean_multiplier",
    "latency_p95_ms",
)
_LESS_THAN_OR_EQUAL_GATES = {
    "correct_to_wrong_rate",
    "protocol_error_rate",
    "latency_mean_multiplier",
    "latency_p95_ms",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CalibrationIterationEvidence(_StrictModel):
    iteration_id: IterationId
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    private_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    private_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_file_sha256: dict[str, str]
    intent_version: str
    validator_version: str
    compiler_version: str
    planner_version: str
    summary: FinQATypedCalibrationRunSummary


class CalibrationIterationTransition(_StrictModel):
    source_iteration: IterationId
    target_iteration: IterationId
    case_count: int = Field(ge=1)
    correct_to_wrong_count: int = Field(ge=0)
    wrong_to_correct_count: int = Field(ge=0)
    both_correct_count: int = Field(ge=0)
    both_wrong_count: int = Field(ge=0)
    answered_to_nonanswer_count: int = Field(ge=0)
    nonanswer_to_answered_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_correctness_accounting(
        self,
    ) -> CalibrationIterationTransition:
        if (
            self.correct_to_wrong_count
            + self.wrong_to_correct_count
            + self.both_correct_count
            + self.both_wrong_count
            != self.case_count
        ):
            raise ValueError("iteration correctness transitions do not reconcile")
        return self


class CandidateShortlistAudit(_StrictModel):
    case_count: int = Field(ge=1)
    mean_candidate_count_before: float = Field(ge=0)
    mean_candidate_count_after: float = Field(ge=0)
    p95_candidate_count_after: int = Field(ge=0)
    full_pool_gold_operand_recall_mean: float = Field(ge=0, le=1)
    shortlist_gold_operand_recall_mean: float = Field(ge=0, le=1)
    cases_with_shortlist_recall_loss: int = Field(ge=0)
    full_pool_complete_operand_coverage_count: int = Field(ge=0)
    shortlist_complete_operand_coverage_count: int = Field(ge=0)
    best_iteration_outcome_by_operand_availability: dict[str, int]
    methodology: Literal[
        "exact_decimal_or_percent_normalized_gold_operand_match_v1"
    ] = "exact_decimal_or_percent_normalized_gold_operand_match_v1"
    limitation: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_outcome_accounting(self) -> CandidateShortlistAudit:
        if sum(self.best_iteration_outcome_by_operand_availability.values()) != (
            self.case_count
        ):
            raise ValueError("candidate availability outcomes do not reconcile")
        if (
            self.cases_with_shortlist_recall_loss > self.case_count
            or self.full_pool_complete_operand_coverage_count > self.case_count
            or self.shortlist_complete_operand_coverage_count > self.case_count
        ):
            raise ValueError("candidate audit count exceeds case count")
        if self.mean_candidate_count_after > self.mean_candidate_count_before:
            raise ValueError("candidate shortlist is larger than source pool")
        return self


class CalibrationShadowGate(_StrictModel):
    metric: ShadowGateMetric
    observed: float
    required: float
    passed: bool

    @model_validator(mode="after")
    def validate_gate_result(self) -> CalibrationShadowGate:
        expected = (
            self.observed <= self.required
            if self.metric in _LESS_THAN_OR_EQUAL_GATES
            else self.observed >= self.required
        )
        if self.passed != expected:
            raise ValueError("shadow gate result contradicts observed threshold")
        return self


class FinQATypedCalibrationPublicEvidence(_StrictModel):
    schema_version: Literal[
        "finqa_typed_contract_calibration_public_v1"
    ] = PUBLIC_SCHEMA_VERSION
    claim_label: Literal[
        "DISCLOSED_DEVELOPMENT_CALIBRATION"
    ] = CLAIM_LABEL
    protocol_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_gate_e_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    )
    source_gate_e_details_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cohort: Literal["calibration"]
    calibration_case_count: int = Field(ge=1)
    calibration_case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    answer_model_name: str = Field(min_length=1, max_length=200)
    answer_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    iterations: tuple[
        CalibrationIterationEvidence,
        CalibrationIterationEvidence,
        CalibrationIterationEvidence,
    ]
    paired_iteration_transitions: tuple[
        CalibrationIterationTransition,
        CalibrationIterationTransition,
        CalibrationIterationTransition,
    ]
    candidate_shortlist_audit: CandidateShortlistAudit
    best_iteration: Literal["v2_2"]
    best_iteration_shadow_gates: tuple[CalibrationShadowGate, ...]
    decision: Literal["CALIBRATION_REJECTED"]
    internal_validation_status: Literal["NOT_RUN"]
    multi_program_status: Literal["NOT_RUN"]
    next_bottleneck: Literal[
        "retrieval_candidate_extraction_scale_and_controlled_constants"
    ]
    content_exclusions: tuple[
        Literal["case_ids"],
        Literal["questions"],
        Literal["answers"],
        Literal["evidence_text"],
        Literal["gold_program_text"],
        Literal["selected_candidate_ids"],
    ]
    non_claims: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_public_contract(
        self,
    ) -> FinQATypedCalibrationPublicEvidence:
        if tuple(item.iteration_id for item in self.iterations) != (
            "v2",
            "v2_1",
            "v2_2",
        ):
            raise ValueError("calibration iterations are out of order")
        expected_pairs = (
            ("v2", "v2_1"),
            ("v2_1", "v2_2"),
            ("v2", "v2_2"),
        )
        if tuple(
            (item.source_iteration, item.target_iteration)
            for item in self.paired_iteration_transitions
        ) != expected_pairs:
            raise ValueError("calibration transition pairs are invalid")
        if any(
            item.summary.case_count != self.calibration_case_count
            or item.summary.cohort != "calibration"
            for item in self.iterations
        ):
            raise ValueError("calibration public case counts do not reconcile")
        if any(
            item.summary.b0 != self.iterations[0].summary.b0
            or item.summary.b1_v1 != self.iterations[0].summary.b1_v1
            for item in self.iterations[1:]
        ):
            raise ValueError("calibration iterations use different baselines")
        if any(
            item.case_count != self.calibration_case_count
            for item in self.paired_iteration_transitions
        ):
            raise ValueError("calibration transitions use a different cohort")
        if (
            self.candidate_shortlist_audit.case_count
            != self.calibration_case_count
        ):
            raise ValueError("candidate audit uses a different cohort")
        if tuple(
            item.metric for item in self.best_iteration_shadow_gates
        ) != SHADOW_GATE_METRICS:
            raise ValueError("calibration shadow gates are incomplete or unordered")
        return self


def _load_rows(run_dir: Path) -> list[FinQATypedCalibrationRunCase]:
    return [
        FinQATypedCalibrationRunCase.model_validate_json(line)
        for line in (run_dir / "details.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def _iteration_evidence(
    iteration_id: IterationId,
    run_dir: Path,
) -> tuple[
    CalibrationIterationEvidence,
    list[FinQATypedCalibrationRunCase],
    FinQATypedCalibrationRunManifest,
]:
    manifest = verify_calibration_run(run_dir)
    rows = _load_rows(run_dir)
    return (
        CalibrationIterationEvidence(
            iteration_id=iteration_id,
            run_id=manifest.run_id,
            private_manifest_sha256=hashlib.sha256(
                (run_dir / "manifest.json").read_bytes()
            ).hexdigest(),
            private_details_sha256=hashlib.sha256(
                (run_dir / "details.jsonl").read_bytes()
            ).hexdigest(),
            execution_code_revision=manifest.execution_code_revision,
            implementation_file_sha256=manifest.implementation_file_sha256,
            intent_version=manifest.intent_version,
            validator_version=manifest.validator_version,
            compiler_version=manifest.compiler_version,
            planner_version=manifest.planner_version,
            summary=manifest.summary,
        ),
        rows,
        manifest,
    )


def _transition(
    source_iteration: IterationId,
    source: Sequence[FinQATypedCalibrationRunCase],
    target_iteration: IterationId,
    target: Sequence[FinQATypedCalibrationRunCase],
) -> CalibrationIterationTransition:
    source_by_id = {row.case_id: row for row in source}
    target_by_id = {row.case_id: row for row in target}
    if set(source_by_id) != set(target_by_id):
        raise ValueError("paired calibration iterations use different cases")
    pairs = [
        (source_by_id[case_id], target_by_id[case_id])
        for case_id in sorted(source_by_id)
    ]
    return CalibrationIterationTransition(
        source_iteration=source_iteration,
        target_iteration=target_iteration,
        case_count=len(pairs),
        correct_to_wrong_count=sum(
            left.b1_v2.strict_execution_match
            and not right.b1_v2.strict_execution_match
            for left, right in pairs
        ),
        wrong_to_correct_count=sum(
            not left.b1_v2.strict_execution_match
            and right.b1_v2.strict_execution_match
            for left, right in pairs
        ),
        both_correct_count=sum(
            left.b1_v2.strict_execution_match
            and right.b1_v2.strict_execution_match
            for left, right in pairs
        ),
        both_wrong_count=sum(
            not left.b1_v2.strict_execution_match
            and not right.b1_v2.strict_execution_match
            for left, right in pairs
        ),
        answered_to_nonanswer_count=sum(
            left.b1_v2.status == "ANSWERED"
            and right.b1_v2.status != "ANSWERED"
            for left, right in pairs
        ),
        nonanswer_to_answered_count=sum(
            left.b1_v2.status != "ANSWERED"
            and right.b1_v2.status == "ANSWERED"
            for left, right in pairs
        ),
    )


def _evidence_for_case(
    case: FinQACase,
    selected_unit_ids: Sequence[str],
):
    by_id = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    if any(unit_id not in by_id for unit_id in selected_unit_ids):
        raise ValueError("candidate audit references unknown evidence")
    return tuple(by_id[unit_id] for unit_id in selected_unit_ids)


def _typed_context(case: FinQACase, selected_unit_ids: Sequence[str]) -> dict:
    evidence = _evidence_for_case(case, selected_unit_ids)
    guard = RetrievedContentGuard()
    admitted = [
        unit
        for unit in evidence
        if guard.scan(unit.text).disposition == "ADMIT"
    ]
    admitted_ids = {unit.unit_id for unit in admitted}
    candidates = extract_finqa_numeric_candidates(
        case,
        admitted_evidence_ids=admitted_ids,
    ).candidates
    return {
        "admitted_ids": admitted_ids,
        "candidates": candidates,
        "context": {unit.unit_id: unit.text for unit in admitted},
    }


def _operand_recall(
    gold_operands: Sequence[Decimal],
    candidate_values: Sequence[Decimal],
) -> tuple[float, bool]:
    if not gold_operands:
        return 1.0, True
    pool = Counter(candidate_values)
    matched = 0
    for operand in gold_operands:
        if pool[operand] > 0:
            pool[operand] -= 1
            matched += 1
        elif pool[operand / Decimal("100")] > 0:
            pool[operand / Decimal("100")] -= 1
            matched += 1
    return matched / len(gold_operands), matched == len(gold_operands)


def build_candidate_shortlist_audit(
    *,
    rows: Sequence[FinQATypedCalibrationRunCase],
    cases_by_id: Mapping[str, FinQACase],
) -> CandidateShortlistAudit:
    before_counts: list[int] = []
    after_counts: list[int] = []
    full_recalls: list[float] = []
    shortlist_recalls: list[float] = []
    recall_loss_count = 0
    full_complete_count = 0
    shortlist_complete_count = 0
    outcomes: Counter[str] = Counter()
    for row in rows:
        case = cases_by_id[row.case_id]
        context = _typed_context(case, row.selected_unit_ids)
        intent = extract_financial_question_intent_v2(case.qa.question)
        shortlist = question_conditioned_candidate_shortlist_v2(
            question=case.qa.question,
            candidates=context["candidates"],
            admitted_evidence_ids=context["admitted_ids"],
            intent=intent,
            evidence_context_by_id=context["context"],
        )
        gold = parse_finqa_gold_program(case.qa.program).numeric_operands
        full_recall, full_complete = _operand_recall(
            gold,
            [item.normalized_value for item in context["candidates"]],
        )
        short_recall, short_complete = _operand_recall(
            gold,
            [item.normalized_value for item in shortlist],
        )
        before_counts.append(len(context["candidates"]))
        after_counts.append(len(shortlist))
        full_recalls.append(full_recall)
        shortlist_recalls.append(short_recall)
        recall_loss_count += short_recall < full_recall
        full_complete_count += full_complete
        shortlist_complete_count += short_complete
        outcome = (
            "correct"
            if row.b1_v2.strict_execution_match
            else ("nonanswer" if row.b1_v2.status != "ANSWERED" else "wrong")
        )
        outcomes[
            f"{outcome}_{'all_gold_available' if short_complete else 'gold_missing'}"
        ] += 1
    ordered_after = sorted(after_counts)
    return CandidateShortlistAudit(
        case_count=len(rows),
        mean_candidate_count_before=sum(before_counts) / len(rows),
        mean_candidate_count_after=sum(after_counts) / len(rows),
        p95_candidate_count_after=ordered_after[
            max(0, (len(ordered_after) * 95 + 99) // 100 - 1)
        ],
        full_pool_gold_operand_recall_mean=sum(full_recalls) / len(rows),
        shortlist_gold_operand_recall_mean=(
            sum(shortlist_recalls) / len(rows)
        ),
        cases_with_shortlist_recall_loss=recall_loss_count,
        full_pool_complete_operand_coverage_count=full_complete_count,
        shortlist_complete_operand_coverage_count=shortlist_complete_count,
        best_iteration_outcome_by_operand_availability=dict(
            sorted(outcomes.items())
        ),
        limitation=(
            "This coarse diagnostic accepts exact Decimal matches or a "
            "percent-normalized value divided by 100; it does not prove semantic "
            "operand identity and treats official constants as unavailable unless "
            "present in admitted evidence."
        ),
    )


def _shadow_gates(
    summary: FinQATypedCalibrationRunSummary,
    protocol: FinQATypedCalibrationProtocol,
) -> tuple[CalibrationShadowGate, ...]:
    gates = protocol.adoption_gates
    comparison = summary.comparison
    observed = (
        ("coverage", summary.b1_v2.coverage, gates.min_coverage, "ge"),
        (
            "execution_accuracy_delta_vs_b0",
            comparison.execution_accuracy_delta_vs_b0,
            gates.min_execution_accuracy_delta_vs_b0,
            "ge",
        ),
        (
            "grounded_accuracy_delta_vs_b0",
            comparison.grounded_accuracy_delta_vs_b0,
            gates.min_grounded_accuracy_delta_vs_b0,
            "ge",
        ),
        (
            "correct_to_wrong_rate",
            comparison.correct_to_wrong_rate,
            gates.max_correct_to_wrong_rate,
            "le",
        ),
        (
            "wrong_to_correct_count",
            float(comparison.wrong_to_correct_count),
            float(gates.min_wrong_to_correct_count),
            "ge",
        ),
        (
            "prevented_operand_failure_count",
            float(comparison.prevented_operand_failure_count),
            float(gates.min_prevented_operand_failure_count),
            "ge",
        ),
        (
            "protocol_error_rate",
            summary.b1_v2.protocol_error_count / summary.case_count,
            gates.max_protocol_error_rate,
            "le",
        ),
        (
            "latency_mean_multiplier",
            comparison.latency_mean_multiplier_vs_b0 or float("inf"),
            gates.max_latency_mean_multiplier,
            "le",
        ),
        (
            "latency_p95_ms",
            summary.b1_v2.latency_ms_p95,
            gates.max_latency_p95_ms,
            "le",
        ),
    )
    return tuple(
        CalibrationShadowGate(
            metric=name,
            observed=value,
            required=threshold,
            passed=value >= threshold if comparator == "ge" else value <= threshold,
        )
        for name, value, threshold, comparator in observed
    )


def build_public_calibration_evidence(
    *,
    protocol: FinQATypedCalibrationProtocol,
    run_dirs: Mapping[IterationId, Path],
    cases_by_id: Mapping[str, FinQACase],
) -> FinQATypedCalibrationPublicEvidence:
    if set(run_dirs) != {"v2", "v2_1", "v2_2"}:
        raise ValueError("public calibration requires exactly three iterations")
    evidence_by_id = {}
    rows_by_id = {}
    manifests = {}
    for iteration_id in ("v2", "v2_1", "v2_2"):
        evidence, rows, manifest = _iteration_evidence(
            iteration_id,
            run_dirs[iteration_id],
        )
        evidence_by_id[iteration_id] = evidence
        rows_by_id[iteration_id] = rows
        manifests[iteration_id] = manifest
    first = manifests["v2"]
    if any(
        manifest.cohort != "calibration"
        or manifest.protocol_id != protocol.protocol_id
        or manifest.source_gate_e_details_sha256
        != protocol.source_gate_e_details_sha256
        or manifest.selected_case_ids_sha256
        != protocol.calibration_case_ids_sha256
        or manifest.answer_model != first.answer_model
        for manifest in manifests.values()
    ):
        raise ValueError("calibration iterations do not share a frozen contract")
    protocol_sha256 = hashlib.sha256(
        canonical_json_bytes(protocol.model_dump(mode="json"))
    ).hexdigest()
    best = evidence_by_id["v2_2"].summary
    return FinQATypedCalibrationPublicEvidence(
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e_run_id=protocol.source_gate_e_run_id,
        source_gate_e_details_sha256=protocol.source_gate_e_details_sha256,
        cohort="calibration",
        calibration_case_count=protocol.calibration_case_count,
        calibration_case_ids_sha256=protocol.calibration_case_ids_sha256,
        answer_model_name=first.answer_model.name,
        answer_model_sha256=first.answer_model.sha256,
        iterations=(
            evidence_by_id["v2"],
            evidence_by_id["v2_1"],
            evidence_by_id["v2_2"],
        ),
        paired_iteration_transitions=(
            _transition(
                "v2",
                rows_by_id["v2"],
                "v2_1",
                rows_by_id["v2_1"],
            ),
            _transition(
                "v2_1",
                rows_by_id["v2_1"],
                "v2_2",
                rows_by_id["v2_2"],
            ),
            _transition(
                "v2",
                rows_by_id["v2"],
                "v2_2",
                rows_by_id["v2_2"],
            ),
        ),
        candidate_shortlist_audit=build_candidate_shortlist_audit(
            rows=rows_by_id["v2_2"],
            cases_by_id=cases_by_id,
        ),
        best_iteration="v2_2",
        best_iteration_shadow_gates=_shadow_gates(best, protocol),
        decision="CALIBRATION_REJECTED",
        internal_validation_status="NOT_RUN",
        multi_program_status="NOT_RUN",
        next_bottleneck=(
            "retrieval_candidate_extraction_scale_and_controlled_constants"
        ),
        content_exclusions=(
            "case_ids",
            "questions",
            "answers",
            "evidence_text",
            "gold_program_text",
            "selected_candidate_ids",
        ),
        non_claims=(
            "not a held-out or confirmatory result",
            "not a frozen-test result",
            "not evidence that typed planning may replace B0",
            "candidate availability is a coarse diagnostic, not semantic recall",
            "internal validation and multi-program v2 were not run",
        ),
    )


__all__ = [
    "PUBLIC_SCHEMA_VERSION",
    "SHADOW_GATE_METRICS",
    "CalibrationIterationEvidence",
    "CalibrationIterationTransition",
    "CalibrationShadowGate",
    "CandidateShortlistAudit",
    "FinQATypedCalibrationPublicEvidence",
    "build_candidate_shortlist_audit",
    "build_public_calibration_evidence",
]
