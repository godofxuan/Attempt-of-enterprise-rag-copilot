from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.documents import SourceLocator
from app.domain.queries import SearchHit
from app.external_datasets.finqa import FinQAEvidenceUnit
from app.external_datasets.finqa_eval import FinQAAnswerProtocolError, FinQAAnswerResult
from app.external_datasets.uda_finance_r3 import UdaFinanceR3PreparedCase
from app.external_datasets.uda_finance_r3_answer_eval import (
    R3NumericCandidate,
    R3TypedPlan,
    evidence_from_hits,
    evaluate_answer_result,
    execute_typed_plan,
    extract_numeric_candidates,
    load_answer_protocol,
    parse_numeric_surface,
    parse_typed_plan,
    summarize_answer_results,
    uda_answer_match,
)
from scripts.eval_uda_finance_r3_answers import claim_split_execution


def _unit(index: int, text: str) -> FinQAEvidenceUnit:
    return FinQAEvidenceUnit(
        unit_id=f"text_{index}", kind="text", ordinal=index, text=text
    )


def _candidate(candidate_id: str, value: str) -> R3NumericCandidate:
    return R3NumericCandidate(
        candidate_id=candidate_id,
        unit_id="text_0",
        surface=value,
        value=value,
        context=f"value was {value}",
    )


def _case() -> UdaFinanceR3PreparedCase:
    return UdaFinanceR3PreparedCase(
        case_id="uda-r3-test",
        split="dev",
        company_id="ABC",
        doc_name="ABC_2020",
        q_uid="ABC_2020.pdf_1_1",
        question="What was the change?",
        answers=["20%", "0.2"],
        gold_doc_id="uda-fin-abc-2020",
        page_number=7,
    )


def _hit(page: int) -> SearchHit:
    return SearchHit(
        index_run_id="r3-index",
        chunk_id=f"chunk-{page}",
        doc_id="uda-fin-abc-2020",
        policy_id="uda-fin-abc-2020",
        source_path="documents/ABC_2020.pdf",
        section_path=[f"Page {page}"],
        locator=SourceLocator(kind="page", start=page, end=page),
        matched_text=f"Revenue was {page}.",
        context_text=f"Revenue was {page}.",
        tenant_id="uda-external",
        region="global",
        acl_groups=["uda-evaluator"],
        version_id="uda-fin-abc-2020-r3-v1",
        version="r3.1",
        status="active",
        authority_level=90,
        variant="authoritative",
        fused_score=1.0,
        dense_score=1.0,
        dense_rank=1,
    )


def test_numeric_surface_handles_financial_notation() -> None:
    assert parse_numeric_surface("$1,250.50") == Decimal("1250.50")
    assert parse_numeric_surface("(42)") == Decimal("-42")
    assert parse_numeric_surface("20%") == Decimal("0.2")
    with pytest.raises(ValueError):
        parse_numeric_surface("(42")


def test_candidate_extraction_round_robins_before_deeper_values() -> None:
    candidates = extract_numeric_candidates(
        [_unit(0, "first 10 then 11 then 12"), _unit(1, "second 20 then 21")],
        max_candidates=4,
    )

    assert [(item.unit_id, item.value) for item in candidates] == [
        ("text_0", "10"),
        ("text_1", "20"),
        ("text_0", "11"),
        ("text_1", "21"),
    ]


def test_typed_plan_enforces_ids_arity_and_citation_coverage() -> None:
    candidates = [_candidate("n001", "100"), _candidate("n002", "120")]
    plan = parse_typed_plan(
        '{"operation":"percent_change","operand_ids":["n001","n002"],'
        '"cited_candidate_ids":["n001","n002"]}',
        candidates,
    )

    assert execute_typed_plan(plan, {item.candidate_id: item for item in candidates}) == Decimal(
        "0.2"
    )
    with pytest.raises(ValueError):
        R3TypedPlan(
            operation="divide", operand_ids=["n001"], cited_candidate_ids=["n001"]
        )
    with pytest.raises(ValueError):
        parse_typed_plan(
            '{"operation":"subtract","operand_ids":["n001","n002"],'
            '"cited_candidate_ids":["n001"]}',
            candidates,
        )


def test_uda_match_uses_symmetric_one_percent_tolerance() -> None:
    assert uda_answer_match("20%", ["0.2"])
    assert uda_answer_match("100.9", ["100"])
    assert not uda_answer_match("102", ["100"])
    assert uda_answer_match("YES", ["yes"])


def test_evidence_mapping_and_summary_are_reproducible() -> None:
    units, pages_by_unit, retrieved_pages = evidence_from_hits([_hit(7), _hit(9)])
    answer = FinQAAnswerResult(
        final_answer="0.2",
        calculation="percent_change(n001,n002)",
        cited_unit_ids=(units[0].unit_id,),
        provided_unit_ids=tuple(item.unit_id for item in units),
        admitted_count=2,
        quarantined_count=0,
        guard_rule_ids=(),
        attempt_count=1,
        latency_ms=50,
        calculator_calls=1,
    )
    row = evaluate_answer_result(
        case=_case(),
        strategy="typed_candidate",
        answer=answer,
        status="ok",
        pages_by_unit=pages_by_unit,
        retrieved_pages=retrieved_pages,
        retrieval_latency_ms=10,
        generation_calls=1,
    )
    summary = summarize_answer_results([row], strategy="typed_candidate")

    assert row.answer_correct and row.grounded_answer_correct
    assert summary.numeric_accuracy == 1
    assert summary.citation_precision == 1
    assert summary.latency_ms_p95 == 60


def test_protocol_failure_keeps_failure_telemetry() -> None:
    error = FinQAAnswerProtocolError(
        attempt_count=2,
        latency_ms=75,
        admitted_count=4,
        quarantined_count=1,
        guard_rule_ids=("instruction_override",),
        code="program_output_exhausted",
        calculator_calls=2,
    )
    row = evaluate_answer_result(
        case=_case(),
        strategy="typed_candidate",
        answer=None,
        status="protocol_error",
        pages_by_unit={},
        retrieved_pages=[],
        retrieval_latency_ms=10,
        generation_calls=2,
        protocol_error=error,
    )

    assert row.total_latency_ms == 85
    assert row.admitted_count == 4
    assert row.quarantined_count == 1
    assert row.calculator_calls == 2
    assert row.guard_rule_ids == ["instruction_override"]


def test_answer_protocol_is_frozen_and_bound() -> None:
    protocol, digest = load_answer_protocol()

    assert len(digest) == 64
    assert protocol["index_manifest_sha256"] == (
        "08773dde88cf71bbccc199a45390af89802355a2f3ca7ff1482e3901513ba27b"
    )
    assert protocol["answer_model"] == "qwen3:8b"
    assert protocol["promotion_gates"]["min_numeric_accuracy_delta"] == 0.05
    assert protocol["typed_contract"]["max_candidates"] == 32
    assert protocol["typed_contract"]["raw_numeric_literals_in_plan"] is False


def test_answer_validation_marker_is_one_shot(tmp_path: Path) -> None:
    kwargs = {
        "split": "validation",
        "run_id": "r3-answer-validation-v1",
        "code_revision": "a" * 40,
        "answer_protocol_sha256": "b" * 64,
        "cases_sha256": "c" * 64,
        "strategies": ["direct", "typed_candidate"],
    }
    marker = claim_split_execution(tmp_path, **kwargs)

    assert marker.is_file()
    with pytest.raises(FileExistsError):
        claim_split_execution(tmp_path, **kwargs)
