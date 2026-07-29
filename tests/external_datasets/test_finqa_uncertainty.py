import hashlib

import pytest

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationCaseEvaluation,
)
from app.external_datasets.finqa_eval import FinQACaseEvaluation
from app.external_datasets.finqa_uncertainty import (
    FinQARuntimeUncertainty,
    FinQAUncertaintyRunManifest,
    assess_finqa_runtime_uncertainty,
    evaluate_finqa_uncertainty_case,
    publish_finqa_uncertainty_run,
    summarize_finqa_uncertainty_cases,
    verify_finqa_uncertainty_run,
)


def _case(*, program: str, exe_ans: float) -> FinQACase:
    return FinQACase.model_validate(
        {
            "pre_text": [],
            "post_text": [],
            "filename": "report.pdf",
            "table_ori": [
                ["metric", "2023", "2022"],
                ["revenue", "120", "100"],
            ],
            "table": [
                ["metric", "2023", "2022"],
                ["revenue", "120", "100"],
            ],
            "qa": {
                "question": "What was the percentage change?",
                "answer": str(exe_ans),
                "explanation": "",
                "ann_table_rows": [],
                "ann_text_rows": [],
                "steps": [],
                "program": program,
                "gold_inds": {"table_1": "private gold annotation"},
                "exe_ans": exe_ans,
                "tfidftopn": {},
                "program_re": program,
                "model_input": [],
            },
            "id": "report.pdf-1",
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


def _evaluation() -> FinQACaseEvaluation:
    return FinQACaseEvaluation(
        case_id="report.pdf-1",
        retrieval_mode="hybrid",
        selected_unit_ids=["table_1"],
        gold_unit_ids=["private_gold_unit"],
        cited_unit_ids=["table_1"],
        final_answer="0.2",
        calculation="(120 - 100) / 100",
        answer_status="ok",
        answer_parseable=True,
        strict_execution_match=False,
        presentation_tolerance_match=False,
        evidence_recall=0.0,
        citation_precision=0.0,
        citation_recall=0.0,
        grounded_execution_match=False,
        grounded_presentation_match=False,
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=[],
        generation_calls=1,
        calculator_calls=1,
        latency_ms=100,
    )


def test_trigger_uses_runtime_inputs_and_ignores_gold_labels() -> None:
    evaluation = _evaluation()
    first = assess_finqa_runtime_uncertainty(
        _case(
            program="subtract(120, 100), divide(#0, const_100)",
            exe_ans=0.2,
        ),
        evaluation,
    )
    changed_gold = evaluation.model_copy(
        update={
            "gold_unit_ids": ["other_private_gold"],
            "strict_execution_match": True,
            "evidence_recall": 1.0,
            "citation_recall": 1.0,
            "grounded_execution_match": True,
        }
    )
    second = assess_finqa_runtime_uncertainty(
        _case(program="add(999, 1)", exe_ans=1000),
        changed_gold,
    )

    assert first == second
    assert first.triggered is True
    assert first.score == 2
    assert first.reason_codes == ["multi_operation", "ratio_division"]


def _result(
    *,
    case_id: str,
    strict: bool,
    generation_calls: int,
    calculator_calls: int,
    latency_ms: float,
) -> FinQACaseEvaluation:
    return _evaluation().model_copy(
        update={
            "case_id": case_id,
            "final_answer": "1" if strict else "0",
            "calculation": "120 / 100" if strict else "100 / 120",
            "strict_execution_match": strict,
            "presentation_tolerance_match": strict,
            "grounded_execution_match": strict,
            "grounded_presentation_match": strict,
            "generation_calls": generation_calls,
            "calculator_calls": calculator_calls,
            "latency_ms": latency_ms,
        }
    )


def _adjudication(
    *,
    case_id: str,
    baseline_correct: bool,
    final_correct: bool,
) -> FinQAAdjudicationCaseEvaluation:
    baseline = _result(
        case_id=case_id,
        strict=baseline_correct,
        generation_calls=1,
        calculator_calls=1,
        latency_ms=100,
    )
    proposal = _result(
        case_id=case_id,
        strict=final_correct,
        generation_calls=2,
        calculator_calls=2,
        latency_ms=200,
    )
    adjudicated = proposal.model_copy(
        update={
            "generation_calls": 3,
            "calculator_calls": 3,
            "latency_ms": 300,
        }
    )
    transition = (
        "wrong_to_correct"
        if not baseline_correct and final_correct
        else "correct_to_wrong"
    )
    return FinQAAdjudicationCaseEvaluation(
        case_id=case_id,
        baseline=baseline,
        proposal=proposal,
        adjudicated=adjudicated,
        proposal_review_status="revised",
        adjudication_status="proposal_accepted",
        correctness_transition=transition,
        adjudication_generation_calls=1,
        adjudication_calculator_calls=1,
        adjudication_latency_ms=100,
    )


def _signal(*, case_id: str, triggered: bool) -> FinQARuntimeUncertainty:
    return FinQARuntimeUncertainty(
        case_id=case_id,
        eligible_for_plan_review=True,
        triggered=triggered,
        score=2 if triggered else 0,
        reason_codes=(
            ["multi_operation", "ratio_division"] if triggered else []
        ),
        operand_grounding_rate=1.0,
        operation_count=2 if triggered else 1,
        numeric_operand_count=2,
        cited_evidence_number_count=2,
        cited_unit_count=1,
        selected_unit_count=1,
        distinct_year_count=2,
        planner_generation_calls=1,
        quarantined_unit_count=0,
    )


def test_gated_policy_preserves_untriggered_baseline_and_reports_cost() -> None:
    fixed = evaluate_finqa_uncertainty_case(
        _adjudication(
            case_id="case-1",
            baseline_correct=False,
            final_correct=True,
        ),
        _signal(case_id="case-1", triggered=True),
    )
    avoided_regression = evaluate_finqa_uncertainty_case(
        _adjudication(
            case_id="case-2",
            baseline_correct=True,
            final_correct=False,
        ),
        _signal(case_id="case-2", triggered=False),
    )

    summary = summarize_finqa_uncertainty_cases(
        [fixed, avoided_regression]
    )

    assert fixed.selected_source == "adjudicated"
    assert avoided_regression.selected_source == "baseline"
    assert summary.trigger_rate == 0.5
    assert summary.baseline_execution_accuracy == 0.5
    assert summary.full_strategy_execution_accuracy == 0.5
    assert summary.gated_execution_accuracy == 1.0
    assert summary.gated_wrong_to_correct == 1
    assert summary.gated_correct_to_wrong == 0
    assert summary.incremental_generation_calls == 2
    assert summary.full_strategy_incremental_generation_calls == 4
    assert summary.generation_call_reduction == pytest.approx(0.5)


def test_uncertainty_run_is_immutable_and_tamper_evident(
    tmp_path,
) -> None:
    row = evaluate_finqa_uncertainty_case(
        _adjudication(
            case_id="case-1",
            baseline_correct=False,
            final_correct=True,
        ),
        _signal(case_id="case-1", triggered=True),
    )
    manifest = FinQAUncertaintyRunManifest(
        uncertainty_run_id="uncertainty-v1",
        source_adjudication_run_id="adjudication-v1",
        source_adjudication_manifest_sha256="a" * 64,
        source_adjudication_details_sha256="b" * 64,
        dataset_revision="c" * 40,
        split="dev",
        split_sha256="d" * 64,
        selected_case_ids_sha256=hashlib.sha256(
            b"case-1\n"
        ).hexdigest(),
        selected_case_count=1,
        retrieval_mode="hybrid",
        source_adjudication_code_revision="f" * 40,
        uncertainty_code_revision="1" * 40,
        summary=summarize_finqa_uncertainty_cases([row]),
    )

    run_dir = publish_finqa_uncertainty_run(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )
    verified = verify_finqa_uncertainty_run(run_dir)

    assert set(verified.artifacts) == {"details.jsonl", "summary.json"}
    with pytest.raises(FileExistsError):
        publish_finqa_uncertainty_run(
            root=tmp_path,
            manifest=manifest,
            details=[row],
        )
    (run_dir / "details.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_finqa_uncertainty_run(run_dir)
