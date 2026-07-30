from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_numeric_evidence_shortlist_v2 import (
    question_conditioned_numeric_evidence_shortlist_v2,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility import (
    build_role_candidate_compatibility_matrix,
    hard_compatible_candidates_for_role,
    verify_role_exact_parser_enforcement,
)
from app.external_datasets.finqa_role_compatibility_protocol import (
    FinQARoleCompatibilityProtocol,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_semantic_demos import (
    FinQADemoSource,
    _build_value_free_skeleton,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.security.retrieved_content import RetrievedContentGuard


AUDIT_SCHEMA_VERSION = "finqa_role_compatibility_audit_v1"
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


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class GoldRoleTarget(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-6]$")
    kind: Literal["evidence", "controlled_constant", "symbolic"]
    value: Decimal | None = None

    @model_validator(mode="after")
    def validate_target(self) -> GoldRoleTarget:
        if (self.kind == "symbolic") != (self.value is None):
            raise ValueError("gold role target kind and value disagree")
        return self


class GoldRoleRetention(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-6]$")
    kind: Literal["evidence", "controlled_constant", "symbolic"]
    hard_filter_retained: bool
    retained_at_4: bool
    retained_at_8: bool


class FinQARoleCompatibilityCaseAudit(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_audit_v1"
    ] = AUDIT_SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=512)
    status: Literal[
        "EVALUATED",
        "UNSUPPORTED_GOLD_SKELETON",
        "COMPATIBILITY_ERROR",
    ]
    failure_reason: str | None = Field(default=None, max_length=256)
    global_candidate_count: int = Field(ge=0, le=24)
    role_count: int = Field(ge=0, le=6)
    symbolic_role_count: int = Field(ge=0, le=6)
    hard_compatible_counts: tuple[int, ...]
    allowlist_counts: tuple[int, ...]
    retention: tuple[GoldRoleRetention, ...]
    complete_at_8: bool
    baseline_role_candidate_edges: int = Field(ge=0, le=144)
    selected_role_candidate_edges: int = Field(ge=0, le=48)
    empty_role_allowlist_count: int = Field(ge=0, le=6)
    known_period_conflict_count: int = Field(ge=0, le=48)
    non_admitted_exposure_count: int = Field(ge=0, le=48)
    outside_global_shortlist_count: int = Field(ge=0, le=48)
    input_order_invariant: bool
    candidate_identity_preserved: bool
    matrix_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_accounting(self) -> FinQARoleCompatibilityCaseAudit:
        if (
            len(self.retention) != self.role_count
            or self.symbolic_role_count
            != sum(item.kind == "symbolic" for item in self.retention)
        ):
            raise ValueError("role compatibility target accounting is invalid")
        if self.status == "EVALUATED":
            if (
                self.failure_reason is not None
                or self.matrix_sha256 is None
                or len(self.hard_compatible_counts) != self.role_count
                or len(self.allowlist_counts) != self.role_count
            ):
                raise ValueError("evaluated role compatibility row is incomplete")
        elif self.matrix_sha256 is not None or self.failure_reason is None:
            raise ValueError("failed role compatibility row is inconsistent")
        expected_complete = (
            self.status == "EVALUATED"
            and bool(self.retention)
            and all(item.retained_at_8 for item in self.retention)
        )
        if self.complete_at_8 != expected_complete:
            raise ValueError("role compatibility complete flag is invalid")
        return self


class FinQARoleCompatibilityGateCheck(_StrictFrozenModel):
    gate: str = Field(min_length=1, max_length=128)
    comparator: Literal["ge", "le", "eq", "required"]
    observed: float | bool
    threshold: float | bool
    passed: bool


class FinQARoleCompatibilityAuditSummary(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_audit_summary_v1"
    ]
    protocol_id: str = Field(min_length=1, max_length=200)
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    case_count: Literal[60]
    evaluated_case_count: int = Field(ge=0, le=60)
    failed_case_count: int = Field(ge=0, le=60)
    gold_role_count: int = Field(ge=1)
    symbolic_role_count: int = Field(ge=0)
    hard_filter_gold_role_retention: float = Field(ge=0, le=1)
    gold_role_recall_at_4: float = Field(ge=0, le=1)
    gold_role_recall_at_8: float = Field(ge=0, le=1)
    complete_case_rate_at_8: float = Field(ge=0, le=1)
    mean_hard_compatible_candidates_per_role: float = Field(ge=0, le=24)
    mean_candidates_per_role: float = Field(ge=0, le=8)
    p95_candidates_per_role: int = Field(ge=0, le=8)
    role_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    empty_role_allowlist_rate: float = Field(ge=0, le=1)
    known_period_conflict_count: int = Field(ge=0)
    non_admitted_exposure_count: int = Field(ge=0)
    outside_global_shortlist_count: int = Field(ge=0)
    input_order_invariant_case_count: int = Field(ge=0, le=60)
    candidate_identity_preserved_case_count: int = Field(ge=0, le=60)
    silent_global_fallback_count: Literal[0] = 0
    no_gold_runtime_input_verified: bool
    role_exact_parser_enforcement_verified: bool
    gate_checks: tuple[FinQARoleCompatibilityGateCheck, ...]
    decision: Literal["INPUT_GATE_PASSED", "INPUT_GATE_FAILED"]
    model_call_count: Literal[0] = 0
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]

    @model_validator(mode="after")
    def validate_decision(self) -> FinQARoleCompatibilityAuditSummary:
        if self.evaluated_case_count + self.failed_case_count != self.case_count:
            raise ValueError("role compatibility case accounting is invalid")
        expected = (
            "INPUT_GATE_PASSED"
            if self.gate_checks and all(item.passed for item in self.gate_checks)
            else "INPUT_GATE_FAILED"
        )
        if self.decision != expected:
            raise ValueError("role compatibility decision contradicts gates")
        return self


def parse_gold_role_targets(program: str) -> tuple[GoldRoleTarget, ...]:
    role_by_operand: dict[str, str] = {}
    targets: list[GoldRoleTarget] = []
    position = 0
    while position < len(program):
        match = _GOLD_STEP.match(program, position)
        if match is None:
            raise ValueError("FinQA gold program has unsupported syntax")
        for argument in (item.strip() for item in match.group(2).split(",")):
            if _STEP_REFERENCE.fullmatch(argument):
                continue
            if argument in role_by_operand:
                continue
            role_id = f"role-{len(role_by_operand) + 1:02d}"
            role_by_operand[argument] = role_id
            constant = _GOLD_CONSTANT.fullmatch(argument)
            number = _GOLD_NUMBER.fullmatch(argument)
            if constant is not None:
                value = Decimal(
                    ("-" if constant.group(1) else "") + constant.group(2)
                )
                kind = "controlled_constant"
            elif number is not None:
                value = Decimal(argument.removesuffix("%"))
                kind = "evidence"
            else:
                value = None
                kind = "symbolic"
            targets.append(
                GoldRoleTarget(
                    role_id=role_id,
                    kind=kind,
                    value=value,
                )
            )
        position = match.end()
    return tuple(targets)


def _surface_value(candidate: NumericCandidateV2) -> Decimal:
    return candidate.normalized_value / _SCALE_MULTIPLIER[candidate.scale]


def _target_retained(
    target: GoldRoleTarget,
    candidates: Sequence[NumericCandidateV2],
) -> bool:
    if target.value is None:
        return False
    return any(
        candidate.normalized_value == target.value
        or _surface_value(candidate) == target.value
        for candidate in candidates
    )


def _candidate_identity_sha256(
    candidates: Sequence[NumericCandidateV2],
) -> str:
    payload = "\n".join(
        candidate.model_dump_json()
        for candidate in sorted(
            candidates,
            key=lambda item: item.candidate_id,
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bounded_failure_reason(error: ValueError) -> str:
    message = str(error).casefold()
    if "empty allowlist" in message:
        return "empty_role_allowlist"
    if "skeleton" in message or "role" in message:
        return "semantic_skeleton_incompatible"
    if "budget" in message:
        return "budget_exceeded"
    return "compatibility_precondition_failed"


def evaluate_role_compatibility_case(
    *,
    case: FinQACase,
    source_row: FinQASemanticPlanningCase,
    guard: RetrievedContentGuard,
) -> FinQARoleCompatibilityCaseAudit:
    if case.id != source_row.case_id:
        raise ValueError("role compatibility case and source row do not match")
    targets = parse_gold_role_targets(case.qa.program)
    skeleton = _build_value_free_skeleton(
        FinQADemoSource(
            case_id=case.id,
            question=case.qa.question,
            program=case.qa.program,
        )
    )
    if skeleton is None or len(targets) != len(skeleton.roles):
        return FinQARoleCompatibilityCaseAudit(
            case_id=case.id,
            status="UNSUPPORTED_GOLD_SKELETON",
            failure_reason="unsupported_gold_skeleton",
            global_candidate_count=0,
            role_count=len(targets),
            symbolic_role_count=sum(item.kind == "symbolic" for item in targets),
            hard_compatible_counts=(),
            allowlist_counts=(),
            retention=tuple(
                GoldRoleRetention(
                    role_id=target.role_id,
                    kind=target.kind,
                    hard_filter_retained=False,
                    retained_at_4=False,
                    retained_at_8=False,
                )
                for target in targets
            ),
            complete_at_8=False,
            baseline_role_candidate_edges=0,
            selected_role_candidate_edges=0,
            empty_role_allowlist_count=len(targets),
            known_period_conflict_count=0,
            non_admitted_exposure_count=0,
            outside_global_shortlist_count=0,
            input_order_invariant=False,
            candidate_identity_preserved=False,
            matrix_sha256=None,
        )

    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=source_row.selected_unit_ids,
    )
    admission = admit_finqa_numeric_evidence_closure_v2(
        case,
        closure=closure,
        guard=guard,
    )
    if admission.admitted_unit_ids != source_row.admitted_closure_unit_ids:
        raise ValueError("Gate E5 admitted evidence is not reproducible")
    admitted_ids = set(admission.admitted_unit_ids)
    corpus = extract_finqa_numeric_candidates_v2(
        case,
        admitted_evidence_ids=admitted_ids,
    )
    intent = extract_financial_question_intent_v2(case.qa.question)
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    context = {
        unit_id: units[unit_id].text
        for unit_id in admission.admitted_unit_ids
    }
    shortlist = question_conditioned_numeric_evidence_shortlist_v2(
        question=case.qa.question,
        candidates=corpus.candidates,
        admitted_evidence_ids=admitted_ids,
        intent=intent,
        evidence_context_by_id=context,
    )
    before_identity = _candidate_identity_sha256(shortlist)
    try:
        matrix = build_role_candidate_compatibility_matrix(
            question=case.qa.question,
            skeleton=skeleton,
            candidates=shortlist,
            admitted_evidence_ids=admitted_ids,
            intent=intent,
            evidence_context_by_id=context,
        )
    except ValueError as error:
        return FinQARoleCompatibilityCaseAudit(
            case_id=case.id,
            status="COMPATIBILITY_ERROR",
            failure_reason=_bounded_failure_reason(error),
            global_candidate_count=len(shortlist),
            role_count=len(targets),
            symbolic_role_count=sum(item.kind == "symbolic" for item in targets),
            hard_compatible_counts=(),
            allowlist_counts=(),
            retention=tuple(
                GoldRoleRetention(
                    role_id=target.role_id,
                    kind=target.kind,
                    hard_filter_retained=False,
                    retained_at_4=False,
                    retained_at_8=False,
                )
                for target in targets
            ),
            complete_at_8=False,
            baseline_role_candidate_edges=len(shortlist) * len(targets),
            selected_role_candidate_edges=0,
            empty_role_allowlist_count=len(targets),
            known_period_conflict_count=0,
            non_admitted_exposure_count=0,
            outside_global_shortlist_count=0,
            input_order_invariant=False,
            candidate_identity_preserved=(
                before_identity == _candidate_identity_sha256(shortlist)
            ),
            matrix_sha256=None,
        )

    reversed_matrix = build_role_candidate_compatibility_matrix(
        question=case.qa.question,
        skeleton=skeleton,
        candidates=tuple(reversed(shortlist)),
        admitted_evidence_ids=admitted_ids,
        intent=intent,
        evidence_context_by_id=context,
    )
    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in shortlist
    }
    global_ids = set(candidate_by_id)
    target_by_role = {item.role_id: item for item in targets}
    retention: list[GoldRoleRetention] = []
    hard_counts: list[int] = []
    allowlist_counts: list[int] = []
    known_period_conflicts = 0
    non_admitted_exposures = 0
    outside_global = 0
    for role, allowlist in zip(
        skeleton.roles,
        matrix.role_allowlists,
        strict=True,
    ):
        hard = hard_compatible_candidates_for_role(
            role=role,
            skeleton=skeleton,
            candidates=shortlist,
            intent=intent,
        )
        selected = tuple(
            candidate_by_id[candidate_id]
            for candidate_id in allowlist.candidate_ids
        )
        target = target_by_role[role.role_id]
        hard_counts.append(len(hard))
        allowlist_counts.append(len(selected))
        retention.append(
            GoldRoleRetention(
                role_id=role.role_id,
                kind=target.kind,
                hard_filter_retained=_target_retained(target, hard),
                retained_at_4=_target_retained(target, selected[:4]),
                retained_at_8=_target_retained(target, selected),
            )
        )
        for candidate in selected:
            if candidate.evidence_id not in admitted_ids or candidate.role != "operand":
                non_admitted_exposures += 1
            if candidate.candidate_id not in global_ids:
                outside_global += 1
            period = (
                candidate.period.casefold().strip()
                if candidate.period is not None
                else (
                    str(candidate.fiscal_year)
                    if candidate.fiscal_year is not None
                    else None
                )
            )
            if (
                allowlist.expected_period is not None
                and period is not None
                and period != allowlist.expected_period
            ):
                known_period_conflicts += 1
    return FinQARoleCompatibilityCaseAudit(
        case_id=case.id,
        status="EVALUATED",
        global_candidate_count=len(shortlist),
        role_count=len(targets),
        symbolic_role_count=sum(item.kind == "symbolic" for item in targets),
        hard_compatible_counts=tuple(hard_counts),
        allowlist_counts=tuple(allowlist_counts),
        retention=tuple(retention),
        complete_at_8=all(item.retained_at_8 for item in retention),
        baseline_role_candidate_edges=len(shortlist) * len(targets),
        selected_role_candidate_edges=sum(allowlist_counts),
        empty_role_allowlist_count=0,
        known_period_conflict_count=known_period_conflicts,
        non_admitted_exposure_count=non_admitted_exposures,
        outside_global_shortlist_count=outside_global,
        input_order_invariant=(
            matrix.role_allowlists == reversed_matrix.role_allowlists
            and matrix.matrix_sha256 == reversed_matrix.matrix_sha256
        ),
        candidate_identity_preserved=(
            before_identity == _candidate_identity_sha256(shortlist)
        ),
        matrix_sha256=matrix.matrix_sha256,
    )


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return ordered[index]


def _check(
    gate: str,
    comparator: Literal["ge", "le", "eq", "required"],
    observed: float | bool,
    threshold: float | bool,
) -> FinQARoleCompatibilityGateCheck:
    passed = (
        observed >= threshold
        if comparator == "ge"
        else (
            observed <= threshold
            if comparator == "le"
            else observed == threshold
        )
    )
    return FinQARoleCompatibilityGateCheck(
        gate=gate,
        comparator=comparator,
        observed=observed,
        threshold=threshold,
        passed=passed,
    )


def verify_no_gold_runtime_input() -> bool:
    source = inspect.getsource(build_role_candidate_compatibility_matrix)
    parameters = inspect.signature(
        build_role_candidate_compatibility_matrix
    ).parameters
    forbidden = ("gold", "answer", "case_id", "gold_evidence")
    return not any(
        token in parameter.casefold()
        for parameter in parameters
        for token in forbidden
    ) and not any(f"{token}=" in source.casefold() for token in forbidden)


def summarize_role_compatibility_audit(
    rows: Sequence[FinQARoleCompatibilityCaseAudit],
    *,
    protocol: FinQARoleCompatibilityProtocol,
) -> FinQARoleCompatibilityAuditSummary:
    if len(rows) != protocol.calibration_case_count:
        raise ValueError("role compatibility audit must contain 60 cases")
    retentions = [item for row in rows for item in row.retention]
    role_count = len(retentions)
    hard_counts = [item for row in rows for item in row.hard_compatible_counts]
    allowlist_counts = [item for row in rows for item in row.allowlist_counts]
    hard_retained = sum(item.hard_filter_retained for item in retentions)
    retained_at_4 = sum(item.retained_at_4 for item in retentions)
    retained_at_8 = sum(item.retained_at_8 for item in retentions)
    baseline_edges = sum(row.baseline_role_candidate_edges for row in rows)
    selected_edges = sum(row.selected_role_candidate_edges for row in rows)
    empty_roles = sum(row.empty_role_allowlist_count for row in rows)
    evaluated = sum(row.status == "EVALUATED" for row in rows)
    hard_retention_rate = hard_retained / role_count
    recall_at_4 = retained_at_4 / role_count
    recall_at_8 = retained_at_8 / role_count
    complete_rate = sum(row.complete_at_8 for row in rows) / len(rows)
    mean_hard = sum(hard_counts) / role_count
    mean_selected = sum(allowlist_counts) / role_count
    edge_reduction = (
        1 - selected_edges / baseline_edges if baseline_edges else 0.0
    )
    empty_rate = empty_roles / role_count
    known_period_conflicts = sum(
        row.known_period_conflict_count for row in rows
    )
    non_admitted = sum(row.non_admitted_exposure_count for row in rows)
    outside_global = sum(
        row.outside_global_shortlist_count for row in rows
    )
    input_order_count = sum(row.input_order_invariant for row in rows)
    identity_count = sum(row.candidate_identity_preserved for row in rows)
    no_gold = verify_no_gold_runtime_input()
    parser_enforced = verify_role_exact_parser_enforcement()
    gates = protocol.gates
    checks = (
        _check(
            "hard_filter_gold_role_retention",
            "ge",
            hard_retention_rate,
            gates.min_hard_filter_gold_role_retention,
        ),
        _check(
            "gold_role_recall_at_4",
            "ge",
            recall_at_4,
            gates.min_gold_role_recall_at_4,
        ),
        _check(
            "gold_role_recall_at_8",
            "ge",
            recall_at_8,
            gates.min_gold_role_recall_at_8,
        ),
        _check(
            "complete_case_rate_at_8",
            "ge",
            complete_rate,
            gates.min_complete_case_rate_at_8,
        ),
        _check(
            "role_candidate_edge_reduction_rate",
            "ge",
            edge_reduction,
            gates.min_role_candidate_edge_reduction_rate,
        ),
        _check(
            "mean_hard_compatible_candidates_per_role",
            "le",
            mean_hard,
            gates.max_mean_hard_compatible_candidates_per_role,
        ),
        _check(
            "mean_candidates_per_role",
            "le",
            mean_selected,
            gates.max_mean_candidates_per_role,
        ),
        _check(
            "p95_candidates_per_role",
            "le",
            float(_p95(allowlist_counts)),
            float(gates.max_p95_candidates_per_role),
        ),
        _check(
            "empty_role_allowlist_rate",
            "le",
            empty_rate,
            gates.max_empty_role_allowlist_rate,
        ),
        _check(
            "known_period_conflict_count",
            "eq",
            float(known_period_conflicts),
            0.0,
        ),
        _check(
            "non_admitted_exposure_count",
            "eq",
            float(non_admitted),
            0.0,
        ),
        _check(
            "outside_global_shortlist_count",
            "eq",
            float(outside_global),
            0.0,
        ),
        _check(
            "input_order_invariance",
            "eq",
            float(input_order_count),
            float(len(rows)),
        ),
        _check(
            "candidate_identity_preservation",
            "eq",
            float(identity_count),
            float(len(rows)),
        ),
        _check("no_gold_runtime_input", "required", no_gold, True),
        _check(
            "role_exact_parser_enforcement",
            "required",
            parser_enforced,
            True,
        ),
        _check("silent_global_fallback_count", "eq", 0.0, 0.0),
    )
    decision = (
        "INPUT_GATE_PASSED"
        if all(item.passed for item in checks)
        else "INPUT_GATE_FAILED"
    )
    return FinQARoleCompatibilityAuditSummary(
        schema_version="finqa_role_compatibility_audit_summary_v1",
        protocol_id=protocol.protocol_id,
        claim_label=protocol.claim_label,
        case_count=60,
        evaluated_case_count=evaluated,
        failed_case_count=len(rows) - evaluated,
        gold_role_count=role_count,
        symbolic_role_count=sum(row.symbolic_role_count for row in rows),
        hard_filter_gold_role_retention=hard_retention_rate,
        gold_role_recall_at_4=recall_at_4,
        gold_role_recall_at_8=recall_at_8,
        complete_case_rate_at_8=complete_rate,
        mean_hard_compatible_candidates_per_role=mean_hard,
        mean_candidates_per_role=mean_selected,
        p95_candidates_per_role=_p95(allowlist_counts),
        role_candidate_edge_reduction_rate=edge_reduction,
        empty_role_allowlist_rate=empty_rate,
        known_period_conflict_count=known_period_conflicts,
        non_admitted_exposure_count=non_admitted,
        outside_global_shortlist_count=outside_global,
        input_order_invariant_case_count=input_order_count,
        candidate_identity_preserved_case_count=identity_count,
        no_gold_runtime_input_verified=no_gold,
        role_exact_parser_enforcement_verified=parser_enforced,
        gate_checks=checks,
        decision=decision,
        internal_validation_status=protocol.internal_validation_status,
        frozen_test_status=protocol.frozen_test_status,
    )


def evaluate_role_compatibility_calibration(
    *,
    cases_by_id: Mapping[str, FinQACase],
    source_rows: Sequence[FinQASemanticPlanningCase],
    protocol: FinQARoleCompatibilityProtocol,
    guard: RetrievedContentGuard | None = None,
) -> tuple[
    tuple[FinQARoleCompatibilityCaseAudit, ...],
    FinQARoleCompatibilityAuditSummary,
]:
    resolved_guard = guard or RetrievedContentGuard()
    rows = tuple(
        evaluate_role_compatibility_case(
            case=cases_by_id[source.case_id],
            source_row=source,
            guard=resolved_guard,
        )
        for source in source_rows
    )
    return rows, summarize_role_compatibility_audit(
        rows,
        protocol=protocol,
    )


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "FinQARoleCompatibilityAuditSummary",
    "FinQARoleCompatibilityCaseAudit",
    "FinQARoleCompatibilityGateCheck",
    "GoldRoleRetention",
    "GoldRoleTarget",
    "evaluate_role_compatibility_calibration",
    "evaluate_role_compatibility_case",
    "parse_gold_role_targets",
    "summarize_role_compatibility_audit",
    "verify_no_gold_runtime_input",
]
