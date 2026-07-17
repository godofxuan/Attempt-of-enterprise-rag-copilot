from __future__ import annotations

from dataclasses import dataclass

from app.corpus.schemas import EvalCase, EvalUserContext
from app.evaluation.retrieval import evaluate_retrieval_case
from tests.v2_test_support import search_hit, search_result


def eval_case(**updates) -> EvalCase:
    values = {
        "case_id": "case-one",
        "question": "当前 Policy A 的规则是什么？",
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
        "expected_answer": "three days",
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


@dataclass
class StubPipeline:
    result: object

    def __post_init__(self) -> None:
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return self.result


def test_retrieval_scores_unique_documents_not_duplicate_chunks() -> None:
    pipeline = StubPipeline(
        search_result(
            [
                search_hit(chunk_id="a-1", doc_id="doc-a"),
                search_hit(chunk_id="a-2", doc_id="doc-a"),
                search_hit(chunk_id="x-1", doc_id="extra"),
                search_hit(chunk_id="b-1", doc_id="doc-b"),
            ]
        )
    )
    case = eval_case(
        gold_doc_ids=["doc-a", "doc-b"],
        expected_authority_doc_ids=["doc-a", "doc-b"],
        required_fact_ids=["fact-a", "fact-b"],
    )

    evaluated = evaluate_retrieval_case(case, pipeline, top_k=5, candidate_k=20)

    assert evaluated.observation.ranked_doc_ids == ["doc-a", "extra", "doc-b"]
    assert evaluated.layer.metrics["document_recall@5"] == 1.0
    assert evaluated.layer.metrics["precision@5"] == 0.4
    assert evaluated.layer.metrics["invalid_extra_documents@5"] == 1.0
    assert evaluated.layer.passed is True


def test_retrieval_partial_gold_coverage_is_ranking_failure() -> None:
    pipeline = StubPipeline(search_result([search_hit(doc_id="doc-a")]))
    case = eval_case(
        gold_doc_ids=["doc-a", "doc-b"],
        expected_authority_doc_ids=["doc-a", "doc-b"],
        required_fact_ids=["fact-a", "fact-b"],
    )

    evaluated = evaluate_retrieval_case(case, pipeline)

    assert evaluated.layer.passed is False
    assert {failure.stage for failure in evaluated.layer.failures} == {
        "ranking",
        "conflict_resolution",
    }
    assert all("doc-b" not in failure.message for failure in evaluated.layer.failures)


def test_retrieval_zero_gold_case_is_valid_without_ranking_denominator() -> None:
    pipeline = StubPipeline(search_result([], stop_reason="no_match"))
    case = eval_case(
        task_type="no_answer",
        answer_mode="not_found",
        required_fact_ids=[],
        gold_doc_ids=[],
        expected_answer=None,
        expected_authority_doc_ids=[],
        tags=["no_answer"],
    )

    evaluated = evaluate_retrieval_case(case, pipeline)

    assert evaluated.layer.passed is True
    assert evaluated.layer.metrics["document_recall@5"] is None
    assert evaluated.layer.metrics["acl_leakage_count"] == 0


def test_retrieval_forbidden_document_is_acl_failure_without_id_in_message() -> None:
    pipeline = StubPipeline(
        search_result([search_hit(doc_id="forbidden-doc", chunk_id="secret-1")])
    )
    case = eval_case(
        task_type="permission",
        answer_mode="permission",
        required_fact_ids=[],
        gold_doc_ids=[],
        forbidden_doc_ids=["forbidden-doc"],
        expected_answer=None,
        expected_authority_doc_ids=[],
        tags=["permission", "acl"],
    )

    evaluated = evaluate_retrieval_case(case, pipeline)

    assert evaluated.layer.passed is False
    assert evaluated.layer.metrics["acl_leakage_count"] == 1
    failure = evaluated.layer.failures[0]
    assert failure.stage == "acl"
    assert "forbidden-doc" not in failure.message


def test_production_variant_uses_analysis_filters_and_bounded_request() -> None:
    pipeline = StubPipeline(search_result([search_hit()]))
    case = eval_case(question="当前 Policy A 的规则是什么？")

    evaluate_retrieval_case(case, pipeline, top_k=3, candidate_k=12)

    request = pipeline.requests[0]
    assert request.mode == "hybrid"
    assert request.top_k == 3
    assert request.candidate_k == 12
    assert request.include_parent is True
    assert request.max_chunks_per_doc == 2
    assert request.filters.temporal_scope == "current"
    assert request.filters.authoritative_only is True


def test_timeout_is_system_runtime_failure() -> None:
    pipeline = StubPipeline(search_result([], stop_reason="timeout"))

    evaluated = evaluate_retrieval_case(eval_case(), pipeline)

    assert evaluated.layer.passed is False
    assert evaluated.layer.failures[0].stage == "system_runtime"
    assert evaluated.layer.failures[0].code == "retrieval_timeout"
