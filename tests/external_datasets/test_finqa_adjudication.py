from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.external_datasets.finqa import (
    FinQACase,
    build_finqa_evidence_units,
)
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationRunManifest,
    LocalFinQACandidateAdjudicator,
    evaluate_finqa_adjudication_case,
    preserve_unadjudicated_finqa_case,
    publish_finqa_adjudication_run,
    summarize_finqa_adjudication_cases,
    verify_finqa_adjudication_run,
)
from app.external_datasets.finqa_eval import FinQACaseEvaluation
from app.external_datasets.finqa_review import (
    FinQAReviewCaseEvaluation,
    summarize_finqa_review_cases,
)


def _case() -> FinQACase:
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
                "question": "What was the signed change as a fraction?",
                "answer": "20%",
                "explanation": "",
                "ann_table_rows": [],
                "ann_text_rows": [],
                "steps": [],
                "program": "subtract(120, 100), divide(#0, 100)",
                "gold_inds": {
                    "table_1": (
                        "metric the revenue of 2023 is 120 ; "
                        "the revenue of 2022 is 100 ;"
                    )
                },
                "exe_ans": 0.2,
                "tfidftopn": {},
                "program_re": "subtract(120, 100), divide(#0, 100)",
                "model_input": [],
            },
            "id": "report.pdf-1",
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


def _evaluation(
    *,
    calculation: str,
    final_answer: str,
    strict: bool,
    generation_calls: int,
    calculator_calls: int,
    latency_ms: float,
) -> FinQACaseEvaluation:
    return FinQACaseEvaluation(
        case_id="report.pdf-1",
        retrieval_mode="hybrid",
        selected_unit_ids=["table_1"],
        gold_unit_ids=["table_1"],
        cited_unit_ids=["table_1"],
        final_answer=final_answer,
        calculation=calculation,
        answer_status="ok",
        answer_parseable=True,
        strict_execution_match=strict,
        presentation_tolerance_match=strict,
        evidence_recall=1.0,
        citation_precision=1.0,
        citation_recall=1.0,
        grounded_execution_match=strict,
        grounded_presentation_match=strict,
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=[],
        generation_calls=generation_calls,
        calculator_calls=calculator_calls,
        latency_ms=latency_ms,
    )


def _source(*, baseline_correct: bool) -> FinQAReviewCaseEvaluation:
    correct = _evaluation(
        calculation="(120 - 100) / 100",
        final_answer="0.2",
        strict=True,
        generation_calls=1,
        calculator_calls=1,
        latency_ms=100,
    )
    wrong = _evaluation(
        calculation="(120 - 90) / 90",
        final_answer="0.3333333333333333333333333333",
        strict=False,
        generation_calls=1,
        calculator_calls=1,
        latency_ms=100,
    )
    baseline = correct if baseline_correct else wrong
    proposed_template = wrong if baseline_correct else correct
    proposal = proposed_template.model_copy(
        update={
            "generation_calls": 2,
            "calculator_calls": 2,
            "latency_ms": 200,
        }
    )
    return FinQAReviewCaseEvaluation(
        case_id="report.pdf-1",
        baseline=baseline,
        reviewed=proposal,
        review_status="revised",
        correctness_transition=(
            "correct_to_wrong"
            if baseline_correct
            else "wrong_to_correct"
        ),
        expression_changed=True,
        citations_changed=False,
        review_generation_calls=1,
        review_calculator_calls=1,
        review_latency_ms=100,
    )


def _choose_expression(
    expression: str,
    captured: list,
) -> Callable[..., str]:
    def chat(model, messages, *, response_format=None, think=None):
        captured.append(messages)
        payload = json.loads(messages[1]["content"])
        label = next(
            candidate_label
            for candidate_label, candidate in payload["candidates"].items()
            if candidate["expression"] == expression
        )
        return json.dumps({"selected_candidate": label})

    return chat


def test_adjudicator_accepts_correct_proposal_and_hides_source_identity() -> None:
    source = _source(baseline_correct=False)
    captured = []
    result = LocalFinQACandidateAdjudicator(
        model="judge-test",
        chat_fn=_choose_expression("(120 - 100) / 100", captured),
    ).adjudicate(
        case_id=source.case_id,
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        source=source,
    )

    row = evaluate_finqa_adjudication_case(
        _case(),
        source=source,
        selected_units=build_finqa_evidence_units(_case())[1:],
        result=result,
    )

    assert result.status == "proposal_accepted"
    assert result.calculator_calls == 2
    assert row.correctness_transition == "wrong_to_correct"
    assert row.adjudicated.generation_calls == 3
    assert row.adjudicated.calculator_calls == 4
    serialized = json.dumps(captured)
    assert "table_1" not in serialized
    assert "candidate-a" in serialized
    assert "candidate-b" in serialized
    assert "baseline" not in serialized
    assert "proposal" not in serialized


def test_adjudicator_can_retain_correct_baseline() -> None:
    source = _source(baseline_correct=True)
    result = LocalFinQACandidateAdjudicator(
        model="judge-test",
        chat_fn=_choose_expression("(120 - 100) / 100", []),
    ).adjudicate(
        case_id=source.case_id,
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        source=source,
    )
    row = evaluate_finqa_adjudication_case(
        _case(),
        source=source,
        selected_units=build_finqa_evidence_units(_case())[1:],
        result=result,
    )

    assert result.status == "baseline_retained"
    assert row.correctness_transition == "correct_to_correct"
    assert row.adjudicated.final_answer == "0.2"


def test_adjudicator_protocol_failure_falls_back_to_baseline() -> None:
    source = _source(baseline_correct=True)
    result = LocalFinQACandidateAdjudicator(
        model="judge-test",
        chat_fn=lambda *args, **kwargs: "{}",
        max_attempts=2,
    ).adjudicate(
        case_id=source.case_id,
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        source=source,
    )

    assert result.status == "fallback_protocol_error"
    assert result.selected_source == "baseline"
    assert result.generation_calls == 2


def test_adjudicator_does_not_hide_transport_failure() -> None:
    source = _source(baseline_correct=True)

    with pytest.raises(RuntimeError, match="Ollama unavailable"):
        LocalFinQACandidateAdjudicator(
            model="judge-test",
            chat_fn=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("Ollama unavailable")
            ),
        ).adjudicate(
            case_id=source.case_id,
            question=_case().qa.question,
            evidence_units=build_finqa_evidence_units(_case())[1:],
            source=source,
        )


def test_unchanged_proposal_bypasses_adjudicator() -> None:
    revised = _source(baseline_correct=True)
    source = revised.model_copy(
        update={
            "reviewed": revised.baseline.model_copy(
                update={
                    "generation_calls": 2,
                    "calculator_calls": 2,
                    "latency_ms": 200,
                }
            ),
            "review_status": "kept",
            "correctness_transition": "correct_to_correct",
            "expression_changed": False,
        }
    )

    row = preserve_unadjudicated_finqa_case(source)

    assert row.adjudication_status == "not_applicable_unchanged_proposal"
    assert row.adjudicated == source.reviewed
    assert row.adjudication_generation_calls == 0


def test_adjudication_run_is_immutable_and_reproducible(
    tmp_path: Path,
) -> None:
    source = _source(baseline_correct=False)
    result = LocalFinQACandidateAdjudicator(
        model="judge-test",
        chat_fn=_choose_expression("(120 - 100) / 100", []),
    ).adjudicate(
        case_id=source.case_id,
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        source=source,
    )
    row = evaluate_finqa_adjudication_case(
        _case(),
        source=source,
        selected_units=build_finqa_evidence_units(_case())[1:],
        result=result,
    )
    source_summary = summarize_finqa_review_cases([source])
    summary = summarize_finqa_adjudication_cases(
        [row],
        source_review=source_summary,
    )
    manifest = FinQAAdjudicationRunManifest(
        adjudication_run_id="finqa-adjudication-dev-v1",
        source_review_run_id="finqa-review-dev-v1",
        source_review_manifest_sha256="a" * 64,
        source_review_details_sha256="b" * 64,
        dataset_revision="c" * 40,
        split="dev",
        split_sha256="d" * 64,
        selected_case_ids_sha256=hashlib.sha256(
            b"report.pdf-1\n"
        ).hexdigest(),
        selected_case_count=1,
        retrieval_mode="hybrid",
        source_review_code_revision="e" * 40,
        adjudication_code_revision="f" * 40,
        adjudicator_model="judge-test",
        adjudicator_model_sha256="1" * 64,
        runtime_backend="test_cpu",
        timeout_seconds=120,
        max_attempts=2,
        summary=summary,
    )

    run_dir = publish_finqa_adjudication_run(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )

    assert verify_finqa_adjudication_run(run_dir).summary == summary
    with pytest.raises(FileExistsError, match="already exists"):
        publish_finqa_adjudication_run(
            root=tmp_path,
            manifest=manifest,
            details=[row],
        )
    (run_dir / "summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_finqa_adjudication_run(run_dir)
