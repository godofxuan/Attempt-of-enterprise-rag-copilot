from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.evidence import AnswerResponse
from app.domain.queries import UserContext
from app.main import app


VALID_USER = {
    "user_id": "employee-one",
    "tenant_id": "tenant-one",
    "region": "cn",
    "groups": ["employees"],
    "roles": [],
}


def test_v2_endpoint_requires_explicit_user_context(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid request must not call runner")

    monkeypatch.setattr("app.main.run_agent_v2_chat", fail_if_called)
    response = TestClient(app).post(
        "/agent/v2/chat",
        json={"question": "What is the policy?"},
    )

    assert response.status_code == 422


def test_v2_endpoint_passes_exact_typed_identity_and_top_k(monkeypatch) -> None:
    captured = {}

    def fake_run(question, user, top_k=None):
        captured.update(question=question, user=user, top_k=top_k)
        return AnswerResponse(
            mode="not_found",
            answer="No visible evidence.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": []},
        )

    monkeypatch.setattr("app.main.run_agent_v2_chat", fake_run)
    response = TestClient(app).post(
        "/agent/v2/chat",
        json={
            "question": "What is the policy?",
            "top_k": 3,
            "user_context": VALID_USER,
        },
    )

    assert response.status_code == 200
    assert captured["question"] == "What is the policy?"
    assert captured["top_k"] == 3
    assert isinstance(captured["user"], UserContext)
    assert captured["user"].model_dump() == VALID_USER
    assert response.json()["mode"] == "not_found"


def test_v2_endpoint_validates_identity_and_top_k_before_runner(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid request must not call runner")

    monkeypatch.setattr("app.main.run_agent_v2_chat", fail_if_called)
    client = TestClient(app)

    empty_groups = client.post(
        "/agent/v2/chat",
        json={
            "question": "What is the policy?",
            "user_context": {**VALID_USER, "groups": []},
        },
    )
    invalid_top_k = client.post(
        "/agent/v2/chat",
        json={
            "question": "What is the policy?",
            "top_k": 0,
            "user_context": VALID_USER,
        },
    )

    assert empty_groups.status_code == 422
    assert invalid_top_k.status_code == 422
