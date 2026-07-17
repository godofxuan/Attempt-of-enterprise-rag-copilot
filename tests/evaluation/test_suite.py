from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.corpus.schemas import EvalCase, EvalUserContext
from app.domain.agent import AgentBudget
from app.domain.evidence import AnswerResponse, AnswerSource, Claim, ClaimCitation
from app.evaluation.suite import evaluate_suite
from tests.v2_test_support import search_hit, search_result


def eval_case(case_id: str, question: str) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question=question,
        task_type="fact_lookup",
        answer_mode="answered",
        user_context=EvalUserContext(
            user_id="employee-one",
            tenant="tenant-one",
            region="cn",
            groups=["employees"],
        ),
        required_fact_ids=["fact-a"],
        gold_doc_ids=["doc-a"],
        distractor_doc_ids=[],
        forbidden_doc_ids=["hidden-doc"],
        expected_answer="3 days",
        expected_filters={},
        expected_authority_doc_ids=["doc-a"],
        tags=["current", "atomic_fact"],
    )


def agent_trace(*, unsafe: bool = False) -> dict:
    if unsafe:
        budget = {
            "search_calls": 0,
            "find_calls": 0,
            "open_calls": 0,
            "steps": 0,
            "context_chars": 0,
        }
        return {
            "intent": "unsafe",
            "analysis_source": "rules",
            "required_aspect_count": 0,
            "steps": [
                {
                    "sequence": 1,
                    "tool": "refuse",
                    "status": "terminal",
                    "latency_ms": 0.0,
                    "visible_count": 0,
                    "context_chars_added": 0,
                    "error_code": None,
                    "budget": budget,
                }
            ],
            "stop_reason": "unsafe",
            "budget": budget,
        }
    budget = {
        "search_calls": 1,
        "find_calls": 0,
        "open_calls": 0,
        "steps": 1,
        "context_chars": 100,
    }
    return {
        "intent": "fact",
        "analysis_source": "rules",
        "required_aspect_count": 1,
        "steps": [
            {
                "sequence": 1,
                "tool": "search",
                "status": "ok",
                "latency_ms": 1.0,
                "visible_count": 1,
                "context_chars_added": 100,
                "error_code": None,
                "budget": budget,
            },
            {
                "sequence": 2,
                "tool": "answer",
                "status": "terminal",
                "latency_ms": 0.0,
                "visible_count": 0,
                "context_chars_added": 0,
                "error_code": None,
                "budget": budget,
            },
        ],
        "stop_reason": "completed",
        "budget": budget,
    }


def answered_response() -> AnswerResponse:
    return AnswerResponse(
        mode="answered",
        answer="Policy A allows 3 days.",
        claims=[
            Claim(
                claim_id="c1",
                text="Policy A allows 3 days.",
                cited_chunk_ids=["chunk-a"],
            )
        ],
        citations=[
            ClaimCitation(
                claim_id="c1",
                cited_chunk_ids=["chunk-a"],
                citation_present=True,
                references_visible_evidence=True,
                lexical_support=1.0,
                supported=True,
            )
        ],
        sources=[
            AnswerSource(
                doc_id="doc-a",
                source_path="documents/doc-a.md",
                section_path=["Policy"],
                chunk_id="chunk-a",
                preview="Policy A allows 3 days.",
            )
        ],
        stop_reason="completed",
        trace=agent_trace(),
    )


@dataclass
class FakeCounters:
    embedding_calls: int = 0
    generation_calls: int = 0

    @property
    def model_calls(self) -> int:
        return self.embedding_calls + self.generation_calls


class FakePipeline:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def search(self, request):
        self.calls.append(request)
        return self.result


class FakeRunner:
    def __init__(self, case_questions: set[str]) -> None:
        self.case_questions = case_questions
        self.calls: list[str] = []

    def run(self, question, user, top_k=None):
        self.calls.append(question)
        if question in self.case_questions:
            return answered_response()
        return AnswerResponse(
            mode="unsafe",
            answer="The unsafe request was refused.",
            stop_reason="unsafe",
            trace=agent_trace(unsafe=True),
        )


def fake_runtime(cases: list[EvalCase], *, retrieval_hits=True):
    hit = search_hit(
        chunk_id="chunk-a",
        doc_id="doc-a",
        fact_ids=["fact-a"],
    )
    pipeline = FakePipeline(
        search_result([hit] if retrieval_hits else [], stop_reason=None)
    )
    runner = FakeRunner({case.question for case in cases})
    return SimpleNamespace(
        mode="deterministic",
        variant="test-runtime",
        pipeline=pipeline,
        runner=runner,
        budget=AgentBudget(),
        counters=FakeCounters(),
        snapshot=SimpleNamespace(all_chunks_by_id={"chunk-a": hit}),
    )


def test_all_suite_runs_each_case_response_once_and_fans_out_four_layers() -> None:
    cases = [eval_case("case-1", "Question one"), eval_case("case-2", "Question two")]
    runtime = fake_runtime(cases)

    result = evaluate_suite(
        cases,
        runtime,
        run_id="run-one",
        suite="all",
        split="dev",
        top_k=5,
        candidate_k=20,
        bootstrap_iterations=200,
    )

    assert result.case_count == 2
    assert all(len(detail.layers) == 4 for detail in result.details)
    assert all(detail.passed for detail in result.details)
    assert runtime.runner.calls.count("Question one") == 1
    assert runtime.runner.calls.count("Question two") == 1
    assert len(runtime.runner.calls) == len(cases) + 4
    assert len(result.security_probes) == 4
    assert result.summary["overall_case_pass"]["passed"] == 2
    assert result.summary["overall_case_pass"]["total"] == 2
    assert result.summary["overall_case_pass"]["rate"] == 1.0
    assert result.summary["layers"]["answer"]["pass_rate"]["rate"] == 1.0
    assert any(
        row["category_type"] == "task_type"
        and row["category"] == "fact_lookup"
        and row["count"] == 2
        for row in result.metrics_by_category
    )
    serialized = result.model_dump_json()
    assert "hidden-doc" not in serialized
    assert "Question one" not in serialized


def test_retrieval_only_suite_never_calls_agent_or_security_probes() -> None:
    cases = [eval_case("case-1", "Question one")]
    runtime = fake_runtime(cases)

    result = evaluate_suite(
        cases,
        runtime,
        run_id="run-retrieval",
        suite="retrieval",
        split="dev",
    )

    assert runtime.runner.calls == []
    assert len(result.details[0].layers) == 1
    assert result.details[0].layers[0].layer == "retrieval"
    assert result.details[0].actual_mode == "not_evaluated"
    assert result.security_probes == []


def test_suite_attributes_retrieval_failure_as_primary() -> None:
    cases = [eval_case("case-1", "Question one")]
    runtime = fake_runtime(cases, retrieval_hits=False)

    result = evaluate_suite(
        cases,
        runtime,
        run_id="run-failure",
        suite="all",
        split="dev",
    )

    detail = result.details[0]
    assert detail.passed is False
    assert detail.primary_failure == "retrieval"
    assert any(layer.layer == "answer" and layer.passed for layer in detail.layers)


def test_category_rows_include_tags_without_questions_or_forbidden_ids() -> None:
    cases = [eval_case("case-1", "Question one")]
    result = evaluate_suite(
        cases,
        fake_runtime(cases),
        run_id="run-categories",
        suite="retrieval",
        split="dev",
    )

    tags = {
        row["category"]
        for row in result.metrics_by_category
        if row["category_type"] == "tag"
    }
    assert tags == {"current", "atomic_fact"}
    assert all("question" not in row for row in result.metrics_by_category)
    assert "hidden-doc" not in str(result.metrics_by_category)


def test_explicit_private_response_sink_captures_answers_without_public_details() -> None:
    cases = [eval_case("case-1", "Question one")]
    private_answers: dict[str, str] = {}

    result = evaluate_suite(
        cases,
        fake_runtime(cases),
        run_id="run-private-review",
        suite="answer",
        split="regression",
        response_sink=private_answers,
    )

    assert private_answers == {"case-1": "Policy A allows 3 days."}
    assert "Policy A allows 3 days." not in result.model_dump_json()
