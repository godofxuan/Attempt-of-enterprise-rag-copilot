from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.domain.evidence import AnswerResponse
from app.main import create_app
from app.runtime.request_context import current_request_context
from tests.api_v2.helpers import USER_HEADERS, make_container


VALID_USER = {
    "user_id": "employee-one",
    "tenant_id": "tenant-one",
    "region": "cn",
    "groups": ["employees"],
    "roles": [],
}


def test_request_id_header_matches_v2_trace_and_context_is_reset(monkeypatch) -> None:
    def fake_run(question, user, top_k=None):
        return AnswerResponse(
            mode="not_found",
            answer="No visible evidence.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        )

    monkeypatch.setattr("app.main.run_agent_v2_chat", fake_run)
    app = create_app(make_container())
    response = TestClient(app).post(
        "/agent/v2/chat",
        headers={**USER_HEADERS, "X-Request-ID": "client.req-123"},
        json={"question": "What is the policy?"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client.req-123"
    assert response.json()["trace"]["request_id"] == "client.req-123"
    assert current_request_context() is None


def test_invalid_attacker_controlled_request_id_is_replaced(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.main.run_agent_v2_chat",
        lambda question, user, top_k=None: AnswerResponse(
            mode="not_found",
            answer="No visible evidence.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        ),
    )
    secret_id = "password=never-show/../../vault"
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers={**USER_HEADERS, "X-Request-ID": secret_id},
        json={"question": "What is the policy?"},
    )

    request_id = response.headers["x-request-id"]
    assert request_id != secret_id
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert response.json()["trace"]["request_id"] == request_id
    assert "never-show" not in response.text
