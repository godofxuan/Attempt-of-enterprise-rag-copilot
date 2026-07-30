from __future__ import annotations

import json
import time
from collections.abc import Sequence

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_eval import (
    FinQAAnswerResult,
    evaluate_finqa_case,
)
from app.external_datasets.finqa_numeric_evidence_shortlist_v2 import (
    question_conditioned_numeric_evidence_shortlist_v2,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    NumericCandidateV2,
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
    SemanticInterventionArmId,
)
from app.external_datasets.finqa_semantic_demos import (
    FinQAStructuralDemo,
    FinQAStructuralDemoIndex,
    demonstration_payload_sha256,
)
from app.external_datasets.finqa_semantic_planner import (
    LocalFinQASemanticPlanner,
    SemanticPlannerProtocolError,
    SemanticPlannerResult,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    FinancialQuestionIntentV2,
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_program import (
    TypedProgramValidationError,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedArmEvaluation,
    arm_evaluation_from_case,
    refused_arm_evaluation,
)
from app.external_datasets.finqa_v23_calibration_run import (
    FinQAV23CalibrationCase,
)
from app.security.retrieved_content import RetrievedContentGuard


def _bounded_failure_reason(error: ValueError) -> str:
    message = str(error).casefold()
    if "candidate budget" in message:
        return "candidate_budget_exceeded"
    if "context budget" in message or "prompt budget" in message:
        return "prompt_budget_exceeded"
    if "too few" in message or "no usable tokens" in message:
        return "dynamic_demo_retrieval_failed"
    if "no operand" in message:
        return "no_admitted_operand_candidate"
    return "semantic_precondition_failed"


def _evaluate_planner_result(
    *,
    case: FinQACase,
    planned: SemanticPlannerResult,
    candidate_count: int,
    admitted_unit_ids: tuple[str, ...],
    quarantined_unit_ids: tuple[str, ...],
    guard_rule_ids: tuple[str, ...],
) -> FinQATypedArmEvaluation:
    units = {unit.unit_id: unit for unit in build_finqa_evidence_units(case)}
    evidence = tuple(units[unit_id] for unit_id in admitted_unit_ids)
    answer = FinQAAnswerResult(
        final_answer=format(planned.execution.value, "f"),
        calculation=json.dumps(
            planned.program.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        cited_unit_ids=planned.execution.evidence_ids,
        provided_unit_ids=admitted_unit_ids,
        admitted_count=len(evidence),
        quarantined_count=len(quarantined_unit_ids),
        guard_rule_ids=guard_rule_ids,
        attempt_count=planned.generation_calls,
        latency_ms=planned.latency_ms,
        calculator_calls=planned.execution.diagnostics.step_count,
    )
    evaluation = evaluate_finqa_case(
        case,
        retrieval_mode="hybrid",
        selected_units=evidence,
        answer=answer,
    )
    return arm_evaluation_from_case(
        arm_id="B2_TYPED_MULTI",
        evaluation=evaluation,
        compiler_calls=planned.compiler_calls,
        generated_program_count=1,
        candidate_count=candidate_count,
        selected_program_sha256=planned.execution.program_sha256,
        selected_support_count=1,
        valid_program_count=1,
    )


def _run_arm(
    *,
    arm_id: SemanticInterventionArmId,
    case: FinQACase,
    planner: LocalFinQASemanticPlanner,
    candidates: Sequence[NumericCandidateV2],
    admitted_unit_ids: tuple[str, ...],
    quarantined_unit_ids: tuple[str, ...],
    guard_rule_ids: tuple[str, ...],
    intent: FinancialQuestionIntentV2,
    evidence_context_by_id: dict[str, str],
    demonstrations: Sequence[FinQAStructuralDemo] = (),
) -> tuple[FinQATypedArmEvaluation, SemanticPlannerResult | None]:
    started = time.perf_counter()
    try:
        if arm_id == "B2_MULTI_STEP_DIRECT":
            planned = planner.plan_direct(
                question=case.qa.question,
                candidates=candidates,
                admitted_evidence_ids=set(admitted_unit_ids),
                intent=intent,
                evidence_context_by_id=evidence_context_by_id,
            )
        else:
            planned = planner.plan_decomposed(
                question=case.qa.question,
                candidates=candidates,
                admitted_evidence_ids=set(admitted_unit_ids),
                intent=intent,
                evidence_context_by_id=evidence_context_by_id,
                demonstrations=demonstrations,
            )
    except SemanticPlannerProtocolError as error:
        return (
            refused_arm_evaluation(
                arm_id="B2_TYPED_MULTI",
                failure_reason=f"{error.stage}:{error.reason}",
                generation_calls=error.generation_calls,
                compiler_calls=error.compiler_calls,
                generated_program_count=error.compiler_calls,
                latency_ms=error.latency_ms,
                candidate_count=len(candidates),
                status="PROTOCOL_ERROR",
                invalid_program_count=error.compiler_calls,
            ),
            None,
        )
    except TypedProgramValidationError as error:
        return (
            refused_arm_evaluation(
                arm_id="B2_TYPED_MULTI",
                failure_reason=error.reason,
                generation_calls=0,
                compiler_calls=0,
                generated_program_count=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                candidate_count=len(candidates),
            ),
            None,
        )
    return (
        _evaluate_planner_result(
            case=case,
            planned=planned,
            candidate_count=len(candidates),
            admitted_unit_ids=admitted_unit_ids,
            quarantined_unit_ids=quarantined_unit_ids,
            guard_rule_ids=guard_rule_ids,
        ),
        planned,
    )


def evaluate_semantic_case(
    *,
    case: FinQACase,
    source_e4: FinQAV23CalibrationCase,
    planner: LocalFinQASemanticPlanner,
    demo_index: FinQAStructuralDemoIndex,
    arm_order: tuple[
        SemanticInterventionArmId,
        SemanticInterventionArmId,
        SemanticInterventionArmId,
    ],
    demo_count: int = 3,
    guard: RetrievedContentGuard | None = None,
) -> FinQASemanticPlanningCase:
    if not (
        case.id == source_e4.case_id
        and set(arm_order)
        == {
            "B2_MULTI_STEP_DIRECT",
            "B3_ROLE_DECOMPOSED",
            "B4_ROLE_DYNAMIC_DEMOS",
        }
    ):
        raise ValueError("semantic runtime source or arm order is invalid")
    resolved_guard = guard or RetrievedContentGuard()
    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=source_e4.selected_unit_ids,
    )
    admission = admit_finqa_numeric_evidence_closure_v2(
        case,
        closure=closure,
        guard=resolved_guard,
    )
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
    guard_rule_ids = tuple(
        sorted(
            {
                rule_id
                for decision in admission.decision_by_unit_id.values()
                for rule_id in decision.rule_ids
            }
        )
    )
    shortlist_started = time.perf_counter()
    try:
        shortlist = question_conditioned_numeric_evidence_shortlist_v2(
            question=case.qa.question,
            candidates=corpus.candidates,
            admitted_evidence_ids=admitted_ids,
            intent=intent,
            evidence_context_by_id=context,
        )
    except ValueError as error:
        shortlist = ()
        refusal = refused_arm_evaluation(
            arm_id="B2_TYPED_MULTI",
            failure_reason=_bounded_failure_reason(error),
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - shortlist_started) * 1000,
            candidate_count=len(corpus.candidates),
        )
        results = {arm_id: refusal for arm_id in arm_order}
        demo_payload_sha256 = None
        retrieved_demo_count = 0
    else:
        results: dict[SemanticInterventionArmId, FinQATypedArmEvaluation] = {}
        demo_payload_sha256 = None
        retrieved_demo_count = 0
        demos: tuple[FinQAStructuralDemo, ...] = ()
        for arm_id in arm_order:
            if arm_id == "B4_ROLE_DYNAMIC_DEMOS":
                try:
                    demos = demo_index.retrieve(
                        case.qa.question,
                        top_k=demo_count,
                    )
                except ValueError as error:
                    results[arm_id] = refused_arm_evaluation(
                        arm_id="B2_TYPED_MULTI",
                        failure_reason=_bounded_failure_reason(error),
                        generation_calls=0,
                        compiler_calls=0,
                        generated_program_count=0,
                        latency_ms=0,
                        candidate_count=len(shortlist),
                    )
                    continue
                retrieved_demo_count = len(demos)
                demo_payload_sha256 = demonstration_payload_sha256(demos)
            result, planned = _run_arm(
                arm_id=arm_id,
                case=case,
                planner=planner,
                candidates=shortlist,
                admitted_unit_ids=admission.admitted_unit_ids,
                quarantined_unit_ids=admission.quarantined_unit_ids,
                guard_rule_ids=guard_rule_ids,
                intent=intent,
                evidence_context_by_id=context,
                demonstrations=demos if arm_id == "B4_ROLE_DYNAMIC_DEMOS" else (),
            )
            results[arm_id] = result
            if arm_id == "B4_ROLE_DYNAMIC_DEMOS" and planned is not None:
                if (
                    planned.demonstration_count != retrieved_demo_count
                    or planned.demonstration_payload_sha256
                    != demo_payload_sha256
                ):
                    raise ValueError("dynamic demo accounting mismatch")
    return FinQASemanticPlanningCase(
        case_id=case.id,
        diagnostic_category=source_e4.diagnostic_category,
        selected_unit_ids=tuple(source_e4.selected_unit_ids),
        admitted_closure_unit_ids=admission.admitted_unit_ids,
        gold_unit_ids=tuple(source_e4.gold_unit_ids),
        candidate_count_before_shortlist=len(corpus.candidates),
        candidate_count_after_shortlist=len(shortlist),
        guard_scan_count=admission.scan_count,
        quarantined_unit_count=len(admission.quarantined_unit_ids),
        arm_order=arm_order,
        b4_demo_count=retrieved_demo_count,
        b4_demo_payload_sha256=demo_payload_sha256,
        b0_stored=source_e4.b0_stored,
        b1_v23_stored=source_e4.b1_v23_intervention,
        b2_direct=results["B2_MULTI_STEP_DIRECT"],
        b3_roles=results["B3_ROLE_DECOMPOSED"],
        b4_dynamic_demos=results["B4_ROLE_DYNAMIC_DEMOS"],
    )


__all__ = ["evaluate_semantic_case"]
