from __future__ import annotations

from app.corpus.schemas import EvalCase, EvalUserContext
from app.domain.evidence import AnswerResponse, AnswerSource, Claim, ClaimCitation
from app.evaluation.answer import evaluate_answer_case
from tests.v2_test_support import search_hit


def eval_case(**updates) -> EvalCase:
    values = {
        "case_id": "case-one",
        "question": "Policy A 允许多少天？",
        "task_type": "fact_lookup",
        "answer_mode": "answered",
        "user_context": EvalUserContext(
            user_id="employee-one",
            tenant="tenant-one",
            region="cn",
            groups=["employees"],
        ),
        "required_fact_ids": ["fact-a"],
        "gold_doc_ids": ["doc-a"],
        "distractor_doc_ids": [],
        "forbidden_doc_ids": [],
        "expected_answer": "3 天",
        "expected_filters": {
            "tenant": "tenant-one",
            "region": "cn",
            "acl_groups": ["employees"],
        },
        "expected_authority_doc_ids": ["doc-a"],
        "tags": ["current", "atomic_fact"],
    }
    values.update(updates)
    return EvalCase(**values)


def answered_response(
    *,
    mode: str = "answered",
    answer: str = "Policy A 允许 3 天。",
    doc_id: str = "doc-a",
    chunk_id: str = "chunk-a",
    supported: bool = True,
) -> AnswerResponse:
    citation = ClaimCitation(
        claim_id="claim-1",
        cited_chunk_ids=[chunk_id],
        citation_present=True,
        references_visible_evidence=True,
        lexical_support=1.0 if supported else 0.0,
        supported=supported,
        unsupported_reason=None if supported else "no lexical support",
    )
    return AnswerResponse(
        mode=mode,
        answer=answer,
        claims=[
            Claim(
                claim_id="claim-1",
                text=answer,
                critical=True,
                cited_chunk_ids=[chunk_id],
            )
        ],
        citations=[citation],
        sources=[
            AnswerSource(
                doc_id=doc_id,
                source_path=f"documents/{doc_id}.md",
                section_path=["Policy"],
                chunk_id=chunk_id,
                preview=answer,
            )
        ],
        stop_reason="completed" if mode == "answered" else "partial_evidence",
    )


def test_answer_full_fact_and_supported_citation_is_correct() -> None:
    response = answered_response()
    chunks = {"chunk-a": search_hit(chunk_id="chunk-a", fact_ids=["fact-a"])}

    evaluated = evaluate_answer_case(eval_case(), response, chunks)

    assert evaluated.layer.passed is True
    assert evaluated.layer.metrics["correctness"] is True
    assert evaluated.layer.metrics["atomic_fact_completeness"] == 1.0
    assert evaluated.layer.metrics["citation_coverage"] == 1.0
    assert evaluated.layer.metrics["citation_correctness"] == 1.0
    assert evaluated.layer.metrics["unsupported_claim_rate"] == 0.0
    assert evaluated.cited_fact_ids == ["fact-a"]


def test_answer_missing_required_fact_is_generation_failure() -> None:
    case = eval_case(
        required_fact_ids=["fact-a", "fact-b"],
        expected_answer="3 天；提前 2 天",
    )
    response = answered_response()
    chunks = {"chunk-a": search_hit(chunk_id="chunk-a", fact_ids=["fact-a"])}

    evaluated = evaluate_answer_case(case, response, chunks)

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["atomic_fact_completeness"] == 0.5
    assert any(
        failure.stage == "generation" and failure.code == "required_fact_omission"
        for failure in evaluated.layer.failures
    )


def test_answer_unsupported_critical_claim_is_citation_failure() -> None:
    response = answered_response(supported=False)
    chunks = {"chunk-a": search_hit(chunk_id="chunk-a", fact_ids=["fact-a"])}

    evaluated = evaluate_answer_case(eval_case(), response, chunks)

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["unsupported_claim_rate"] == 1.0
    assert any(
        failure.stage == "citation_verification"
        for failure in evaluated.layer.failures
    )


def test_version_conflict_requires_expected_authority_source() -> None:
    case = eval_case(
        task_type="version_conflict",
        gold_doc_ids=["doc-current"],
        distractor_doc_ids=["doc-retired"],
        expected_authority_doc_ids=["doc-current"],
    )
    response = answered_response(doc_id="doc-retired", chunk_id="old-chunk")
    chunks = {
        "old-chunk": search_hit(
            chunk_id="old-chunk",
            doc_id="doc-retired",
            fact_ids=["fact-a"],
            status="retired",
            version="2025",
            version_id="policy-a@2025",
        )
    }

    evaluated = evaluate_answer_case(case, response, chunks)

    assert evaluated.layer.metrics["conflict_resolution_accuracy"] is False
    assert any(
        failure.stage == "conflict_resolution"
        for failure in evaluated.layer.failures
    )


def test_permission_mode_is_scored_without_answer_or_source_denominator() -> None:
    case = eval_case(
        task_type="permission",
        answer_mode="permission",
        required_fact_ids=[],
        gold_doc_ids=[],
        forbidden_doc_ids=["hidden"],
        expected_answer=None,
        expected_authority_doc_ids=[],
        tags=["permission", "acl"],
    )
    response = AnswerResponse(
        mode="permission",
        answer="The requested resource is unavailable for this identity.",
        stop_reason="permission",
    )

    evaluated = evaluate_answer_case(case, response, {})

    assert evaluated.layer.passed is True
    assert evaluated.layer.metrics["correctness"] is True
    assert evaluated.layer.metrics["refusal_accuracy"] is True
    assert evaluated.layer.metrics["atomic_fact_completeness"] is None
    assert evaluated.layer.metrics["citation_coverage"] is None


def test_partial_answer_reports_supported_fact_quality_but_is_not_full_correct() -> None:
    case = eval_case(
        required_fact_ids=["fact-a", "fact-b"],
        expected_answer="3 天；提前 2 天",
    )
    response = answered_response(mode="partial")
    chunks = {"chunk-a": search_hit(chunk_id="chunk-a", fact_ids=["fact-a"])}

    evaluated = evaluate_answer_case(case, response, chunks)

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["partial_answer_quality"] == 0.5
    assert evaluated.layer.metrics["correctness"] is False
    assert any(
        failure.code == "answer_mode_mismatch"
        for failure in evaluated.layer.failures
    )


def test_expected_answer_signal_is_auxiliary_not_a_hard_semantic_judge() -> None:
    response = answered_response(answer="同义改写但不含 gold 原句")
    chunks = {"chunk-a": search_hit(chunk_id="chunk-a", fact_ids=["fact-a"])}

    evaluated = evaluate_answer_case(eval_case(), response, chunks)

    assert evaluated.layer.metrics["expected_answer_signal"] == 0.0
    assert evaluated.layer.metrics["correctness"] is True
    assert evaluated.layer.passed is True
