from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.api_v2.helpers import make_container


def test_validation_error_is_generic_and_does_not_echo_invalid_input() -> None:
    secret = "PROJECT_NIGHTFALL_password=never-show"
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers={"X-Request-ID": "req-validation"},
        json={"question": secret},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "request_validation_failed",
            "message": "Request validation failed.",
            "request_id": "req-validation",
            "retryable": False,
        }
    }
    assert secret not in response.text


def test_unhandled_endpoint_error_is_generic_and_log_does_not_contain_secret(
    monkeypatch,
    caplog,
) -> None:
    secret = "D:/vault/secret.index password=never-show"

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr("app.main.run_agent_chat", fail)
    response = TestClient(create_app(make_container()), raise_server_exceptions=False).post(
        "/agent/chat",
        headers={"X-Request-ID": "req-error"},
        json={"question": "safe question", "top_k": 3},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "The service could not complete the request.",
            "request_id": "req-error",
            "retryable": False,
        }
    }
    assert "never-show" not in response.text
    assert "vault" not in response.text
    assert secret not in caplog.text
