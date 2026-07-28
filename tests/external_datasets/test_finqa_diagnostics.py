from __future__ import annotations

from pathlib import Path

import pytest

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_diagnostics import (
    FinQADiagnosticManifest,
    analyze_finqa_expression,
    diagnose_finqa_case,
    parse_finqa_gold_program,
    publish_finqa_diagnostic,
    summarize_finqa_diagnostics,
    verify_finqa_diagnostic,
)
from app.external_datasets.finqa_eval import FinQACaseEvaluation


def _case(
    *,
    program: str = "subtract(120, 100), divide(#0, const_100)",
) -> FinQACase:
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
                "question": "What was the change as a fraction?",
                "answer": "0.2",
                "explanation": "",
                "ann_table_rows": [],
                "ann_text_rows": [],
                "steps": [],
                "program": program,
                "gold_inds": {
                    "table_1": (
                        "metric the revenue of 2023 is 120 ; "
                        "the revenue of 2022 is 100 ;"
                    )
                },
                "exe_ans": 0.2,
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


def _evaluation(
    *,
    calculation: str = "(120 - 100) / 100",
    strict: bool = False,
    evidence_recall: float = 1.0,
    citation_recall: float = 1.0,
    answer_status: str = "ok",
) -> FinQACaseEvaluation:
    return FinQACaseEvaluation(
        case_id="report.pdf-1",
        retrieval_mode="hybrid",
        selected_unit_ids=["table_1"] if evidence_recall else ["table_0"],
        gold_unit_ids=["table_1"],
        cited_unit_ids=["table_1"] if citation_recall else ["table_0"],
        final_answer="0.2" if strict else "0.3",
        calculation=calculation,
        answer_status=answer_status,
        answer_parseable=answer_status == "ok",
        strict_execution_match=strict,
        presentation_tolerance_match=strict,
        evidence_recall=evidence_recall,
        citation_precision=citation_recall,
        citation_recall=citation_recall,
        grounded_execution_match=strict and citation_recall == 1.0,
        grounded_presentation_match=strict and citation_recall == 1.0,
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=[],
        generation_calls=1,
        calculator_calls=1 if answer_status == "ok" else 0,
        latency_ms=100,
    )


def test_gold_program_and_expression_have_comparable_execution_order() -> None:
    gold = parse_finqa_gold_program(
        "subtract(120, 100), divide(#0, const_100)"
    )
    predicted = analyze_finqa_expression("(120 - 100) / 100")

    assert gold.operations == ("subtract", "divide")
    assert predicted.operations == gold.operations
    assert predicted.numeric_operands == gold.numeric_operands
    assert gold.unsupported_operations == ()


def test_gold_table_operation_is_preserved_as_unsupported() -> None:
    gold = parse_finqa_gold_program("table_average(operating margin, none)")

    assert gold.operations == ("table_average",)
    assert gold.numeric_operands == ()
    assert gold.unsupported_operations == ("table_average",)


def test_compound_unary_minus_is_an_explicit_multiply_signal() -> None:
    predicted = analyze_finqa_expression("-(120 - 100)")

    assert predicted.numeric_operands == (120, 100, -1)
    assert predicted.operations == ("subtract", "multiply")


@pytest.mark.parametrize(
    ("evaluation", "expected_category"),
    [
        (_evaluation(strict=True), "correct_grounded"),
        (
            _evaluation(strict=True, citation_recall=0.0),
            "correct_citation_incomplete",
        ),
        (_evaluation(evidence_recall=0.0), "retrieval_miss"),
        (
            _evaluation(
                calculation="",
                answer_status="program_output_exhausted",
            ),
            "generation_protocol_error",
        ),
        (
            _evaluation(calculation="(130 - 100) / 100"),
            "operand_selection_signal",
        ),
        (
            _evaluation(calculation="(120 + 100) / 100"),
            "operation_plan_signal",
        ),
        (
            _evaluation(calculation="(100 - 120) / 100"),
            "composition_or_scale_signal",
        ),
    ],
)
def test_diagnostic_priority_is_deterministic(
    evaluation: FinQACaseEvaluation,
    expected_category: str,
) -> None:
    row = diagnose_finqa_case(_case(), evaluation)

    assert row.category == expected_category


def test_unsupported_operation_precedes_operand_signals() -> None:
    row = diagnose_finqa_case(
        _case(program="table_average(revenue, none)"),
        _evaluation(calculation="(120 + 100) / 2"),
    )

    assert row.category == "unsupported_gold_operation"


def test_expression_grounding_uses_citations_and_official_constants() -> None:
    row = diagnose_finqa_case(
        _case(),
        _evaluation(calculation="(120 - 999) / 100"),
    )

    assert row.expression_operand_grounding_rate == pytest.approx(2 / 3)


def test_diagnostic_artifact_is_immutable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    row = diagnose_finqa_case(_case(), _evaluation(strict=True))
    summary = summarize_finqa_diagnostics([row])
    manifest = FinQADiagnosticManifest(
        diagnostic_id="finqa-dev-diagnostic-v1",
        source_run_id="finqa-dev-source-v1",
        source_manifest_sha256="a" * 64,
        source_details_sha256="b" * 64,
        dataset_revision="c" * 40,
        split="dev",
        split_sha256="d" * 64,
        selected_case_ids_sha256="e" * 64,
        source_code_revision="f" * 40,
        diagnostic_code_revision="1" * 40,
        retrieval_mode="hybrid",
        summary=summary,
    )

    run_dir = publish_finqa_diagnostic(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )

    assert verify_finqa_diagnostic(run_dir).summary == summary
    with pytest.raises(FileExistsError, match="already exists"):
        publish_finqa_diagnostic(
            root=tmp_path,
            manifest=manifest,
            details=[row],
        )
    (run_dir / "summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_finqa_diagnostic(run_dir)
