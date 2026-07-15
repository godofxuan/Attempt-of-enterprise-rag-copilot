from fastapi.testclient import TestClient

from app.agent.schemas import AgentChatResponse, AgentTrace
from app.main import app


def test_agent_chat_endpoint_returns_answer_sources_and_trace(monkeypatch):
    source = {
        "source": "policy.md",
        "section": "Section",
        "chunk_id": "policy.md::Section::0",
        "preview": "policy snippet",
    }

    def fake_run_agent_chat(question, top_k=None):
        assert question == "test question"
        assert top_k == 3
        return AgentChatResponse(
            answer="grounded answer",
            sources=[source],
            trace=AgentTrace(route="policy_qa", route_reason="default", plan=[], steps=[]),
        )

    monkeypatch.setattr("app.main.run_agent_chat", fake_run_agent_chat)

    client = TestClient(app)
    response = client.post("/agent/chat", json={"question": "test question", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "grounded answer"
    assert body["sources"] == [source]
    assert body["trace"]["route"] == "policy_qa"
