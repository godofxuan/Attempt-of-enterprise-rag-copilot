import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.external_datasets.finqa import FinQACase
from app.external_datasets.finqa_adjudication import (
    FinQAAdjudicationCaseEvaluation,
)
from app.external_datasets.finqa_eval import FinQACaseEvaluation
from app.external_datasets.finqa_selective import (
    FinQASelectiveCaseEvaluation,
    FinQASelectiveExecutionProtocol,
    FinQASelectiveRunManifest,
    publish_finqa_selective_run,
    select_finqa_cases_excluding,
    summarize_finqa_selective_cases,
    verify_finqa_selective_run,
)
from app.external_datasets.finqa_uncertainty import (
    FinQARuntimeUncertainty,
    evaluate_finqa_uncertainty_case,
)


def _case(case_id: str) -> FinQACase:
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
                "answer": "0.2",
                "explanation": "",
                "ann_table_rows": [],
                "ann_text_rows": [],
                "steps": [],
                "program": "divide(subtract(120,100),100)",
                "gold_inds": {"table_1": "private gold annotation"},
                "exe_ans": 0.2,
                "tfidftopn": {},
                "program_re": "divide(subtract(120,100),100)",
                "model_input": [],
            },
            "id": case_id,
            "table_retrieved": [],
            "text_retrieved": [],
            "table_retrieved_all": [],
            "text_retrieved_all": [],
        }
    )


def _evaluation(
    *,
    case_id: str,
    strict: bool,
    generation_calls: int,
    calculator_calls: int,
    latency_ms: float,
) -> FinQACaseEvaluation:
    return FinQACaseEvaluation(
        case_id=case_id,
        retrieval_mode="hybrid",
        selected_unit_ids=["table_1"],
        gold_unit_ids=["table_1"],
        cited_unit_ids=["table_1"],
        final_answer="0.2" if strict else "0.1",
        calculation="(120 - 100) / 100" if strict else "120 - 100",
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


def _full_execution(
    *,
    case_id: str,
    baseline_correct: bool,
    final_correct: bool,
) -> FinQAAdjudicationCaseEvaluation:
    baseline = _evaluation(
        case_id=case_id,
        strict=baseline_correct,
        generation_calls=1,
        calculator_calls=1,
        latency_ms=100,
    )
    proposal = _evaluation(
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
        score=2 if triggered else 1,
        reason_codes=(
            ["multi_operation", "ratio_division"]
            if triggered
            else ["multi_operation"]
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


def _row(
    *,
    case_id: str,
    triggered: bool,
    baseline_correct: bool,
    final_correct: bool,
) -> FinQASelectiveCaseEvaluation:
    execution = _full_execution(
        case_id=case_id,
        baseline_correct=baseline_correct,
        final_correct=final_correct,
    )
    signal = _signal(case_id=case_id, triggered=triggered)
    return FinQASelectiveCaseEvaluation(
        case_id=case_id,
        signal=signal,
        full_strategy_execution=execution,
        policy=evaluate_finqa_uncertainty_case(execution, signal),
        route="adjudicated" if triggered else "baseline",
        production_review_executed=triggered,
        production_adjudication_executed=triggered,
        shadow_review_executed=not triggered,
        shadow_adjudication_executed=not triggered,
        observed_selective_latency_ms=300 if triggered else 100,
        observed_shadow_latency_ms=0 if triggered else 200,
        observed_experiment_latency_ms=300,
    )


def test_selective_sample_is_deterministic_and_excludes_prior_cases() -> None:
    cases = [_case(f"case-{index}") for index in range(10)]
    first = select_finqa_cases_excluding(
        cases,
        excluded_case_ids={"case-0", "case-1"},
        count=4,
        seed="frozen-seed",
    )
    second = select_finqa_cases_excluding(
        list(reversed(cases)),
        excluded_case_ids={"case-1", "case-0"},
        count=4,
        seed="frozen-seed",
    )

    assert [case.id for case in first] == [case.id for case in second]
    assert not {"case-0", "case-1"} & {case.id for case in first}
    with pytest.raises(ValueError, match="unknown"):
        select_finqa_cases_excluding(
            cases,
            excluded_case_ids={"missing"},
            count=1,
            seed="frozen-seed",
        )


def test_shadow_arm_cannot_change_untriggered_policy_output() -> None:
    row = _row(
        case_id="case-1",
        triggered=False,
        baseline_correct=True,
        final_correct=False,
    )

    assert row.policy.gated == row.policy.baseline
    assert row.policy.full_strategy.strict_execution_match is False
    assert row.route == "baseline"
    with pytest.raises(ValidationError, match="flags"):
        row.model_copy(
            update={"production_review_executed": True}
        ).__class__.model_validate(
            {
                **row.model_dump(mode="json"),
                "production_review_executed": True,
            }
        )


def test_selective_summary_reports_quality_cost_and_observed_latency() -> None:
    fixed = _row(
        case_id="case-1",
        triggered=True,
        baseline_correct=False,
        final_correct=True,
    )
    avoided_shadow_regression = _row(
        case_id="case-2",
        triggered=False,
        baseline_correct=True,
        final_correct=False,
    )

    summary = summarize_finqa_selective_cases(
        [fixed, avoided_shadow_regression]
    )

    assert summary.baseline.execution_accuracy == 0.5
    assert summary.selective.execution_accuracy == 1.0
    assert summary.full_strategy.execution_accuracy == 0.5
    assert summary.policy.gated_wrong_to_correct == 1
    assert summary.policy.gated_correct_to_wrong == 0
    assert summary.policy.generation_call_reduction == pytest.approx(0.5)
    assert summary.production_review_case_count == 1
    assert summary.shadow_review_case_count == 1
    assert summary.observed_selective_latency_ms_mean == 200
    assert summary.observed_shadow_latency_ms_total == 200


def test_selective_run_is_immutable_and_reproducible(tmp_path) -> None:
    row = _row(
        case_id="case-1",
        triggered=True,
        baseline_correct=False,
        final_correct=True,
    )
    summary = summarize_finqa_selective_cases([row])
    manifest = FinQASelectiveRunManifest(
        selective_run_id="selective-v1",
        protocol_sha256="a" * 64,
        dataset_revision="b" * 40,
        split="dev",
        split_sha256="c" * 64,
        excluded_case_ids_sha256="d" * 64,
        excluded_case_count=2,
        selected_case_ids_sha256=hashlib.sha256(
            b"case-1\n"
        ).hexdigest(),
        selected_case_count=1,
        sample_seed="frozen-seed",
        retrieval_mode="hybrid",
        top_k=10,
        answer_model="qwen3:8b",
        answer_model_sha256="e" * 64,
        review_model="qwen3-coder:30b",
        review_model_sha256="f" * 64,
        adjudicator_model="qwen3:8b",
        adjudicator_model_sha256="e" * 64,
        embedding_model="bge-m3",
        embedding_model_sha256="1" * 64,
        runtime_backend="ollama_cuda",
        code_revision="2" * 40,
        timeout_seconds=180,
        max_attempts=2,
        summary=summary,
    )

    run_dir = publish_finqa_selective_run(
        root=tmp_path,
        manifest=manifest,
        details=[row],
    )
    verified = verify_finqa_selective_run(run_dir)

    assert verified.summary == summary
    with pytest.raises(FileExistsError):
        publish_finqa_selective_run(
            root=tmp_path,
            manifest=manifest,
            details=[row],
        )
    (run_dir / "summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact mismatch"):
        verify_finqa_selective_run(run_dir)


def test_frozen_selective_protocol_binds_public_sources_without_content() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    protocol_path = (
        repository_root
        / "docs"
        / "external_datasets"
        / "evidence"
        / "finqa_selective_execution_protocol_v1.json"
    )
    protocol = FinQASelectiveExecutionProtocol.model_validate_json(
        protocol_path.read_bytes()
    )

    assert protocol.status == "FROZEN_BEFORE_EXECUTION"
    assert protocol.excluded_case_count == 150
    assert protocol.sample_count == 100
    assert protocol.overlap_with_excluded_case_count == 0
    assert protocol.runtime_backend_requirement == "normal_cuda_no_vulkan"
    for relative_path, expected_sha256 in protocol.source_sha256.items():
        assert (
            hashlib.sha256(
                (repository_root / relative_path).read_bytes()
            ).hexdigest()
            == expected_sha256
        )
    payload = json.loads(protocol_path.read_text(encoding="utf-8"))

    def collect_keys(value):
        if isinstance(value, dict):
            return set(value) | {
                key
                for child in value.values()
                for key in collect_keys(child)
            }
        if isinstance(value, list):
            return {
                key for child in value for key in collect_keys(child)
            }
        return set()

    assert not {
        "question",
        "answer",
        "exe_ans",
        "program",
        "calculation",
        "case_id",
    } & collect_keys(payload)
