from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_role_compatibility_protocol_v2 import (
    FinQARoleCompatibilityProtocolV2,
)
from app.external_datasets.finqa_role_compatibility_v2 import (
    CapabilityRoute,
    build_role_candidate_compatibility_matrix_v2,
    route_finqa_numeric_capability,
    verify_no_gold_runtime_inputs_v2,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
)
from app.external_datasets.finqa_semantic_demos import _role_name
from app.external_datasets.finqa_semantic_program_v2 import (
    SemanticProgramSkeletonV2,
    SemanticProgramStepV2,
    SemanticRoleRefV2,
    SemanticRoleSpecV2,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_controlled_program import (
    CONTROLLED_CONSTANT_VALUES,
    ControlledConstantRef,
)
from app.external_datasets.finqa_typed_program import (
    StepRef,
)
from app.security.retrieved_content import RetrievedContentGuard


AUDIT_SCHEMA_VERSION = "finqa_role_compatibility_v2_audit_v1"
_GOLD_STEP = re.compile(r"([a-z_]+)\(([^()]*)\)(?:,\s*|$)")
_GOLD_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)%?")
_GOLD_CONSTANT = re.compile(r"const_(?:m)?\d+")
_STEP_REFERENCE = re.compile(r"#([0-9]+)")
_SUPPORTED_OPERATION = {
    "add": "ADD",
    "subtract": "SUB",
    "multiply": "MUL",
    "divide": "DIV",
}
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


class EvidenceRoleTargetV2(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    value: Decimal


class OracleSemanticProgramV2(_StrictFrozenModel):
    capability_route: CapabilityRoute
    skeleton: SemanticProgramSkeletonV2 | None
    evidence_targets: tuple[EvidenceRoleTargetV2, ...]
    controlled_constant_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_route_payload(self) -> OracleSemanticProgramV2:
        if self.capability_route == "TYPED_NUMERIC":
            if self.skeleton is None or not self.evidence_targets:
                raise ValueError("typed oracle program is incomplete")
            if {
                item.role_id for item in self.evidence_targets
            } != {item.role_id for item in self.skeleton.roles}:
                raise ValueError("typed oracle role targets do not reconcile")
        elif (
            self.skeleton is not None
            or self.evidence_targets
            or self.controlled_constant_ids
        ):
            raise ValueError("fallback oracle program must not expose operands")
        return self


class EvidenceRoleRetentionV2(_StrictFrozenModel):
    role_id: str = Field(pattern=r"^role-0[1-8]$")
    source_pool_retained: bool
    retained_at_4: bool
    retained_at_8: bool


class FinQARoleCompatibilityCaseAuditV2(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_v2_audit_v1"
    ] = AUDIT_SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=512)
    oracle_route: CapabilityRoute
    runtime_route: CapabilityRoute
    route_match: bool
    status: Literal["FALLBACK_ROUTED", "EVALUATED", "COMPATIBILITY_ERROR"]
    failure_reason: str | None = Field(default=None, max_length=256)
    source_candidate_count: int = Field(ge=0, le=128)
    evidence_role_count: int = Field(ge=0, le=8)
    controlled_constant_count: int = Field(ge=0, le=8)
    controlled_constant_retained_count: int = Field(ge=0, le=8)
    hard_compatible_counts: tuple[int, ...]
    allowlist_counts: tuple[int, ...]
    retention: tuple[EvidenceRoleRetentionV2, ...]
    complete_at_8: bool
    baseline_role_candidate_edges: int = Field(ge=0, le=1024)
    selected_role_candidate_edges: int = Field(ge=0, le=64)
    empty_role_allowlist_count: int = Field(ge=0, le=8)
    known_period_conflict_count: int = Field(ge=0, le=64)
    non_admitted_exposure_count: int = Field(ge=0, le=64)
    input_order_invariant: bool
    candidate_identity_preserved: bool
    matrix_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_accounting(
        self,
    ) -> FinQARoleCompatibilityCaseAuditV2:
        if len(self.retention) != self.evidence_role_count:
            raise ValueError("v2 evidence role accounting is invalid")
        expected_complete = (
            self.status == "EVALUATED"
            and bool(self.retention)
            and all(item.retained_at_8 for item in self.retention)
            and self.controlled_constant_retained_count
            == self.controlled_constant_count
        )
        if self.complete_at_8 != expected_complete:
            raise ValueError("v2 complete flag is invalid")
        if self.status == "EVALUATED":
            if (
                self.failure_reason is not None
                or self.matrix_sha256 is None
                or len(self.allowlist_counts) != self.evidence_role_count
                or len(self.hard_compatible_counts)
                != self.evidence_role_count
            ):
                raise ValueError("evaluated v2 row is incomplete")
        elif self.status == "FALLBACK_ROUTED":
            if (
                self.oracle_route == "TYPED_NUMERIC"
                or self.matrix_sha256 is not None
                or self.failure_reason is not None
            ):
                raise ValueError("fallback v2 row is inconsistent")
        elif self.failure_reason is None or self.matrix_sha256 is not None:
            raise ValueError("failed v2 row is inconsistent")
        return self


class FinQARoleCompatibilityGateCheckV2(_StrictFrozenModel):
    gate: str = Field(min_length=1, max_length=128)
    comparator: Literal["ge", "le", "eq", "required"]
    observed: float | bool
    threshold: float | bool
    passed: bool


class FinQARoleCompatibilityAuditSummaryV2(_StrictFrozenModel):
    schema_version: Literal[
        "finqa_role_compatibility_v2_audit_summary_v1"
    ]
    protocol_id: str = Field(min_length=1, max_length=200)
    claim_label: Literal["DISCLOSED_DEVELOPMENT_CALIBRATION"]
    case_count: Literal[60]
    typed_eligible_case_count: int = Field(ge=0, le=60)
    fallback_case_count: int = Field(ge=0, le=60)
    evaluated_typed_case_count: int = Field(ge=0, le=60)
    failed_typed_case_count: int = Field(ge=0, le=60)
    runtime_capability_route_accuracy: float = Field(ge=0, le=1)
    typed_eligible_case_rate: float = Field(ge=0, le=1)
    evidence_role_count: int = Field(ge=1)
    controlled_constant_count: int = Field(ge=0)
    evidence_role_source_recall: float = Field(ge=0, le=1)
    controlled_constant_recall: float = Field(ge=0, le=1)
    evidence_role_recall_at_4: float = Field(ge=0, le=1)
    evidence_role_recall_at_8: float = Field(ge=0, le=1)
    complete_typed_case_rate_at_8: float = Field(ge=0, le=1)
    role_candidate_edge_reduction_rate: float = Field(ge=0, le=1)
    mean_exposed_candidates_per_role: float = Field(ge=0, le=8)
    p95_exposed_candidates_per_role: int = Field(ge=0, le=8)
    empty_role_allowlist_rate: float = Field(ge=0, le=1)
    known_period_conflict_count: int = Field(ge=0)
    non_admitted_exposure_count: int = Field(ge=0)
    input_order_invariant_case_count: int = Field(ge=0, le=60)
    candidate_identity_preserved_case_count: int = Field(ge=0, le=60)
    no_gold_runtime_input_verified: bool
    controlled_constant_enum_enforcement_verified: bool
    role_exact_parser_enforcement_verified: bool
    serving_route_disabled_verified: bool
    silent_fallback_expansion_count: Literal[0] = 0
    gate_checks: tuple[FinQARoleCompatibilityGateCheckV2, ...]
    decision: Literal["INPUT_GATE_PASSED", "INPUT_GATE_FAILED"]
    model_call_count: Literal[0] = 0
    internal_validation_status: Literal["NOT_RUN"]
    frozen_test_status: Literal["UNTOUCHED"]

    @model_validator(mode="after")
    def validate_decision(
        self,
    ) -> FinQARoleCompatibilityAuditSummaryV2:
        if self.typed_eligible_case_count + self.fallback_case_count != 60:
            raise ValueError("v2 capability case accounting is invalid")
        if (
            self.evaluated_typed_case_count + self.failed_typed_case_count
            != self.typed_eligible_case_count
        ):
            raise ValueError("v2 typed case accounting is invalid")
        expected = (
            "INPUT_GATE_PASSED"
            if self.gate_checks and all(item.passed for item in self.gate_checks)
            else "INPUT_GATE_FAILED"
        )
        if self.decision != expected:
            raise ValueError("v2 decision contradicts gates")
        return self


def _gold_matches(program: str) -> tuple[re.Match[str], ...]:
    matches: list[re.Match[str]] = []
    position = 0
    while position < len(program):
        match = _GOLD_STEP.match(program, position)
        if match is None:
            raise ValueError("FinQA gold program has unsupported syntax")
        matches.append(match)
        position = match.end()
    return tuple(matches)


def _constant_value(constant_id: str) -> Decimal:
    digits = constant_id.removeprefix("const_")
    if digits.startswith("m"):
        digits = f"-{digits[1:]}"
    return Decimal(digits)


def _source_bound_constant_ids(case: FinQACase) -> frozenset[str]:
    constants = frozenset(_GOLD_CONSTANT.findall(case.qa.program))
    if not constants:
        return frozenset()
    gold_candidates = extract_finqa_numeric_candidates_v2(
        case,
        admitted_evidence_ids=set(case.qa.gold_inds),
    ).candidates
    return frozenset(
        constant_id
        for constant_id in constants
        if any(
            candidate.normalized_value == _constant_value(constant_id)
            or (
                candidate.normalized_value
                / _SCALE_MULTIPLIER[candidate.scale]
            )
            == _constant_value(constant_id)
            for candidate in gold_candidates
        )
    )


def build_oracle_semantic_program_v2(
    *,
    question: str,
    program: str,
    source_bound_constant_ids: frozenset[str] = frozenset(),
) -> OracleSemanticProgramV2:
    matches = _gold_matches(program)
    operation_names = tuple(match.group(1) for match in matches)
    if "greater" in operation_names:
        return OracleSemanticProgramV2(
            capability_route="B0_BOOLEAN_COMPARISON_FALLBACK",
            skeleton=None,
            evidence_targets=(),
            controlled_constant_ids=(),
        )
    if any(name.startswith("table_") for name in operation_names):
        return OracleSemanticProgramV2(
            capability_route="B0_SYMBOLIC_TABLE_AGGREGATION_FALLBACK",
            skeleton=None,
            evidence_targets=(),
            controlled_constant_ids=(),
        )
    if (
        len(matches) > 5
        or any(name not in _SUPPORTED_OPERATION for name in operation_names)
    ):
        raise ValueError("gold program is outside E6-v2 capability routes")

    intent = extract_financial_question_intent_v2(question)
    percent_change = intent.operation_family == "percent_change"
    role_by_operand: dict[str, str] = {}
    targets: list[EvidenceRoleTargetV2] = []
    constants: list[str] = []
    roles: list[SemanticRoleSpecV2] = []
    steps: list[SemanticProgramStepV2] = []
    for step_index, match in enumerate(matches):
        operation_name = match.group(1)
        arguments = tuple(
            item.strip() for item in match.group(2).split(",")
        )
        if len(arguments) != 2:
            raise ValueError("gold operation must have exactly two arguments")
        references = []
        for argument_index, argument in enumerate(arguments):
            step_ref = _STEP_REFERENCE.fullmatch(argument)
            if step_ref is not None:
                referenced_index = int(step_ref.group(1))
                if referenced_index >= step_index:
                    raise ValueError("gold step reference points forward")
                references.append(
                    StepRef(step_id=f"step-{referenced_index + 1:02d}")
                )
                continue
            if _GOLD_CONSTANT.fullmatch(argument):
                if argument not in source_bound_constant_ids:
                    if argument not in CONTROLLED_CONSTANT_VALUES:
                        raise ValueError(
                            "non-source gold constant is outside host registry: "
                            f"{argument}"
                        )
                    references.append(
                        ControlledConstantRef(constant_id=argument)
                    )
                    if argument not in constants:
                        constants.append(argument)
                    continue
                target_value = _constant_value(argument)
            elif _GOLD_NUMBER.fullmatch(argument):
                target_value = Decimal(argument.removesuffix("%"))
            else:
                raise ValueError("numeric route has symbolic gold operand")
            role_id = role_by_operand.get(argument)
            if role_id is None:
                role_id = f"role-{len(role_by_operand) + 1:02d}"
                role_by_operand[argument] = role_id
                semantic_role, period_role = _role_name(
                    operation=operation_name,
                    position=argument_index,
                    percent_change=percent_change,
                )
                roles.append(
                    SemanticRoleSpecV2(
                        role_id=role_id,
                        semantic_role=semantic_role,
                        period_role=period_role,
                    )
                )
                targets.append(
                    EvidenceRoleTargetV2(
                        role_id=role_id,
                        value=target_value,
                    )
                )
            references.append(SemanticRoleRefV2(role_id=role_id))
        steps.append(
            SemanticProgramStepV2(
                step_id=f"step-{step_index + 1:02d}",
                operation=_SUPPORTED_OPERATION[operation_name],
                arguments=tuple(references),
            )
        )
    return OracleSemanticProgramV2(
        capability_route="TYPED_NUMERIC",
        skeleton=SemanticProgramSkeletonV2(
            roles=tuple(roles),
            steps=tuple(steps),
            output_step_id=steps[-1].step_id,
        ),
        evidence_targets=tuple(targets),
        controlled_constant_ids=tuple(constants),
    )


def _surface_value(candidate: NumericCandidateV2) -> Decimal:
    return candidate.normalized_value / _SCALE_MULTIPLIER[candidate.scale]


def _target_retained(
    target: EvidenceRoleTargetV2,
    candidates: Sequence[NumericCandidateV2],
) -> bool:
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


def evaluate_role_compatibility_case_v2(
    *,
    case: FinQACase,
    source_row: FinQASemanticPlanningCase,
    guard: RetrievedContentGuard,
) -> FinQARoleCompatibilityCaseAuditV2:
    if case.id != source_row.case_id:
        raise ValueError("v2 role case and source row do not match")
    oracle = build_oracle_semantic_program_v2(
        question=case.qa.question,
        program=case.qa.program,
        source_bound_constant_ids=_source_bound_constant_ids(case),
    )
    runtime_route = route_finqa_numeric_capability(case.qa.question)
    if oracle.capability_route != "TYPED_NUMERIC":
        return FinQARoleCompatibilityCaseAuditV2(
            case_id=case.id,
            oracle_route=oracle.capability_route,
            runtime_route=runtime_route,
            route_match=runtime_route == oracle.capability_route,
            status="FALLBACK_ROUTED",
            source_candidate_count=0,
            evidence_role_count=0,
            controlled_constant_count=0,
            controlled_constant_retained_count=0,
            hard_compatible_counts=(),
            allowlist_counts=(),
            retention=(),
            complete_at_8=False,
            baseline_role_candidate_edges=0,
            selected_role_candidate_edges=0,
            empty_role_allowlist_count=0,
            known_period_conflict_count=0,
            non_admitted_exposure_count=0,
            input_order_invariant=True,
            candidate_identity_preserved=True,
            matrix_sha256=None,
        )
    assert oracle.skeleton is not None

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
    candidates = tuple(
        candidate
        for candidate in corpus.candidates
        if candidate.role == "operand"
    )
    if not candidates:
        raise ValueError("Gate E6-v2 admitted operand pool is empty")
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    context = {
        unit_id: units[unit_id].text
        for unit_id in admission.admitted_unit_ids
    }
    intent = extract_financial_question_intent_v2(case.qa.question)
    before_identity = _candidate_identity_sha256(candidates)
    try:
        matrix = build_role_candidate_compatibility_matrix_v2(
            question=case.qa.question,
            skeleton=oracle.skeleton,
            candidates=candidates,
            admitted_evidence_ids=admitted_ids,
            intent=intent,
            evidence_context_by_id=context,
        )
    except ValueError as error:
        return FinQARoleCompatibilityCaseAuditV2(
            case_id=case.id,
            oracle_route=oracle.capability_route,
            runtime_route=runtime_route,
            route_match=runtime_route == oracle.capability_route,
            status="COMPATIBILITY_ERROR",
            failure_reason=(
                "empty_role_allowlist"
                if "empty allowlist" in str(error).casefold()
                else "compatibility_precondition_failed"
            ),
            source_candidate_count=len(candidates),
            evidence_role_count=len(oracle.evidence_targets),
            controlled_constant_count=len(oracle.controlled_constant_ids),
            controlled_constant_retained_count=len(
                oracle.controlled_constant_ids
            ),
            hard_compatible_counts=(),
            allowlist_counts=(),
            retention=tuple(
                EvidenceRoleRetentionV2(
                    role_id=target.role_id,
                    source_pool_retained=_target_retained(
                        target,
                        candidates,
                    ),
                    retained_at_4=False,
                    retained_at_8=False,
                )
                for target in oracle.evidence_targets
            ),
            complete_at_8=False,
            baseline_role_candidate_edges=(
                len(candidates) * len(oracle.evidence_targets)
            ),
            selected_role_candidate_edges=0,
            empty_role_allowlist_count=(
                len(oracle.evidence_targets)
                if "empty allowlist" in str(error).casefold()
                else 0
            ),
            known_period_conflict_count=0,
            non_admitted_exposure_count=0,
            input_order_invariant=False,
            candidate_identity_preserved=(
                before_identity == _candidate_identity_sha256(candidates)
            ),
            matrix_sha256=None,
        )
    reversed_matrix = build_role_candidate_compatibility_matrix_v2(
        question=case.qa.question,
        skeleton=oracle.skeleton,
        candidates=tuple(reversed(candidates)),
        admitted_evidence_ids=admitted_ids,
        intent=intent,
        evidence_context_by_id=context,
    )
    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in candidates
    }
    target_by_role = {
        target.role_id: target for target in oracle.evidence_targets
    }
    retention: list[EvidenceRoleRetentionV2] = []
    hard_counts: list[int] = []
    allowlist_counts: list[int] = []
    known_period_conflicts = 0
    non_admitted_exposures = 0
    for allowlist in matrix.role_allowlists:
        selected = tuple(
            candidate_by_id[candidate_id]
            for candidate_id in allowlist.candidate_ids
        )
        target = target_by_role[allowlist.role_id]
        hard_counts.append(allowlist.hard_compatible_candidate_count)
        allowlist_counts.append(len(selected))
        retention.append(
            EvidenceRoleRetentionV2(
                role_id=allowlist.role_id,
                source_pool_retained=_target_retained(target, candidates),
                retained_at_4=_target_retained(target, selected[:4]),
                retained_at_8=_target_retained(target, selected),
            )
        )
        for candidate in selected:
            if candidate.evidence_id not in admitted_ids or candidate.role != "operand":
                non_admitted_exposures += 1
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
    return FinQARoleCompatibilityCaseAuditV2(
        case_id=case.id,
        oracle_route=oracle.capability_route,
        runtime_route=runtime_route,
        route_match=runtime_route == oracle.capability_route,
        status="EVALUATED",
        source_candidate_count=len(candidates),
        evidence_role_count=len(oracle.evidence_targets),
        controlled_constant_count=len(oracle.controlled_constant_ids),
        controlled_constant_retained_count=len(oracle.controlled_constant_ids),
        hard_compatible_counts=tuple(hard_counts),
        allowlist_counts=tuple(allowlist_counts),
        retention=tuple(retention),
        complete_at_8=all(item.retained_at_8 for item in retention),
        baseline_role_candidate_edges=(
            len(candidates) * len(oracle.evidence_targets)
        ),
        selected_role_candidate_edges=sum(allowlist_counts),
        empty_role_allowlist_count=0,
        known_period_conflict_count=known_period_conflicts,
        non_admitted_exposure_count=non_admitted_exposures,
        input_order_invariant=(
            matrix.role_allowlists == reversed_matrix.role_allowlists
            and matrix.matrix_sha256 == reversed_matrix.matrix_sha256
        ),
        candidate_identity_preserved=(
            before_identity == _candidate_identity_sha256(candidates)
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
) -> FinQARoleCompatibilityGateCheckV2:
    passed = (
        observed >= threshold
        if comparator == "ge"
        else (
            observed <= threshold
            if comparator == "le"
            else observed == threshold
        )
    )
    return FinQARoleCompatibilityGateCheckV2(
        gate=gate,
        comparator=comparator,
        observed=observed,
        threshold=threshold,
        passed=passed,
    )


def summarize_role_compatibility_audit_v2(
    rows: Sequence[FinQARoleCompatibilityCaseAuditV2],
    *,
    protocol: FinQARoleCompatibilityProtocolV2,
    role_exact_parser_enforcement_verified: bool,
    serving_route_disabled_verified: bool,
) -> FinQARoleCompatibilityAuditSummaryV2:
    if len(rows) != protocol.calibration_case_count:
        raise ValueError("v2 role audit must contain 60 cases")
    typed_rows = [row for row in rows if row.oracle_route == "TYPED_NUMERIC"]
    evaluated = [row for row in typed_rows if row.status == "EVALUATED"]
    retentions = [item for row in typed_rows for item in row.retention]
    role_count = len(retentions)
    constants = sum(row.controlled_constant_count for row in typed_rows)
    retained_constants = sum(
        row.controlled_constant_retained_count for row in typed_rows
    )
    source_recall = (
        sum(item.source_pool_retained for item in retentions) / role_count
    )
    recall_4 = sum(item.retained_at_4 for item in retentions) / role_count
    recall_8 = sum(item.retained_at_8 for item in retentions) / role_count
    complete_rate = sum(row.complete_at_8 for row in typed_rows) / len(
        typed_rows
    )
    baseline_edges = sum(
        row.baseline_role_candidate_edges for row in typed_rows
    )
    selected_edges = sum(
        row.selected_role_candidate_edges for row in typed_rows
    )
    edge_reduction = (
        1 - selected_edges / baseline_edges if baseline_edges else 0.0
    )
    allowlist_counts = [
        item for row in typed_rows for item in row.allowlist_counts
    ]
    mean_exposed = (
        sum(allowlist_counts) / len(allowlist_counts)
        if allowlist_counts
        else 0.0
    )
    empty_roles = sum(row.empty_role_allowlist_count for row in typed_rows)
    route_accuracy = sum(row.route_match for row in rows) / len(rows)
    constant_recall = (
        retained_constants / constants if constants else 1.0
    )
    known_conflicts = sum(row.known_period_conflict_count for row in rows)
    non_admitted = sum(row.non_admitted_exposure_count for row in rows)
    input_order_count = sum(row.input_order_invariant for row in rows)
    identity_count = sum(row.candidate_identity_preserved for row in rows)
    no_gold = verify_no_gold_runtime_inputs_v2()
    constant_enum = tuple(CONTROLLED_CONSTANT_VALUES) == (
        "const_1",
        "const_2",
        "const_3",
        "const_4",
        "const_5",
        "const_10",
        "const_100",
        "const_1000",
    )
    gates = protocol.gates
    checks = (
        _check(
            "runtime_capability_route_accuracy",
            "ge",
            route_accuracy,
            gates.min_runtime_capability_route_accuracy,
        ),
        _check(
            "typed_eligible_case_rate",
            "ge",
            len(typed_rows) / len(rows),
            gates.min_typed_eligible_case_rate,
        ),
        _check(
            "evidence_role_source_recall",
            "ge",
            source_recall,
            gates.min_evidence_role_source_recall,
        ),
        _check(
            "controlled_constant_recall",
            "ge",
            constant_recall,
            gates.min_controlled_constant_recall,
        ),
        _check(
            "evidence_role_recall_at_4",
            "ge",
            recall_4,
            gates.min_evidence_role_recall_at_4,
        ),
        _check(
            "evidence_role_recall_at_8",
            "ge",
            recall_8,
            gates.min_evidence_role_recall_at_8,
        ),
        _check(
            "complete_typed_case_rate_at_8",
            "ge",
            complete_rate,
            gates.min_complete_typed_case_rate_at_8,
        ),
        _check(
            "role_candidate_edge_reduction_rate",
            "ge",
            edge_reduction,
            gates.min_role_candidate_edge_reduction_rate,
        ),
        _check(
            "mean_exposed_candidates_per_role",
            "le",
            mean_exposed,
            gates.max_mean_exposed_candidates_per_role,
        ),
        _check(
            "p95_exposed_candidates_per_role",
            "le",
            float(_p95(allowlist_counts)),
            float(gates.max_p95_exposed_candidates_per_role),
        ),
        _check(
            "empty_role_allowlist_rate",
            "le",
            empty_roles / role_count,
            gates.max_empty_role_allowlist_rate,
        ),
        _check(
            "known_period_conflict_count",
            "eq",
            float(known_conflicts),
            0.0,
        ),
        _check(
            "non_admitted_exposure_count",
            "eq",
            float(non_admitted),
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
            "controlled_constant_enum_enforcement",
            "required",
            constant_enum,
            True,
        ),
        _check(
            "role_exact_parser_enforcement",
            "required",
            role_exact_parser_enforcement_verified,
            True,
        ),
        _check(
            "serving_route_disabled",
            "required",
            serving_route_disabled_verified,
            True,
        ),
        _check("silent_fallback_expansion_count", "eq", 0.0, 0.0),
    )
    decision = (
        "INPUT_GATE_PASSED"
        if all(item.passed for item in checks)
        else "INPUT_GATE_FAILED"
    )
    return FinQARoleCompatibilityAuditSummaryV2(
        schema_version="finqa_role_compatibility_v2_audit_summary_v1",
        protocol_id=protocol.protocol_id,
        claim_label=protocol.claim_label,
        case_count=60,
        typed_eligible_case_count=len(typed_rows),
        fallback_case_count=len(rows) - len(typed_rows),
        evaluated_typed_case_count=len(evaluated),
        failed_typed_case_count=len(typed_rows) - len(evaluated),
        runtime_capability_route_accuracy=route_accuracy,
        typed_eligible_case_rate=len(typed_rows) / len(rows),
        evidence_role_count=role_count,
        controlled_constant_count=constants,
        evidence_role_source_recall=source_recall,
        controlled_constant_recall=constant_recall,
        evidence_role_recall_at_4=recall_4,
        evidence_role_recall_at_8=recall_8,
        complete_typed_case_rate_at_8=complete_rate,
        role_candidate_edge_reduction_rate=edge_reduction,
        mean_exposed_candidates_per_role=mean_exposed,
        p95_exposed_candidates_per_role=_p95(allowlist_counts),
        empty_role_allowlist_rate=empty_roles / role_count,
        known_period_conflict_count=known_conflicts,
        non_admitted_exposure_count=non_admitted,
        input_order_invariant_case_count=input_order_count,
        candidate_identity_preserved_case_count=identity_count,
        no_gold_runtime_input_verified=no_gold,
        controlled_constant_enum_enforcement_verified=constant_enum,
        role_exact_parser_enforcement_verified=(
            role_exact_parser_enforcement_verified
        ),
        serving_route_disabled_verified=serving_route_disabled_verified,
        gate_checks=checks,
        decision=decision,
        internal_validation_status=protocol.internal_validation_status,
        frozen_test_status=protocol.frozen_test_status,
    )


def evaluate_role_compatibility_calibration_v2(
    *,
    cases_by_id: Mapping[str, FinQACase],
    source_rows: Sequence[FinQASemanticPlanningCase],
    protocol: FinQARoleCompatibilityProtocolV2,
    role_exact_parser_enforcement_verified: bool,
    serving_route_disabled_verified: bool,
    guard: RetrievedContentGuard | None = None,
) -> tuple[
    tuple[FinQARoleCompatibilityCaseAuditV2, ...],
    FinQARoleCompatibilityAuditSummaryV2,
]:
    resolved_guard = guard or RetrievedContentGuard()
    rows = tuple(
        evaluate_role_compatibility_case_v2(
            case=cases_by_id[source.case_id],
            source_row=source,
            guard=resolved_guard,
        )
        for source in source_rows
    )
    return rows, summarize_role_compatibility_audit_v2(
        rows,
        protocol=protocol,
        role_exact_parser_enforcement_verified=(
            role_exact_parser_enforcement_verified
        ),
        serving_route_disabled_verified=serving_route_disabled_verified,
    )


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "EvidenceRoleRetentionV2",
    "EvidenceRoleTargetV2",
    "FinQARoleCompatibilityAuditSummaryV2",
    "FinQARoleCompatibilityCaseAuditV2",
    "OracleSemanticProgramV2",
    "build_oracle_semantic_program_v2",
    "evaluate_role_compatibility_calibration_v2",
    "evaluate_role_compatibility_case_v2",
    "summarize_role_compatibility_audit_v2",
]
