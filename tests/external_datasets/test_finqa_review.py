from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.external_datasets.finqa import (
    FinQACase,
    build_finqa_evidence_units,
)
from app.external_datasets.finqa_eval import FinQACaseEvaluation
from app.external_datasets.finqa_review import (
    FinQAReviewRunManifest,
    LocalFinQAPlanReviewer,
    evaluate_finqa_review_case,
    preserve_unreviewable_finqa_case,
    publish_finqa_review_run,
    summarize_finqa_review_cases,
    verify_finqa_review_run,
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


def _baseline(
    *,
    calculation: str = "(120 - 100) / 100",
    final_answer: str = "0.2",
    strict: bool = True,
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
        generation_calls=1,
        calculator_calls=1,
        latency_ms=100,
    )


def _review_response(
    expression: str,
    citations: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "expression": expression,
            "cited_candidate_ids": citations or ["evidence-01"],
        }
    )


def test_plan_reviewer_keeps_a_valid_draft_and_hides_real_unit_ids() -> None:
    captured = []

    def chat(model, messages, *, response_format=None, think=None):
        captured.append(messages)
        return _review_response("(120 - 100) / 100")

    result = LocalFinQAPlanReviewer(
        model="qwen-test",
        chat_fn=chat,
    ).review(
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        baseline=_baseline(),
    )

    assert result.review_status == "kept"
    assert result.expression_changed is False
    assert result.final_answer == "0.2"
    assert result.review_generation_calls == 1
    serialized = json.dumps(captured)
    assert "table_1" not in serialized
    assert "evidence-01" in serialized
    assert "must yield 0.054, not 5.4" in serialized


def test_plan_reviewer_revises_expression_and_citations() -> None:
    baseline = _baseline(
        calculation="(120 - 90) / 90",
        final_answer="0.3333333333333333333333333333",
        strict=False,
    )
    result = LocalFinQAPlanReviewer(
        model="qwen-test",
        chat_fn=lambda *args, **kwargs: _review_response(
            "(120 - 100) / 100"
        ),
    ).review(
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        baseline=baseline,
    )

    assert result.review_status == "revised"
    assert result.expression_changed is True
    assert result.final_answer == "0.2"


def test_plan_reviewer_falls_back_only_for_exhausted_protocol_errors() -> None:
    responses = iter(
        [
            _review_response("1 / 0"),
            _review_response("evidence-01 + 1"),
        ]
    )
    result = LocalFinQAPlanReviewer(
        model="qwen-test",
        chat_fn=lambda *args, **kwargs: next(responses),
        max_attempts=2,
    ).review(
        question=_case().qa.question,
        evidence_units=build_finqa_evidence_units(_case())[1:],
        baseline=_baseline(),
    )

    assert result.review_status == "fallback_protocol_error"
    assert result.final_answer == "0.2"
    assert result.calculation == "(120 - 100) / 100"
    assert result.review_generation_calls == 2
    # Both structured payloads reached the calculator: one divided by zero,
    # while the other was rejected by the calculator's character allowlist.
    assert result.review_calculator_calls == 2


def test_plan_reviewer_does_not_hide_transport_failures() -> None:
    def unavailable(*args, **kwargs):
        raise RuntimeError("Ollama unavailable")

    with pytest.raises(RuntimeError, match="Ollama unavailable"):
        LocalFinQAPlanReviewer(
            model="qwen-test",
            chat_fn=unavailable,
        ).review(
            question=_case().qa.question,
            evidence_units=build_finqa_evidence_units(_case())[1:],
            baseline=_baseline(),
        )


def test_plan_reviewer_rejects_evidence_order_drift() -> None:
    with pytest.raises(ValueError, match="does not match baseline order"):
        LocalFinQAPlanReviewer(
            model="qwen-test",
            chat_fn=lambda *args, **kwargs: _review_response("1"),
        ).review(
            question=_case().qa.question,
            evidence_units=build_finqa_evidence_units(_case()),
            baseline=_baseline(),
        )


def test_review_evaluation_records_wrong_to_correct_and_total_cost() -> None:
    case = _case()
    selected = build_finqa_evidence_units(case)[1:]
    baseline = _baseline(
        calculation="(120 - 90) / 90",
        final_answer="0.3333333333333333333333333333",
        strict=False,
    )
    review = LocalFinQAPlanReviewer(
        model="qwen-test",
        chat_fn=lambda *args, **kwargs: _review_response(
            "(120 - 100) / 100"
        ),
    ).review(
        question=case.qa.question,
        evidence_units=selected,
        baseline=baseline,
    )

    row = evaluate_finqa_review_case(
        case,
        baseline=baseline,
        selected_units=selected,
        review=review,
    )
    summary = summarize_finqa_review_cases([row])

    assert row.correctness_transition == "wrong_to_correct"
    assert row.reviewed.generation_calls == 2
    assert row.reviewed.calculator_calls == 2
    assert summary.execution_accuracy_delta == 1.0
    assert summary.transition_counts["wrong_to_correct"] == 1
    assert summary.discordant_case_count == 1
    assert summary.mcnemar_exact_p_value == 1.0
    assert summary.generation_call_multiplier == 2.0
    assert summary.calculator_call_multiplier == 2.0


def test_unreviewable_baseline_is_preserved_without_incremental_calls() -> None:
    baseline = _baseline().model_copy(
        update={
            "answer_status": "program_output_exhausted",
            "answer_parseable": False,
            "strict_execution_match": False,
            "presentation_tolerance_match": False,
            "grounded_execution_match": False,
            "grounded_presentation_match": False,
            "calculation": "",
            "final_answer": "",
        }
    )

    row = preserve_unreviewable_finqa_case(baseline)
    summary = summarize_finqa_review_cases([row])

    assert row.review_status == "not_applicable_baseline_error"
    assert row.reviewed == baseline
    assert row.review_generation_calls == 0
    assert summary.review_eligible_case_count == 0
    assert summary.generation_call_multiplier == 1.0


def test_review_run_is_immutable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    case = _case()
    selected = build_finqa_evidence_units(case)[1:]
    baseline = _baseline()
    review = LocalFinQAPlanReviewer(
        model="qwen-test",
        chat_fn=lambda *args, **kwargs: _review_response(
            "(120 - 100) / 100"
        ),
    ).review(
        question=case.qa.question,
        evidence_units=selected,
        baseline=baseline,
    )
    row = evaluate_finqa_review_case(
        case,
        baseline=baseline,
        selected_units=selected,
        review=review,
    )
    summary = summarize_finqa_review_cases([row])
    selected_ids_sha256 = hashlib.sha256(
        b"report.pdf-1\n"
    ).hexdigest()
    manifest = FinQAReviewRunManifest(
        review_run_id="finqa-review-dev-v1",
        review_prompt_version="finqa_plan_review_v1",
        source_run_id="finqa-source-dev-v1",
        source_manifest_sha256="a" * 64,
        source_details_sha256="b" * 64,
        dataset_revision="c" * 40,
        split="dev",
        split_sha256="d" * 64,
        selected_case_ids_sha256=selected_ids_sha256,
        selected_case_count=1,
        retrieval_mode="hybrid",
        source_code_revision="f" * 40,
        review_code_revision="1" * 40,
        review_model="qwen-test",
        review_model_sha256="2" * 64,
        timeout_seconds=120,
        max_attempts=2,
        summary=summary,
    )

    run_dir = publish_finqa_review_run(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )

    assert verify_finqa_review_run(run_dir).summary == summary
    with pytest.raises(FileExistsError, match="already exists"):
        publish_finqa_review_run(
            root=tmp_path,
            manifest=manifest,
            details=[row],
        )
    (run_dir / "details.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_finqa_review_run(run_dir)
