from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_diagnostics import parse_finqa_gold_program
from app.external_datasets.finqa_numeric_evidence_protocol import (
    FinQANumericEvidenceProtocol,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericEvidenceClosurePolicyV2,
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_numeric_evidence_shortlist_v2 import (
    question_conditioned_numeric_evidence_shortlist_v2,
)
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_program import (
    NumericCandidate,
    extract_finqa_numeric_candidates,
)
from app.security.retrieved_content import RetrievedContentGuard


AUDIT_SCHEMA_VERSION = "finqa_numeric_evidence_audit_v1"
MatchCategory = Literal[
    "controlled_constant",
    "selected_normalized",
    "selected_surface_view",
    "retrieval_missing",
    "extraction_unresolved",
]

_GOLD_STEP = re.compile(r"([a-z_]+)\(([^()]*)\)(?:,\s*|$)")
_GOLD_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)%?")
_GOLD_CONSTANT = re.compile(r"const_(m)?(\d+)")
_STEP_REFERENCE = re.compile(r"#[0-9]+")
_SCALE_MULTIPLIER = {
    "one": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "percent": Decimal("0.01"),
    "basis_point": Decimal("0.0001"),
    "unknown": Decimal("1"),
}
_MATCHED_CATEGORIES = {
    "controlled_constant",
    "selected_normalized",
    "selected_surface_view",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GoldOperandReference(_StrictModel):
    value: Decimal
    kind: Literal["evidence", "controlled_constant"]


class NumericEvidenceInputViewCase(_StrictModel):
    categories: tuple[MatchCategory, ...]
    complete: bool
    candidate_count: int = Field(ge=0, le=256)

    @model_validator(mode="after")
    def validate_completion(self) -> NumericEvidenceInputViewCase:
        expected = all(item in _MATCHED_CATEGORIES for item in self.categories)
        if self.complete != expected:
            raise ValueError("numeric input completion contradicts categories")
        return self


class FinQANumericEvidenceCaseAudit(_StrictModel):
    case_id: str = Field(min_length=1)
    gold_operand_count: int = Field(ge=0)
    v1_selected_pre: NumericEvidenceInputViewCase
    v1_selected_post: NumericEvidenceInputViewCase
    v2_selected_pre: NumericEvidenceInputViewCase
    v2_selected_post: NumericEvidenceInputViewCase
    v2_closure_pre: NumericEvidenceInputViewCase
    v2_closure_post: NumericEvidenceInputViewCase
    v2_gold_evidence: NumericEvidenceInputViewCase
    closure_added_unit_count: int = Field(ge=0, le=64)
    closure_total_unit_count: int = Field(ge=1, le=64)
    closure_total_chars: int = Field(ge=1, le=64_000)
    closure_scan_count: int = Field(ge=1, le=64)
    closure_quarantined_unit_count: int = Field(ge=0, le=64)
    shortlist_error_count: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def validate_case_accounting(self) -> FinQANumericEvidenceCaseAudit:
        views = (
            self.v1_selected_pre,
            self.v1_selected_post,
            self.v2_selected_pre,
            self.v2_selected_post,
            self.v2_closure_pre,
            self.v2_closure_post,
            self.v2_gold_evidence,
        )
        if any(len(view.categories) != self.gold_operand_count for view in views):
            raise ValueError("numeric evidence case operands do not reconcile")
        if self.closure_scan_count != self.closure_total_unit_count:
            raise ValueError("numeric evidence closure was not fully scanned")
        return self


class NumericEvidenceInputViewSummary(_StrictModel):
    complete_case_count: int = Field(ge=0)
    complete_rate: float = Field(ge=0, le=1)
    candidate_count_mean: float = Field(ge=0)
    candidate_count_p95: int = Field(ge=0)
    candidate_count_max: int = Field(ge=0)
    match_category_counts: dict[str, int]


class NumericEvidenceClosureSummary(_StrictModel):
    added_unit_count_mean: float = Field(ge=0)
    added_unit_count_p95: int = Field(ge=0)
    total_unit_count_mean: float = Field(ge=1)
    total_unit_count_p95: int = Field(ge=1)
    total_unit_count_max: int = Field(ge=1)
    total_chars_mean: float = Field(ge=1)
    total_chars_p95: int = Field(ge=1)
    total_chars_max: int = Field(ge=1)
    scan_count: int = Field(ge=1)
    quarantined_unit_count: int = Field(ge=0)
    retrieval_missing_operand_count: int = Field(ge=0)
    retrieval_missing_operand_recovered_count: int = Field(ge=0)
    retrieval_missing_operand_recovery_rate: float = Field(ge=0, le=1)
    extraction_unresolved_operand_count: int = Field(ge=0)
    extraction_unresolved_operand_recovered_count: int = Field(ge=0)


class NumericEvidenceGateCheck(_StrictModel):
    gate: str = Field(min_length=1, max_length=128)
    comparator: Literal["ge", "le", "required"]
    observed: float | bool
    threshold: float | bool
    passed: bool


class FinQANumericEvidenceAuditSummary(_StrictModel):
    schema_version: Literal[
        "finqa_numeric_evidence_audit_v1"
    ] = AUDIT_SCHEMA_VERSION
    protocol_id: str = Field(min_length=1, max_length=200)
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    case_count: Literal[60]
    gold_operand_count: int = Field(ge=1)
    views: dict[str, NumericEvidenceInputViewSummary]
    closure: NumericEvidenceClosureSummary
    gate_checks: tuple[NumericEvidenceGateCheck, ...]
    decision: Literal["INPUT_GATE_PASSED", "INPUT_GATE_FAILED"]
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]
    model_call_count: Literal[0] = 0

    @model_validator(mode="after")
    def validate_decision(self) -> FinQANumericEvidenceAuditSummary:
        expected = (
            "INPUT_GATE_PASSED"
            if self.gate_checks and all(item.passed for item in self.gate_checks)
            else "INPUT_GATE_FAILED"
        )
        if self.decision != expected:
            raise ValueError("numeric evidence decision contradicts gate checks")
        return self


def parse_gold_operand_references(program: str) -> tuple[GoldOperandReference, ...]:
    parse_finqa_gold_program(program)
    result: list[GoldOperandReference] = []
    position = 0
    while position < len(program):
        match = _GOLD_STEP.match(program, position)
        if match is None:
            raise ValueError("FinQA gold program has unsupported syntax")
        for argument in (item.strip() for item in match.group(2).split(",")):
            constant = _GOLD_CONSTANT.fullmatch(argument)
            if constant is not None:
                value = Decimal(
                    ("-" if constant.group(1) else "") + constant.group(2)
                )
                result.append(
                    GoldOperandReference(
                        value=value,
                        kind="controlled_constant",
                    )
                )
            elif _GOLD_NUMBER.fullmatch(argument):
                result.append(
                    GoldOperandReference(
                        value=Decimal(argument.removesuffix("%")),
                        kind="evidence",
                    )
                )
            # The upstream parser has already validated symbolic table selectors
            # such as "expected life in years". They are not numeric evidence.
        position = match.end()
    return tuple(result)


def _surface_value(candidate: NumericCandidate) -> Decimal:
    return candidate.normalized_value / _SCALE_MULTIPLIER[candidate.scale]


def _maximum_candidate_matches(
    operands: Sequence[GoldOperandReference],
    candidates: Sequence[NumericCandidate],
    operand_indices: Sequence[int],
) -> dict[int, tuple[int, MatchCategory]]:
    result: dict[int, tuple[int, MatchCategory]] = {}
    for operand_index in operand_indices:
        value = operands[operand_index].value
        matches: list[tuple[int, MatchCategory]] = []
        for candidate_index, candidate in enumerate(candidates):
            if candidate.role != "operand":
                continue
            if candidate.normalized_value == value:
                matches.append((candidate_index, "selected_normalized"))
            elif _surface_value(candidate) == value:
                matches.append((candidate_index, "selected_surface_view"))
        ranked = sorted(
            matches,
            key=lambda item: (
                0 if item[1] == "selected_normalized" else 1,
                candidates[item[0]].candidate_id,
            ),
        )
        if ranked:
            result[operand_index] = ranked[0]
    return result


def classify_operand_availability(
    operands: Sequence[GoldOperandReference],
    selected_candidates: Sequence[NumericCandidate],
    gold_evidence_candidates: Sequence[NumericCandidate],
) -> tuple[MatchCategory, ...]:
    categories: list[MatchCategory | None] = [None] * len(operands)
    evidence_indices = []
    for index, operand in enumerate(operands):
        if operand.kind == "controlled_constant":
            categories[index] = "controlled_constant"
        else:
            evidence_indices.append(index)
    selected = _maximum_candidate_matches(
        operands,
        selected_candidates,
        evidence_indices,
    )
    for index, (_, category) in selected.items():
        categories[index] = category
    missing_indices = [
        index for index in evidence_indices if categories[index] is None
    ]
    retrievable = _maximum_candidate_matches(
        operands,
        gold_evidence_candidates,
        missing_indices,
    )
    for index in missing_indices:
        categories[index] = (
            "retrieval_missing"
            if index in retrievable
            else "extraction_unresolved"
        )
    return tuple(category for category in categories if category is not None)


def _view(
    categories: tuple[MatchCategory, ...],
    candidate_count: int,
) -> NumericEvidenceInputViewCase:
    return NumericEvidenceInputViewCase(
        categories=categories,
        complete=all(item in _MATCHED_CATEGORIES for item in categories),
        candidate_count=candidate_count,
    )


def _context(
    case: FinQACase,
    unit_ids: Sequence[str],
) -> dict[str, str]:
    units = {unit.unit_id: unit.text for unit in build_finqa_evidence_units(case)}
    return {unit_id: units[unit_id] for unit_id in unit_ids}


def evaluate_numeric_evidence_case(
    *,
    case: FinQACase,
    source_row: FinQATypedCalibrationRunCase,
    policy: NumericEvidenceClosurePolicyV2,
    guard: RetrievedContentGuard,
) -> FinQANumericEvidenceCaseAudit:
    if case.id != source_row.case_id:
        raise ValueError("numeric evidence case does not match source row")
    operands = parse_gold_operand_references(case.qa.program)
    selected_ids = set(source_row.selected_unit_ids)
    gold_ids = set(source_row.gold_unit_ids)
    v1_selected = extract_finqa_numeric_candidates(
        case,
        admitted_evidence_ids=selected_ids,
    ).candidates
    v1_gold = extract_finqa_numeric_candidates(
        case,
        admitted_evidence_ids=gold_ids,
    ).candidates
    v2_selected = extract_finqa_numeric_candidates_v2(
        case,
        admitted_evidence_ids=selected_ids,
    ).candidates
    v2_gold = extract_finqa_numeric_candidates_v2(
        case,
        admitted_evidence_ids=gold_ids,
    ).candidates
    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=source_row.selected_unit_ids,
        policy=policy,
    )
    admission = admit_finqa_numeric_evidence_closure_v2(
        case,
        closure=closure,
        guard=guard,
    )
    closure_ids = set(admission.admitted_unit_ids)
    v2_closure = extract_finqa_numeric_candidates_v2(
        case,
        admitted_evidence_ids=closure_ids,
    ).candidates

    intent = extract_financial_question_intent_v2(case.qa.question)
    shortlist_error_count = 0

    def shortlist(
        candidates: Sequence[NumericCandidate],
        evidence_ids: set[str],
        ordered_evidence_ids: Sequence[str],
    ) -> tuple[NumericCandidate, ...]:
        nonlocal shortlist_error_count
        try:
            return question_conditioned_numeric_evidence_shortlist_v2(
                question=case.qa.question,
                candidates=candidates,
                admitted_evidence_ids=evidence_ids,
                intent=intent,
                evidence_context_by_id=_context(
                    case,
                    ordered_evidence_ids,
                ),
            )
        except ValueError:
            shortlist_error_count += 1
            return ()

    v1_shortlist = shortlist(
        v1_selected,
        selected_ids,
        source_row.selected_unit_ids,
    )
    v2_selected_shortlist = shortlist(
        v2_selected,
        selected_ids,
        source_row.selected_unit_ids,
    )
    v2_closure_shortlist = shortlist(
        v2_closure,
        closure_ids,
        admission.admitted_unit_ids,
    )

    def categories(
        selected: Sequence[NumericCandidate],
        gold: Sequence[NumericCandidate],
    ) -> tuple[MatchCategory, ...]:
        return classify_operand_availability(operands, selected, gold)

    return FinQANumericEvidenceCaseAudit(
        case_id=case.id,
        gold_operand_count=len(operands),
        v1_selected_pre=_view(
            categories(v1_selected, v1_gold),
            len(v1_selected),
        ),
        v1_selected_post=_view(
            categories(v1_shortlist, v1_gold),
            len(v1_shortlist),
        ),
        v2_selected_pre=_view(
            categories(v2_selected, v2_gold),
            len(v2_selected),
        ),
        v2_selected_post=_view(
            categories(v2_selected_shortlist, v2_gold),
            len(v2_selected_shortlist),
        ),
        v2_closure_pre=_view(
            categories(v2_closure, v2_gold),
            len(v2_closure),
        ),
        v2_closure_post=_view(
            categories(v2_closure_shortlist, v2_gold),
            len(v2_closure_shortlist),
        ),
        v2_gold_evidence=_view(
            categories(v2_gold, v2_gold),
            len(v2_gold),
        ),
        closure_added_unit_count=len(closure.added_unit_ids),
        closure_total_unit_count=closure.total_unit_count,
        closure_total_chars=closure.total_chars,
        closure_scan_count=admission.scan_count,
        closure_quarantined_unit_count=len(
            admission.quarantined_unit_ids
        ),
        shortlist_error_count=shortlist_error_count,
    )


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)]


def _view_summary(
    rows: Sequence[FinQANumericEvidenceCaseAudit],
    field: str,
) -> NumericEvidenceInputViewSummary:
    views = [getattr(row, field) for row in rows]
    counts = [view.candidate_count for view in views]
    categories = Counter(
        category for view in views for category in view.categories
    )
    complete = sum(view.complete for view in views)
    return NumericEvidenceInputViewSummary(
        complete_case_count=complete,
        complete_rate=complete / len(views),
        candidate_count_mean=sum(counts) / len(counts),
        candidate_count_p95=_p95(counts),
        candidate_count_max=max(counts),
        match_category_counts=dict(sorted(categories.items())),
    )


def summarize_numeric_evidence_audit(
    *,
    rows: Sequence[FinQANumericEvidenceCaseAudit],
    protocol: FinQANumericEvidenceProtocol,
    v1_byte_stability_verified: bool,
    provenance_bound_dual_value_verified: bool,
    no_gold_runtime_input_verified: bool,
) -> FinQANumericEvidenceAuditSummary:
    if len(rows) != protocol.calibration_case_count:
        raise ValueError("numeric evidence audit case count is invalid")
    case_ids = [row.case_id for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("numeric evidence audit case IDs are duplicated")
    view_fields = (
        "v1_selected_pre",
        "v1_selected_post",
        "v2_selected_pre",
        "v2_selected_post",
        "v2_closure_pre",
        "v2_closure_post",
        "v2_gold_evidence",
    )
    views = {
        field: _view_summary(rows, field)
        for field in view_fields
    }
    baseline_retrieval = sum(
        category == "retrieval_missing"
        for row in rows
        for category in row.v1_selected_pre.categories
    )
    recovered_retrieval = sum(
        before == "retrieval_missing"
        and after in _MATCHED_CATEGORIES
        for row in rows
        for before, after in zip(
            row.v1_selected_pre.categories,
            row.v2_closure_post.categories,
            strict=True,
        )
    )
    baseline_unresolved = sum(
        category == "extraction_unresolved"
        for row in rows
        for category in row.v1_selected_pre.categories
    )
    recovered_unresolved = sum(
        before == "extraction_unresolved"
        and after in _MATCHED_CATEGORIES
        for row in rows
        for before, after in zip(
            row.v1_selected_pre.categories,
            row.v2_selected_pre.categories,
            strict=True,
        )
    )
    closure = NumericEvidenceClosureSummary(
        added_unit_count_mean=sum(
            row.closure_added_unit_count for row in rows
        )
        / len(rows),
        added_unit_count_p95=_p95(
            [row.closure_added_unit_count for row in rows]
        ),
        total_unit_count_mean=sum(
            row.closure_total_unit_count for row in rows
        )
        / len(rows),
        total_unit_count_p95=_p95(
            [row.closure_total_unit_count for row in rows]
        ),
        total_unit_count_max=max(
            row.closure_total_unit_count for row in rows
        ),
        total_chars_mean=sum(row.closure_total_chars for row in rows)
        / len(rows),
        total_chars_p95=_p95([row.closure_total_chars for row in rows]),
        total_chars_max=max(row.closure_total_chars for row in rows),
        scan_count=sum(row.closure_scan_count for row in rows),
        quarantined_unit_count=sum(
            row.closure_quarantined_unit_count for row in rows
        ),
        retrieval_missing_operand_count=baseline_retrieval,
        retrieval_missing_operand_recovered_count=recovered_retrieval,
        retrieval_missing_operand_recovery_rate=(
            recovered_retrieval / baseline_retrieval
            if baseline_retrieval
            else 1.0
        ),
        extraction_unresolved_operand_count=baseline_unresolved,
        extraction_unresolved_operand_recovered_count=recovered_unresolved,
    )
    gates = protocol.gates
    observed = (
        (
            "runtime_input_complete_rate",
            views["v2_closure_post"].complete_rate,
            gates.min_runtime_input_complete_rate,
            "ge",
        ),
        (
            "gold_evidence_complete_rate",
            views["v2_gold_evidence"].complete_rate,
            gates.min_gold_evidence_complete_rate,
            "ge",
        ),
        (
            "retrieval_missing_operand_recovery_rate",
            closure.retrieval_missing_operand_recovery_rate,
            gates.min_retrieval_missing_operand_recovery_rate,
            "ge",
        ),
        (
            "p95_total_evidence_units",
            float(closure.total_unit_count_p95),
            float(gates.max_p95_total_evidence_units),
            "le",
        ),
        (
            "p95_total_evidence_chars",
            float(closure.total_chars_p95),
            float(gates.max_p95_total_evidence_chars),
            "le",
        ),
        (
            "p95_candidates_before_shortlist",
            float(views["v2_closure_pre"].candidate_count_p95),
            float(gates.max_p95_candidates_before_shortlist),
            "le",
        ),
        (
            "v1_byte_stability",
            v1_byte_stability_verified,
            True,
            "required",
        ),
        (
            "added_evidence_guard_scan",
            all(
                row.closure_scan_count == row.closure_total_unit_count
                for row in rows
            ),
            True,
            "required",
        ),
        (
            "provenance_bound_dual_value_view",
            provenance_bound_dual_value_verified,
            True,
            "required",
        ),
        (
            "no_gold_runtime_input",
            no_gold_runtime_input_verified,
            True,
            "required",
        ),
        (
            "p95_candidates_after_shortlist",
            float(views["v2_closure_post"].candidate_count_p95),
            float(protocol.budgets.max_candidates_after_shortlist),
            "le",
        ),
    )
    gate_checks = tuple(
        NumericEvidenceGateCheck(
            gate=name,
            comparator=comparator,
            observed=value,
            threshold=threshold,
            passed=(
                value >= threshold
                if comparator == "ge"
                else (
                    value <= threshold
                    if comparator == "le"
                    else value is threshold
                )
            ),
        )
        for name, value, threshold, comparator in observed
    )
    decision = (
        "INPUT_GATE_PASSED"
        if all(item.passed for item in gate_checks)
        else "INPUT_GATE_FAILED"
    )
    return FinQANumericEvidenceAuditSummary(
        protocol_id=protocol.protocol_id,
        claim_label=protocol.claim_label,
        case_count=60,
        gold_operand_count=sum(row.gold_operand_count for row in rows),
        views=views,
        closure=closure,
        gate_checks=gate_checks,
        decision=decision,
        internal_validation_status="NOT_RUN",
        frozen_test_status="UNTOUCHED",
    )


def evaluate_numeric_evidence_calibration(
    *,
    cases_by_id: Mapping[str, FinQACase],
    source_rows: Sequence[FinQATypedCalibrationRunCase],
    protocol: FinQANumericEvidenceProtocol,
    policy: NumericEvidenceClosurePolicyV2 | None = None,
    guard: RetrievedContentGuard | None = None,
    v1_byte_stability_verified: bool,
    provenance_bound_dual_value_verified: bool,
    no_gold_runtime_input_verified: bool,
) -> tuple[
    tuple[FinQANumericEvidenceCaseAudit, ...],
    FinQANumericEvidenceAuditSummary,
]:
    resolved_policy = policy or NumericEvidenceClosurePolicyV2(
        max_added_evidence_units=protocol.budgets.max_added_evidence_units,
        max_total_evidence_units=protocol.budgets.max_total_evidence_units,
        max_total_evidence_chars=protocol.budgets.max_total_evidence_chars,
        text_neighbor_radius=protocol.budgets.text_neighbor_radius,
        expand_bounded_table_parent=(
            protocol.budgets.expand_bounded_table_parent
        ),
    )
    resolved_guard = guard or RetrievedContentGuard()
    rows = tuple(
        evaluate_numeric_evidence_case(
            case=cases_by_id[source.case_id],
            source_row=source,
            policy=resolved_policy,
            guard=resolved_guard,
        )
        for source in source_rows
    )
    return rows, summarize_numeric_evidence_audit(
        rows=rows,
        protocol=protocol,
        v1_byte_stability_verified=v1_byte_stability_verified,
        provenance_bound_dual_value_verified=(
            provenance_bound_dual_value_verified
        ),
        no_gold_runtime_input_verified=no_gold_runtime_input_verified,
    )


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "FinQANumericEvidenceAuditSummary",
    "FinQANumericEvidenceCaseAudit",
    "GoldOperandReference",
    "NumericEvidenceClosureSummary",
    "NumericEvidenceGateCheck",
    "NumericEvidenceInputViewCase",
    "NumericEvidenceInputViewSummary",
    "classify_operand_availability",
    "evaluate_numeric_evidence_calibration",
    "evaluate_numeric_evidence_case",
    "parse_gold_operand_references",
    "summarize_numeric_evidence_audit",
]
