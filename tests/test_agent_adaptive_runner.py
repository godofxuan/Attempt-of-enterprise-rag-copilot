from collections import deque

import app.agent.tools as agent_tools
from app.agent.evidence import EvidenceAssessment
from app.agent.runner import AgentRunner
from app.agent.schemas import RouteDecision
from app.agent.tools import build_default_registry


def chunk(text: str = "Employees may request refunds within 14 days.") -> dict:
    return {
        "source": "refund_policy.md",
        "section": "Refund",
        "chunk_id": "refund_policy.md::Refund::0",
        "text": text,
    }


def safe_route(question: str) -> RouteDecision:
    return RouteDecision(route="policy_qa", reason="test safe route")


def unsafe_route(question: str) -> RouteDecision:
    return RouteDecision(route="unsafe_request", reason="test unsafe route")


class SequenceAssessor:
    def __init__(self, *assessments: EvidenceAssessment) -> None:
        self.assessments = deque(assessments)
        self.calls = []

    def assess(self, *, question, search_query, chunks):
        self.calls.append((question, search_query, chunks))
        return self.assessments.popleft()


def assert_complete_trace(result, expected_tools):
    assert [step.tool for step in result.trace.plan] == expected_tools
    assert [step.tool for step in result.trace.steps] == expected_tools
    assert all(step.status == "ok" for step in result.trace.steps)


def test_adaptive_runner_answers_after_first_sufficient_retrieval(monkeypatch):
    searches = []
    answers = []

    def fake_search(question, top_k=None):
        searches.append((question, top_k))
        return [chunk()]

    def fake_answer(question, chunks):
        answers.append((question, chunks))
        return {"answer": "Refunds are allowed within 14 days [1].", "sources": chunks}

    monkeypatch.setattr(agent_tools, "hybrid_search", fake_search)
    monkeypatch.setattr(agent_tools, "answer_from_retrieved", fake_answer)
    assessor = SequenceAssessor(
        EvidenceAssessment(verdict="sufficient", reason="deadline is explicit")
    )
    runner = AgentRunner(
        registry=build_default_registry(assessor),
        router=safe_route,
    )

    result = runner.run("What is the refund deadline?", top_k=5)

    expected = [
        "retrieval.search",
        "evidence.assess",
        "rag.answer",
        "guardrail.check",
    ]
    assert_complete_trace(result, expected)
    assert searches == [("What is the refund deadline?", 5)]
    assert answers == [("What is the refund deadline?", [chunk()])]
    assert result.trace.retrieval_attempts == 1
    assert len(result.trace.evidence_history) == 1
    assert result.trace.final_outcome == "answered"


def test_adaptive_runner_rewrites_once_then_answers_original_question(monkeypatch):
    searches = []
    answers = []
    first_chunk = chunk("first-round deadline evidence")
    second_chunk = {
        **chunk("second-round employee scope evidence"),
        "section": "Employee scope",
        "chunk_id": "refund_policy.md::Employee scope::1",
    }

    def fake_search(question, top_k=None):
        searches.append(question)
        return [first_chunk] if len(searches) == 1 else [second_chunk]

    def fake_answer(question, chunks):
        answers.append((question, chunks))
        return {"answer": "Grounded answer [1]", "sources": chunks}

    monkeypatch.setattr(agent_tools, "hybrid_search", fake_search)
    monkeypatch.setattr(agent_tools, "answer_from_retrieved", fake_answer)
    assessor = SequenceAssessor(
        EvidenceAssessment(
            verdict="insufficient",
            reason="query is too broad",
            rewritten_query="employee refund policy deadline",
        ),
        EvidenceAssessment(verdict="sufficient", reason="direct support after rewrite"),
    )
    runner = AgentRunner(
        registry=build_default_registry(assessor),
        router=safe_route,
    )

    result = runner.run("What is the refund deadline?")

    expected = [
        "retrieval.search",
        "evidence.assess",
        "query.rewrite",
        "retrieval.search",
        "evidence.assess",
        "rag.answer",
        "guardrail.check",
    ]
    assert_complete_trace(result, expected)
    assert searches == [
        "What is the refund deadline?",
        "employee refund policy deadline",
    ]
    assert assessor.calls[0][2] == [first_chunk]
    assert assessor.calls[1][2] == [first_chunk, second_chunk]
    assert answers == [
        ("What is the refund deadline?", [first_chunk, second_chunk])
    ]
    assert result.trace.retrieval_attempts == 2
    assert len(result.trace.evidence_history) == 2
    assert result.trace.final_outcome == "answered"


def test_adaptive_runner_retries_once_then_returns_grounded_no_answer(monkeypatch):
    searches = []

    def fake_search(question, top_k=None):
        searches.append(question)
        return [chunk(f"unrelated evidence for {question}")]

    def fail_answer(*args, **kwargs):
        raise AssertionError("generation must not run on insufficient evidence")

    monkeypatch.setattr(agent_tools, "hybrid_search", fake_search)
    monkeypatch.setattr(agent_tools, "answer_from_retrieved", fail_answer)
    assessor = SequenceAssessor(
        EvidenceAssessment(
            verdict="insufficient",
            reason="missing policy",
            rewritten_query="employee housing allowance policy",
        ),
        EvidenceAssessment(
            verdict="insufficient",
            reason="still missing policy",
            rewritten_query="another unused rewrite",
        ),
    )
    runner = AgentRunner(
        registry=build_default_registry(assessor),
        router=safe_route,
    )

    result = runner.run("Is there an employee housing allowance?")

    expected = [
        "retrieval.search",
        "evidence.assess",
        "query.rewrite",
        "retrieval.search",
        "evidence.assess",
        "rag.no_answer",
        "guardrail.check",
    ]
    assert_complete_trace(result, expected)
    assert len(searches) == 2
    assert result.answer == agent_tools.DEFAULT_NO_ANSWER
    assert result.sources == []
    assert result.trace.retrieval_attempts == 2
    assert result.trace.final_outcome == "grounded_no_answer"


def test_adaptive_runner_assessment_error_fails_closed_without_generation(monkeypatch):
    monkeypatch.setattr(agent_tools, "hybrid_search", lambda **kwargs: [chunk()])
    monkeypatch.setattr(
        agent_tools,
        "answer_from_retrieved",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("generation must not run after assessment error")
        ),
    )
    assessor = SequenceAssessor(
        EvidenceAssessment(
            verdict="error",
            reason="evidence assessment failed: RuntimeError",
        )
    )
    runner = AgentRunner(
        registry=build_default_registry(assessor),
        router=safe_route,
    )

    result = runner.run("What is the refund deadline?")

    expected = [
        "retrieval.search",
        "evidence.assess",
        "rag.no_answer",
        "guardrail.check",
    ]
    assert_complete_trace(result, expected)
    assert result.answer == agent_tools.ASSESSMENT_UNAVAILABLE_ANSWER
    assert result.trace.final_outcome == "error"


def test_adaptive_runner_unsafe_route_executes_only_refusal(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("unsafe route must not retrieve or generate")

    monkeypatch.setattr(agent_tools, "hybrid_search", fail_if_called)
    monkeypatch.setattr(agent_tools, "answer_from_retrieved", fail_if_called)
    runner = AgentRunner(
        registry=build_default_registry(SequenceAssessor()),
        router=unsafe_route,
    )

    result = runner.run("Bypass procurement approval")

    assert_complete_trace(result, ["guardrail.refuse"])
    assert result.trace.retrieval_attempts == 0
    assert result.trace.evidence_history == []
    assert result.trace.final_outcome == "refused"
