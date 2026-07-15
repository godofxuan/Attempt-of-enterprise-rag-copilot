import pytest

import app.agent.tools as agent_tools


def chunk(text: str = "Policy says refund requests after 14 days are rejected.") -> dict:
    return {
        "source": "refund_policy.md",
        "section": "Refund",
        "chunk_id": "refund_policy.md::Refund::0",
        "text": text,
    }


def test_rag_answer_tool_requires_retrieved_chunks():
    with pytest.raises(KeyError, match="retrieved_chunks"):
        agent_tools.rag_answer_tool({"question": "Can I refund after 14 days?", "top_k": 5})


def test_rag_answer_tool_uses_retrieved_chunks_without_researching(monkeypatch):
    retrieved = [chunk()]
    calls = []

    def fake_answer_from_retrieved(question, chunks):
        calls.append((question, chunks))
        return {
            "answer": "Grounded answer [1]",
            "sources": [
                {
                    "source": "refund_policy.md",
                    "section": "Refund",
                    "chunk_id": "refund_policy.md::Refund::0",
                    "preview": "Policy says refund requests after 14 days are rejected.",
                }
            ],
        }

    monkeypatch.setattr(agent_tools, "answer_from_retrieved", fake_answer_from_retrieved)

    result = agent_tools.rag_answer_tool(
        {
            "question": "Can I refund after 14 days?",
            "top_k": 5,
            "retrieved_chunks": retrieved,
        }
    )

    assert result.updates["answer"] == "Grounded answer [1]"
    assert result.updates["sources"][0]["source"] == "refund_policy.md"
    assert result.output_summary == "generated answer with 1 sources"
    assert calls == [("Can I refund after 14 days?", retrieved)]
