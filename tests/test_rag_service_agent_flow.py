from types import SimpleNamespace

import app.rag_service as rag_service


def chunk(text: str = "Policy says refund requests after 14 days are rejected.") -> dict:
    return {
        "source": "refund_policy.md",
        "section": "Refund",
        "chunk_id": "refund_policy.md::Refund::0",
        "text": text,
    }


def test_answer_from_retrieved_uses_supplied_chunks_without_search(monkeypatch):
    def fail_search(**kwargs):
        raise AssertionError("answer_from_retrieved must not call hybrid_search")

    captured = {}

    def fake_chat(model, messages):
        captured["model"] = model
        captured["messages"] = messages
        return "Grounded answer [1]"

    monkeypatch.setattr(rag_service, "hybrid_search", fail_search)
    monkeypatch.setattr(rag_service, "_chat_with_ollama", fake_chat)
    monkeypatch.setattr(
        rag_service,
        "get_settings",
        lambda: SimpleNamespace(chat_model="test-chat-model"),
    )

    result = rag_service.answer_from_retrieved("Can I refund after 14 days?", [chunk()])

    assert result["answer"] == "Grounded answer [1]"
    assert result["sources"] == [
        {
            "source": "refund_policy.md",
            "section": "Refund",
            "chunk_id": "refund_policy.md::Refund::0",
            "preview": "Policy says refund requests after 14 days are rejected.",
        }
    ]
    assert captured["model"] == "test-chat-model"
    assert "Policy says refund requests after 14 days are rejected." in captured["messages"][1]["content"]


def test_answer_question_searches_once_then_delegates_to_answer_from_retrieved(monkeypatch):
    retrieved = [chunk()]
    calls = []

    def fake_search(question, top_k=None):
        calls.append(("search", question, top_k))
        return retrieved

    def fake_answer_from_retrieved(question, chunks):
        calls.append(("answer", question, chunks))
        return {"answer": "delegated answer", "sources": []}

    monkeypatch.setattr(rag_service, "hybrid_search", fake_search)
    monkeypatch.setattr(rag_service, "answer_from_retrieved", fake_answer_from_retrieved)

    result = rag_service.answer_question("Can I refund after 14 days?", top_k=5)

    assert result == {"answer": "delegated answer", "sources": []}
    assert calls == [
        ("search", "Can I refund after 14 days?", 5),
        ("answer", "Can I refund after 14 days?", retrieved),
    ]
