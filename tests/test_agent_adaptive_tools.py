import pytest

import app.agent.tools as agent_tools
from app.agent.evidence import EvidenceAssessment


def chunk(text: str = "Policy says refund requests after 14 days are rejected.") -> dict:
    return {
        "source": "refund_policy.md",
        "section": "Refund",
        "chunk_id": "refund_policy.md::Refund::0",
        "text": text,
    }


def test_retrieval_uses_search_query_and_keeps_original_question(monkeypatch):
    calls = []

    def fake_search(question, top_k=None):
        calls.append((question, top_k))
        return [chunk()]

    monkeypatch.setattr(agent_tools, "hybrid_search", fake_search)
    context = {
        "question": "original question",
        "search_query": "rewritten search query",
        "top_k": 5,
        "retrieval_attempts": 1,
    }

    result = agent_tools.retrieval_search_tool(context)

    assert calls == [("rewritten search query", 5)]
    assert result.updates["retrieval_attempts"] == 2
    assert result.updates["retrieved_chunks"] == [chunk()]
    assert result.updates["latest_retrieved_chunks"] == [chunk()]
    assert result.updates["phase"] == "retrieved"
    assert context["question"] == "original question"


def test_retrieval_accumulates_unique_chunks_across_attempts(monkeypatch):
    first = chunk("first-round evidence")
    duplicate = {**first, "text": "same chunk returned again"}
    second = {
        **chunk("second-round evidence"),
        "section": "Scope",
        "chunk_id": "refund_policy.md::Scope::1",
    }

    monkeypatch.setattr(
        agent_tools,
        "hybrid_search",
        lambda question, top_k=None: [duplicate, second],
    )
    context = {
        "question": "original question",
        "search_query": "rewritten search query",
        "top_k": 5,
        "retrieval_attempts": 1,
        "retrieved_chunks": [first],
        "retrieved_sources": [agent_tools._source_view(first)],
    }

    result = agent_tools.retrieval_search_tool(context)

    assert result.updates["latest_retrieved_chunks"] == [duplicate, second]
    assert result.updates["retrieved_chunks"] == [first, second]
    assert result.updates["retrieved_sources"] == [
        agent_tools._source_view(first),
        agent_tools._source_view(second),
    ]
    assert "2 latest chunks" in result.output_summary
    assert "2 accumulated unique chunks" in result.output_summary


def test_evidence_assess_tool_appends_structured_history():
    class FakeAssessor:
        def assess(self, *, question, search_query, chunks):
            assert question == "original question"
            assert search_query == "refund deadline"
            assert chunks == [chunk()]
            return EvidenceAssessment(
                verdict="insufficient",
                reason="missing employee scope",
                rewritten_query="employee refund deadline",
                rewrite_source="fallback",
            )

    context = {
        "question": "original question",
        "search_query": "refund deadline",
        "retrieval_attempts": 1,
        "retrieved_chunks": [chunk()],
        "evidence_history": [],
    }

    result = agent_tools.make_evidence_assess_tool(FakeAssessor())(context)

    assert result.updates["phase"] == "assessed"
    assert result.updates["evidence_assessment"].verdict == "insufficient"
    history = result.updates["evidence_history"]
    assert len(history) == 1
    assert history[0].attempt == 1
    assert history[0].search_query == "refund deadline"
    assert history[0].rewritten_query == "employee refund deadline"
    assert history[0].rewrite_source == "fallback"


def test_evidence_assess_tool_balances_prior_and_latest_prompt_evidence():
    prior = [
        {
            **chunk(f"prior evidence {index}"),
            "chunk_id": f"prior::{index}",
        }
        for index in range(8)
    ]
    latest = [
        {
            **chunk(f"latest evidence {index}"),
            "chunk_id": f"latest::{index}",
        }
        for index in range(8)
    ]
    captured = {}

    class CapturingAssessor:
        def assess(self, *, question, search_query, chunks):
            captured["chunks"] = chunks
            return EvidenceAssessment(
                verdict="sufficient",
                reason="balanced evidence supports the answer",
            )

    context = {
        "question": "original question",
        "search_query": "rewritten query",
        "retrieval_attempts": 2,
        "latest_retrieved_chunks": latest,
        "retrieved_chunks": [*prior, *latest],
        "evidence_history": [],
    }

    agent_tools.make_evidence_assess_tool(CapturingAssessor())(context)

    assert [item["chunk_id"] for item in captured["chunks"]] == [
        "prior::0",
        "latest::0",
        "prior::1",
        "latest::1",
        "prior::2",
        "latest::2",
        "prior::3",
        "latest::3",
    ]


def test_evidence_assess_tool_converts_unexpected_assessor_exception():
    class FailingAssessor:
        def assess(self, **kwargs):
            raise RuntimeError("assessor crashed")

    context = {
        "question": "question",
        "search_query": "query",
        "retrieval_attempts": 1,
        "retrieved_chunks": [chunk()],
        "evidence_history": [],
    }

    result = agent_tools.make_evidence_assess_tool(FailingAssessor())(context)

    assessment = result.updates["evidence_assessment"]
    assert assessment.verdict == "error"
    assert assessment.reason == "evidence assessment failed: RuntimeError"
    assert result.updates["phase"] == "assessed"


def test_query_rewrite_applies_validated_candidate_without_changing_question():
    context = {
        "question": "original question",
        "search_query": "refund",
        "evidence_assessment": EvidenceAssessment(
            verdict="insufficient",
            reason="too broad",
            rewritten_query="employee refund deadline",
        ),
    }

    result = agent_tools.query_rewrite_tool(context)

    assert result.updates == {
        "search_query": "employee refund deadline",
        "phase": "rewritten",
    }
    assert context["question"] == "original question"


def test_query_rewrite_rejects_unchanged_candidate():
    context = {
        "question": "refund deadline",
        "search_query": "refund deadline",
        "evidence_assessment": EvidenceAssessment(
            verdict="insufficient",
            reason="missing evidence",
            rewritten_query="Refund Deadline",
        ),
    }

    with pytest.raises(ValueError, match="usable rewritten query"):
        agent_tools.query_rewrite_tool(context)


def test_rag_answer_uses_original_question_after_rewrite(monkeypatch):
    calls = []

    def fake_answer(question, chunks):
        calls.append((question, chunks))
        return {"answer": "Grounded answer [1]", "sources": chunks}

    monkeypatch.setattr(agent_tools, "answer_from_retrieved", fake_answer)
    result = agent_tools.rag_answer_tool(
        {
            "question": "original question",
            "search_query": "rewritten query",
            "retrieved_chunks": [chunk()],
        }
    )

    assert calls == [("original question", [chunk()])]
    assert result.updates["phase"] == "answered"
    assert result.updates["final_outcome"] == "answered"


def test_rag_no_answer_distinguishes_insufficient_from_assessment_error():
    insufficient = agent_tools.rag_no_answer_tool(
        {
            "evidence_assessment": EvidenceAssessment(
                verdict="insufficient",
                reason="missing evidence",
            )
        }
    )
    unavailable = agent_tools.rag_no_answer_tool(
        {
            "evidence_assessment": EvidenceAssessment(
                verdict="error",
                reason="evidence assessment failed: RuntimeError",
            )
        }
    )

    assert insufficient.updates["answer"] == agent_tools.DEFAULT_NO_ANSWER
    assert insufficient.updates["final_outcome"] == "grounded_no_answer"
    assert insufficient.updates["sources"] == []
    assert insufficient.updates["phase"] == "no_answer"
    assert unavailable.updates["answer"] == agent_tools.ASSESSMENT_UNAVAILABLE_ANSWER
    assert unavailable.updates["final_outcome"] == "error"


def test_guardrail_and_refusal_tools_set_terminal_state(monkeypatch):
    monkeypatch.setattr(agent_tools, "unsafe_answer", lambda answer: False)
    checked = agent_tools.guardrail_check_tool(
        {"answer": "safe", "final_outcome": "answered"}
    )
    refused = agent_tools.guardrail_refuse_tool({})

    assert checked.updates == {"guardrail_blocked": False, "phase": "guarded"}
    assert refused.updates["phase"] == "refused"
    assert refused.updates["final_outcome"] == "refused"
