from __future__ import annotations

import json
import time

from app.external_datasets.finqa import FinQACase, build_finqa_evidence_units
from app.external_datasets.finqa_eval import (
    FinQAAnswerResult,
    evaluate_finqa_case,
)
from app.external_datasets.finqa_numeric_evidence_shortlist_v2 import (
    question_conditioned_numeric_evidence_shortlist_v2,
)
from app.external_datasets.finqa_numeric_evidence_v2 import (
    admit_finqa_numeric_evidence_closure_v2,
    expand_finqa_numeric_evidence_v2,
    extract_finqa_numeric_candidates_v2,
)
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
)
from app.external_datasets.finqa_typed_planner import (
    TypedPlannerProtocolError,
)
from app.external_datasets.finqa_typed_planner_v2 import (
    extract_financial_question_intent_v2,
)
from app.external_datasets.finqa_typed_planner_v23 import (
    LocalFinQATypedProgramPlannerV23,
)
from app.external_datasets.finqa_typed_program import (
    TypedProgramValidationError,
)
from app.external_datasets.finqa_typed_retrospective import (
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
    if "no operand" in message:
        return "no_admitted_operand_candidate"
    return "typed_precondition_failed"


def evaluate_v23_case(
    *,
    case: FinQACase,
    source: FinQATypedCalibrationRunCase,
    planner: LocalFinQATypedProgramPlannerV23,
    guard: RetrievedContentGuard | None = None,
) -> FinQAV23CalibrationCase:
    if case.id != source.case_id:
        raise ValueError("v2.3 source row does not match FinQA case")
    resolved_guard = guard or RetrievedContentGuard()
    closure = expand_finqa_numeric_evidence_v2(
        case,
        selected_unit_ids=source.selected_unit_ids,
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
    started = time.perf_counter()
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
        result = refused_arm_evaluation(
            arm_id="B1_TYPED_SINGLE",
            failure_reason=_bounded_failure_reason(error),
            generation_calls=0,
            compiler_calls=0,
            generated_program_count=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            candidate_count=len(corpus.candidates),
        )
    else:
        try:
            planned = planner.plan_and_execute(
                question=case.qa.question,
                candidates=shortlist,
                admitted_evidence_ids=admitted_ids,
                intent=intent,
                evidence_context_by_id=context,
            )
        except TypedPlannerProtocolError as error:
            result = refused_arm_evaluation(
                arm_id="B1_TYPED_SINGLE",
                failure_reason=error.last_reason,
                generation_calls=error.attempt_count,
                compiler_calls=error.compiler_calls,
                generated_program_count=error.compiler_calls,
                latency_ms=error.latency_ms,
                candidate_count=len(shortlist),
                status="PROTOCOL_ERROR",
            )
        except TypedProgramValidationError as error:
            result = refused_arm_evaluation(
                arm_id="B1_TYPED_SINGLE",
                failure_reason=error.reason,
                generation_calls=0,
                compiler_calls=0,
                generated_program_count=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                candidate_count=len(shortlist),
            )
        except ValueError as error:
            result = refused_arm_evaluation(
                arm_id="B1_TYPED_SINGLE",
                failure_reason=_bounded_failure_reason(error),
                generation_calls=0,
                compiler_calls=0,
                generated_program_count=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                candidate_count=len(shortlist),
            )
        else:
            evidence = tuple(
                units[unit_id] for unit_id in admission.admitted_unit_ids
            )
            answer = FinQAAnswerResult(
                final_answer=format(planned.execution.value, "f"),
                calculation=json.dumps(
                    planned.program.model_dump(mode="json"),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                cited_unit_ids=planned.execution.evidence_ids,
                provided_unit_ids=admission.admitted_unit_ids,
                admitted_count=len(evidence),
                quarantined_count=len(admission.quarantined_unit_ids),
                guard_rule_ids=tuple(
                    sorted(
                        {
                            rule_id
                            for decision in admission.decision_by_unit_id.values()
                            for rule_id in decision.rule_ids
                        }
                    )
                ),
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
            result = arm_evaluation_from_case(
                arm_id="B1_TYPED_SINGLE",
                evaluation=evaluation,
                compiler_calls=planned.compiler_calls,
                generated_program_count=1,
                candidate_count=len(shortlist),
                selected_program_sha256=(
                    planned.execution.program_sha256
                ),
                selected_support_count=1,
                valid_program_count=1,
            )
    return FinQAV23CalibrationCase(
        case_id=case.id,
        diagnostic_category=source.diagnostic_category,
        selected_unit_ids=tuple(source.selected_unit_ids),
        admitted_closure_unit_ids=admission.admitted_unit_ids,
        gold_unit_ids=tuple(source.gold_unit_ids),
        candidate_count_before_shortlist=len(corpus.candidates),
        candidate_count_after_shortlist=len(shortlist),
        guard_scan_count=admission.scan_count,
        quarantined_unit_count=len(admission.quarantined_unit_ids),
        b0_stored=source.b0,
        b1_v22_stored=source.b1_v2,
        b1_v23_intervention=result,
    )


__all__ = ["evaluate_v23_case"]
