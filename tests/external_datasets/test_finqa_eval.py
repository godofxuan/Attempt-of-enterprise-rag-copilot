import json
from pathlib import Path

import numpy as np
import pytest

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_eval import (
    FinQAAnswerProtocolError,
    FinQAAnswerResult,
    FinQARunManifest,
    LocalFinQAAnswerer,
    LocalFinQAProgramAnswerer,
    evaluate_finqa_case,
    evaluate_finqa_protocol_error,
    parse_finqa_answer_payload,
    publish_finqa_run,
    rank_finqa_evidence,
    selected_case_ids_sha256,
    summarize_finqa_cases,
    verify_finqa_run,
)
from app.external_datasets import finqa_eval


def _case() -> FinQACase:
    return FinQACase.model_validate(
        {
            "pre_text": [
                "Revenue increased from 100 to 120.",
                "Operating expense remained stable.",
            ],
            "post_text": ["The increase was driven by subscription sales."],
            "filename": "report.pdf",
            "table_ori": [
                ["", "2023", "2022"],
                ["Revenue", "120", "100"],
            ],
            "table": [
                ["", "2023", "2022"],
                ["Revenue", "120", "100"],
            ],
            "qa": {
                "question": "What was the revenue growth rate?",
                "answer": "20%",
                "explanation": "",
                "ann_table_rows": [1],
                "ann_text_rows": [],
                "steps": [],
                "program": "divide(20, 100)",
                "gold_inds": {
                    "table_1": (
                        "the Revenue of 2023 is 120 ; "
                        "the Revenue of 2022 is 100 ;"
                    )
                },
                "exe_ans": 0.2,
                "tfidftopn": {},
                "program_re": "divide(20, 100)",
                "model_input": [],
            },
            "id": "report.pdf-1",
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


def test_parse_finqa_answer_rejects_unknown_or_duplicate_citations() -> None:
    duplicate = json.dumps(
        {
            "final_answer": "20%",
            "calculation": "(120-100)/100",
            "cited_candidate_ids": ["evidence-01", "evidence-01"],
        }
    )
    with pytest.raises(ValueError, match="unique"):
        parse_finqa_answer_payload(
            duplicate,
            allowed_candidate_ids=["evidence-01"],
        )

    unknown = json.dumps(
        {
            "final_answer": "20%",
            "calculation": "(120-100)/100",
            "cited_candidate_ids": ["evidence-02"],
        }
    )
    with pytest.raises(ValueError, match="unknown candidate"):
        parse_finqa_answer_payload(
            unknown,
            allowed_candidate_ids=["evidence-01"],
        )


def test_finqa_response_schema_avoids_unsupported_ollama_string_lengths() -> None:
    schema = finqa_eval._response_format(["evidence-01"])

    assert schema["properties"]["final_answer"] == {"type": "string"}
    assert schema["properties"]["calculation"] == {"type": "string"}
    with pytest.raises(ValueError, match="at least 1 character"):
        parse_finqa_answer_payload(
            json.dumps(
                {
                    "final_answer": "",
                    "calculation": "x",
                    "cited_candidate_ids": ["evidence-01"],
                }
            ),
            allowed_candidate_ids=["evidence-01"],
        )


def test_local_finqa_answerer_maps_temporary_ids_back_to_units() -> None:
    case = _case()
    units = rank_finqa_evidence(case, mode="oracle", top_k=5)
    calls = []

    def chat(model, messages, *, response_format=None, think=None):
        calls.append((model, messages, response_format, think))
        return json.dumps(
            {
                "final_answer": "20%",
                "calculation": "(120 - 100) / 100 = 20%",
                "cited_candidate_ids": ["evidence-01"],
            }
        )

    result = LocalFinQAAnswerer(model="qwen-test", chat_fn=chat).answer(
        question=case.qa.question,
        evidence_units=units,
    )

    assert result.cited_unit_ids == ("table_1",)
    assert result.attempt_count == 1
    assert calls[0][3] is False
    assert "table_1" not in calls[0][1][1]["content"]


def test_local_finqa_program_answerer_executes_calculator_result() -> None:
    case = _case()
    units = rank_finqa_evidence(case, mode="oracle", top_k=5)

    def chat(model, messages, *, response_format=None, think=None):
        return json.dumps(
            {
                "expression": "(120 - 100) / 100",
                "cited_candidate_ids": ["evidence-01"],
            }
        )

    result = LocalFinQAProgramAnswerer(
        model="qwen-test",
        chat_fn=chat,
    ).answer(question=case.qa.question, evidence_units=units)

    assert result.final_answer == "0.2"
    assert result.cited_unit_ids == ("table_1",)
    assert result.calculator_calls == 1
    assert result.calculation == "(120 - 100) / 100"


def test_local_finqa_program_answerer_counts_failed_calculator_retry() -> None:
    case = _case()
    units = rank_finqa_evidence(case, mode="oracle", top_k=5)
    responses = iter(
        [
            json.dumps(
                {
                    "expression": "1 / 0",
                    "cited_candidate_ids": ["evidence-01"],
                }
            ),
            json.dumps(
                {
                    "expression": "20 / 100",
                    "cited_candidate_ids": ["evidence-01"],
                }
            ),
        ]
    )

    result = LocalFinQAProgramAnswerer(
        model="qwen-test",
        chat_fn=lambda *args, **kwargs: next(responses),
    ).answer(question=case.qa.question, evidence_units=units)

    assert result.final_answer == "0.2"
    assert result.attempt_count == 2
    assert result.calculator_calls == 2


def test_finqa_program_schema_exposes_only_expression_and_citations() -> None:
    schema = finqa_eval._program_response_format(["evidence-01"])

    assert schema["properties"]["expression"] == {"type": "string"}
    assert set(schema["properties"]) == {
        "expression",
        "cited_candidate_ids",
    }


def test_local_finqa_answerer_retries_one_invalid_response() -> None:
    case = _case()
    units = rank_finqa_evidence(case, mode="oracle", top_k=5)
    responses = iter(
        [
            '{"final_answer":"20%","calculation":"x",'
            '"cited_candidate_ids":["unknown"]}',
            '{"final_answer":"20%","calculation":"(120-100)/100",'
            '"cited_candidate_ids":["evidence-01"]}',
        ]
    )

    result = LocalFinQAAnswerer(
        model="qwen-test",
        chat_fn=lambda *args, **kwargs: next(responses),
    ).answer(question=case.qa.question, evidence_units=units)

    assert result.attempt_count == 2


def test_local_finqa_answerer_reports_exhausted_protocol_attempts() -> None:
    case = _case()
    units = rank_finqa_evidence(case, mode="oracle", top_k=5)

    with pytest.raises(FinQAAnswerProtocolError) as captured:
        LocalFinQAAnswerer(
            model="qwen-test",
            chat_fn=lambda *args, **kwargs: (
                '{"final_answer":"L","calculation":"x",'
                '"cited_candidate_ids":["evidence-01"]}'
            ),
            max_attempts=2,
        ).answer(question=case.qa.question, evidence_units=units)

    assert captured.value.code == "structured_output_exhausted"
    assert captured.value.attempt_count == 2
    assert captured.value.admitted_count == 1
    assert captured.value.quarantined_count == 0


def test_local_finqa_answerer_does_not_mask_transport_failures() -> None:
    case = _case()
    units = rank_finqa_evidence(case, mode="oracle", top_k=5)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Ollama unavailable")

    with pytest.raises(RuntimeError, match="Ollama unavailable"):
        LocalFinQAAnswerer(
            model="qwen-test",
            chat_fn=unavailable,
            max_attempts=2,
        ).answer(question=case.qa.question, evidence_units=units)


def test_finqa_protocol_error_becomes_a_scored_auditable_row() -> None:
    case = _case()
    selected = rank_finqa_evidence(case, mode="oracle", top_k=5)
    error = FinQAAnswerProtocolError(
        attempt_count=2,
        latency_ms=125.0,
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=(),
    )

    row = evaluate_finqa_protocol_error(
        case,
        retrieval_mode="oracle",
        selected_units=selected,
        error=error,
    )
    summary = summarize_finqa_cases([row])

    assert row.answer_status == "structured_output_exhausted"
    assert row.answer_parseable is False
    assert row.strict_execution_match is False
    assert row.evidence_recall == 1.0
    assert row.citation_precision == 0.0
    assert row.generation_calls == 2
    assert summary.generation_protocol_error_rate == 1.0
    assert summary.calculator_calls == 0
    assert summary.execution_accuracy == 0.0


def test_rank_finqa_evidence_supports_bm25_dense_and_hybrid() -> None:
    case = _case()

    def embed_batch(texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            rows.append(
                [1.0, 0.0]
                if "revenue" in text.casefold()
                else [0.0, 1.0]
            )
        return np.asarray(rows, dtype=np.float32)

    bm25 = rank_finqa_evidence(case, mode="bm25", top_k=2)
    dense = rank_finqa_evidence(
        case,
        mode="dense",
        top_k=2,
        embed_batch=embed_batch,
    )
    hybrid = rank_finqa_evidence(
        case,
        mode="hybrid",
        top_k=2,
        embed_batch=embed_batch,
    )

    assert "table_1" in {unit.unit_id for unit in bm25}
    assert "table_1" in {unit.unit_id for unit in dense}
    assert "table_1" in {unit.unit_id for unit in hybrid}


def test_finqa_evaluation_separates_answer_retrieval_and_citation() -> None:
    case = _case()
    selected = rank_finqa_evidence(case, mode="oracle", top_k=5)
    answer = FinQAAnswerResult(
        final_answer="20%",
        calculation="(120 - 100) / 100",
        cited_unit_ids=("table_1",),
        provided_unit_ids=("table_1",),
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=(),
        attempt_count=1,
        latency_ms=100.0,
    )

    row = evaluate_finqa_case(
        case,
        retrieval_mode="oracle",
        selected_units=selected,
        answer=answer,
    )
    summary = summarize_finqa_cases([row])

    assert row.strict_execution_match is True
    assert row.presentation_tolerance_match is True
    assert row.evidence_recall == 1.0
    assert row.citation_precision == 1.0
    assert row.citation_recall == 1.0
    assert row.grounded_execution_match is True
    assert row.grounded_presentation_match is True
    assert summary.execution_accuracy == 1.0
    assert summary.presentation_tolerance_accuracy == 1.0
    assert summary.grounded_execution_accuracy == 1.0
    assert summary.grounded_presentation_accuracy == 1.0


def test_finqa_run_is_atomic_immutable_and_reproducible(
    tmp_path: Path,
) -> None:
    case = _case()
    selected = rank_finqa_evidence(case, mode="oracle", top_k=5)
    answer = FinQAAnswerResult(
        final_answer="20%",
        calculation="(120 - 100) / 100",
        cited_unit_ids=("table_1",),
        provided_unit_ids=("table_1",),
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=(),
        attempt_count=1,
        latency_ms=100.0,
    )
    row = evaluate_finqa_case(
        case,
        retrieval_mode="oracle",
        selected_units=selected,
        answer=answer,
    )
    summary = summarize_finqa_cases([row])
    manifest = FinQARunManifest(
        run_id="finqa-dev-oracle-v1",
        split="dev",
        dataset_revision="a" * 40,
        split_sha256="b" * 64,
        selected_case_ids_sha256=selected_case_ids_sha256([case]),
        source_case_count=1,
        selected_case_count=1,
        sample_seed="finqa-dev-v1",
        retrieval_mode="oracle",
        top_k=5,
        answer_model="qwen-test",
        answer_model_sha256="c" * 64,
        embedding_model="none",
        embedding_model_sha256=None,
        code_revision="d" * 40,
        timeout_seconds=120,
        max_attempts=2,
        summary=summary,
    )

    run_dir = publish_finqa_run(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )

    assert verify_finqa_run(run_dir).summary == summary
    with pytest.raises(FileExistsError, match="already exists"):
        publish_finqa_run(
            root=tmp_path,
            manifest=manifest,
            details=[row],
        )


def test_finqa_run_verifier_rejects_tampering(tmp_path: Path) -> None:
    case = _case()
    selected = rank_finqa_evidence(case, mode="oracle", top_k=5)
    answer = FinQAAnswerResult(
        final_answer="20%",
        calculation="(120 - 100) / 100",
        cited_unit_ids=("table_1",),
        provided_unit_ids=("table_1",),
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=(),
        attempt_count=1,
        latency_ms=100.0,
    )
    row = evaluate_finqa_case(
        case,
        retrieval_mode="oracle",
        selected_units=selected,
        answer=answer,
    )
    manifest = FinQARunManifest(
        run_id="finqa-dev-tamper-v1",
        split="dev",
        dataset_revision="a" * 40,
        split_sha256="b" * 64,
        selected_case_ids_sha256=selected_case_ids_sha256([case]),
        source_case_count=1,
        selected_case_count=1,
        sample_seed="finqa-dev-v1",
        retrieval_mode="oracle",
        top_k=5,
        answer_model="qwen-test",
        answer_model_sha256="c" * 64,
        embedding_model="none",
        embedding_model_sha256=None,
        code_revision="d" * 40,
        timeout_seconds=120,
        max_attempts=2,
        summary=summarize_finqa_cases([row]),
    )
    run_dir = publish_finqa_run(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )
    (run_dir / "details.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_finqa_run(run_dir)


def test_finqa_v1_rows_migrate_new_metrics_as_not_available() -> None:
    case = _case()
    selected = rank_finqa_evidence(case, mode="oracle", top_k=5)
    answer = FinQAAnswerResult(
        final_answer="20%",
        calculation="(120 - 100) / 100",
        cited_unit_ids=("table_1",),
        provided_unit_ids=("table_1",),
        admitted_count=1,
        quarantined_count=0,
        guard_rule_ids=(),
        attempt_count=1,
        latency_ms=100.0,
    )
    payload = evaluate_finqa_case(
        case,
        retrieval_mode="oracle",
        selected_units=selected,
        answer=answer,
    ).model_dump(mode="json")
    payload.pop("presentation_tolerance_match")
    payload.pop("grounded_presentation_match")
    payload.pop("answer_status")
    payload.pop("calculator_calls")

    migrated = finqa_eval.FinQACaseEvaluation.model_validate(payload)
    summary = summarize_finqa_cases([migrated])

    assert migrated.presentation_tolerance_match is None
    assert migrated.answer_status is None
    assert summary.presentation_tolerance_accuracy is None
    assert summary.grounded_presentation_accuracy is None
    assert summary.generation_protocol_error_rate is None
    assert summary.calculator_calls is None
