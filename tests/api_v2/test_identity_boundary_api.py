from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.identity as identity_api
from app.api.identity import MAX_AUTHENTICATED_BODY_BYTES, TrustedIdentityMiddleware
from app.domain.evidence import AnswerResponse
from app.main import create_app
from app.security.identity import (
    UnavailableFeedbackActorHasher,
    UnavailableIdentityVerifier,
)
from tests.api_v2.helpers import OPERATOR_HEADERS, USER_HEADERS, make_container


def _protected_asgi_scope(authorization: str) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/agent/v2/chat",
        "raw_path": b"/agent/v2/chat",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", authorization.encode("ascii")),
        ],
        "client": ("127.0.0.1", 41000),
        "server": ("127.0.0.1", 8000),
    }


def _asgi_error(messages: list[dict]) -> tuple[int, dict]:
    start = next(item for item in messages if item["type"] == "http.response.start")
    body = b"".join(
        item.get("body", b"")
        for item in messages
        if item["type"] == "http.response.body"
    )
    return int(start["status"]), json.loads(body)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/agent/v2/chat", {"question": "Policy?"}),
        (
            "POST",
            "/feedback",
            {
                "target_request_id": "req-answer-1",
                "question": "Policy?",
                "answer": "Answer",
                "helpful": True,
            },
        ),
        ("GET", "/identity/me", None),
        ("GET", "/observability/metrics", None),
        ("GET", "/observability/traces/req-answer-1", None),
    ],
)
def test_protected_routes_require_bearer_token(
    method: str,
    path: str,
    body: dict | None,
) -> None:
    response = TestClient(create_app(make_container())).request(
        method,
        path,
        json=body,
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.json()["error"]["retryable"] is False


def test_health_and_api_documentation_remain_public() -> None:
    client = TestClient(create_app(make_container()))

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_openapi_documents_bearer_security_without_protecting_schema() -> None:
    schema = TestClient(create_app(make_container())).get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert schema["paths"]["/agent/v2/chat"]["post"]["security"] == [
        {"BearerAuth": []}
    ]
    assert schema["paths"]["/observability/metrics"]["get"]["security"] == [
        {"BearerAuth": []}
    ]
    assert "security" not in schema["paths"]["/health/live"]["get"]


@pytest.mark.parametrize(
    "path",
    ["/observability/metrics", "/observability/traces/missing"],
)
def test_valid_non_operator_token_is_forbidden_from_operator_routes(path: str) -> None:
    response = TestClient(create_app(make_container())).get(path, headers=USER_HEADERS)

    assert response.status_code == 403
    assert "www-authenticate" not in response.headers
    assert response.json()["error"]["code"] == "insufficient_role"


def test_operator_token_can_reach_operator_route() -> None:
    response = TestClient(create_app(make_container())).get(
        "/observability/metrics",
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200


def test_mounted_secure_app_preserves_authentication_and_operator_boundary() -> None:
    parent = FastAPI()
    parent.mount("/prefix", create_app(make_container()))

    with TestClient(parent) as client:
        missing = client.get("/prefix/observability/metrics")
        user = client.get(
            "/prefix/observability/metrics",
            headers=USER_HEADERS,
        )
        operator = client.get(
            "/prefix/observability/metrics",
            headers=OPERATOR_HEADERS,
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authentication_required"
    assert user.status_code == 403
    assert user.json()["error"]["code"] == "insufficient_role"
    assert operator.status_code == 200


def test_identity_me_is_the_explicit_identity_disclosure_endpoint() -> None:
    response = TestClient(create_app(make_container())).get(
        "/identity/me",
        headers=USER_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "subject": "employee-one",
        "tenant_id": "tenant-one",
        "region": "cn",
        "groups": ["employees"],
        "roles": [],
        "issuer": "https://identity.localhost/",
        "audience": "enterprise-rag-api",
        "key_id": "test-key-1",
    }


def test_invalid_token_precedes_body_validation_and_never_calls_agent(monkeypatch) -> None:
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("agent must not run")

    monkeypatch.setattr("app.main.run_agent_v2_chat", forbidden_run)
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers={"Authorization": "Bearer attacker-token"},
        json={"question": "", "user_context": {"roles": ["admin"]}},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert calls == 0


def test_invalid_token_precedes_authenticated_body_limit(monkeypatch) -> None:
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("agent must not run")

    monkeypatch.setattr("app.main.run_agent_v2_chat", forbidden_run)
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers={"Authorization": "Bearer attacker-token"},
        content=b"x" * (MAX_AUTHENTICATED_BODY_BYTES + 1),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert calls == 0


def test_authenticated_oversized_body_is_rejected_before_json_and_agent(
    monkeypatch,
) -> None:
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("agent must not run")

    monkeypatch.setattr("app.main.run_agent_v2_chat", forbidden_run)
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers=USER_HEADERS,
        content=b"x" * (MAX_AUTHENTICATED_BODY_BYTES + 1),
    )

    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "request_body_too_large",
        "message": "The authenticated request body is too large.",
        "request_id": response.json()["error"]["request_id"],
        "retryable": False,
    }
    assert calls == 0


def test_authenticated_chunked_body_is_bounded_without_content_length(
    monkeypatch,
) -> None:
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("agent must not run")

    def chunks():
        yield b"x" * (MAX_AUTHENTICATED_BODY_BYTES // 2)
        yield b"y" * (MAX_AUTHENTICATED_BODY_BYTES // 2 + 1)

    monkeypatch.setattr("app.main.run_agent_v2_chat", forbidden_run)
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers=USER_HEADERS,
        content=chunks(),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert calls == 0


@pytest.mark.parametrize(
    ("framing_headers", "expected_status", "expected_code", "expected_message"),
    [
        (
            [
                (b"content-length", b"1"),
                (b"content-length", b"1"),
            ],
            400,
            "invalid_content_length",
            "The request body framing is invalid.",
        ),
        (
            [
                (b"content-length", b"1"),
                (b"transfer-encoding", b"chunked"),
            ],
            400,
            "invalid_content_length",
            "The request body framing is invalid.",
        ),
        (
            [(b"content-length", b"not-a-number")],
            400,
            "invalid_content_length",
            "The request body framing is invalid.",
        ),
        (
            [(b"content-length", b"9" * 5_000)],
            413,
            "request_body_too_large",
            "The authenticated request body is too large.",
        ),
    ],
)
def test_authenticated_invalid_content_length_is_rejected_before_receive(
    framing_headers: list[tuple[bytes, bytes]],
    expected_status: int,
    expected_code: str,
    expected_message: str,
) -> None:
    receive_calls = 0
    downstream_calls = 0
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1

    async def receive() -> dict:
        nonlocal receive_calls
        receive_calls += 1
        raise AssertionError("invalid framing must be rejected before body receive")

    async def send(message: dict) -> None:
        sent.append(message)

    scope = _protected_asgi_scope(USER_HEADERS["Authorization"])
    scope["headers"].extend(framing_headers)
    middleware = TrustedIdentityMiddleware(downstream, container=make_container())
    asyncio.run(middleware(scope, receive, send))

    status, payload = _asgi_error(sent)
    assert status == expected_status
    assert payload["error"] == {
        "code": expected_code,
        "message": expected_message,
        "request_id": payload["error"]["request_id"],
        "retryable": False,
    }
    assert receive_calls == 0
    assert downstream_calls == 0


@pytest.mark.parametrize(
    "message",
    [
        ["not", "an", "asgi", "message"],
        {"type": "websocket.receive", "bytes": b"x"},
        {"type": "http.request", "body": "not-bytes"},
        {"type": "http.request", "body": b"", "more_body": 1},
    ],
)
def test_authenticated_invalid_asgi_body_message_is_rejected(
    message: object,
) -> None:
    receive_calls = 0
    downstream_calls = 0
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1

    async def receive():
        nonlocal receive_calls
        receive_calls += 1
        return message

    async def send(outbound: dict) -> None:
        sent.append(outbound)

    middleware = TrustedIdentityMiddleware(downstream, container=make_container())
    asyncio.run(
        middleware(
            _protected_asgi_scope(USER_HEADERS["Authorization"]),
            receive,
            send,
        )
    )

    status, payload = _asgi_error(sent)
    assert status == 400
    assert payload["error"] == {
        "code": "invalid_request_body",
        "message": "The authenticated request body framing is invalid.",
        "request_id": payload["error"]["request_id"],
        "retryable": False,
    }
    assert receive_calls == 1
    assert downstream_calls == 0


def test_authenticated_zero_byte_chunk_flood_is_bounded_by_message_count() -> None:
    receive_calls = 0
    downstream_calls = 0
    sent: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1

    async def receive() -> dict:
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls > identity_api.MAX_AUTHENTICATED_BODY_MESSAGES:
            raise AssertionError("middleware did not bound zero-byte ASGI chunks")
        return {"type": "http.request", "body": b"", "more_body": True}

    async def send(message: dict) -> None:
        sent.append(message)

    middleware = TrustedIdentityMiddleware(downstream, container=make_container())
    asyncio.run(
        middleware(
            _protected_asgi_scope(USER_HEADERS["Authorization"]),
            receive,
            send,
        )
    )

    status, payload = _asgi_error(sent)
    assert status == 413
    assert payload["error"]["code"] == "request_body_too_large"
    assert receive_calls == identity_api.MAX_AUTHENTICATED_BODY_MESSAGES
    assert downstream_calls == 0


def test_authenticated_body_receive_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream_calls = 0
    sent: list[dict] = []
    never_returns = asyncio.Event()

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1

    async def receive() -> dict:
        await never_returns.wait()
        raise AssertionError("unreachable")

    async def send(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr(
        identity_api,
        "AUTHENTICATED_BODY_RECEIVE_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    middleware = TrustedIdentityMiddleware(downstream, container=make_container())
    asyncio.run(
        asyncio.wait_for(
            middleware(
                _protected_asgi_scope(USER_HEADERS["Authorization"]),
                receive,
                send,
            ),
            timeout=0.2,
        )
    )

    status, payload = _asgi_error(sent)
    assert status == 408
    assert payload["error"] == {
        "code": "request_body_timeout",
        "message": "The authenticated request body was not received in time.",
        "request_id": payload["error"]["request_id"],
        "retryable": False,
    }
    assert downstream_calls == 0


def test_valid_token_cannot_override_server_owned_identity(monkeypatch) -> None:
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("agent must not run")

    monkeypatch.setattr("app.main.run_agent_v2_chat", forbidden_run)
    response = TestClient(create_app(make_container())).post(
        "/agent/v2/chat",
        headers=USER_HEADERS,
        json={
            "question": "Policy?",
            "user_context": {
                "user_id": "admin",
                "tenant_id": "other-tenant",
                "region": "global",
                "groups": ["executives"],
                "roles": ["rag.operator"],
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"
    assert calls == 0


def test_verified_principal_is_the_only_agent_user_context(monkeypatch) -> None:
    observed = {}

    def fake_run(question, user, top_k=None):
        observed.update(question=question, user=user, top_k=top_k)
        return AnswerResponse(
            mode="not_found",
            answer="No visible evidence.",
            stop_reason="not_found",
            trace={"intent": "fact", "steps": [], "budget": {}},
        )

    monkeypatch.setattr("app.main.run_agent_v2_chat", fake_run)
    container = make_container()
    response = TestClient(create_app(container)).post(
        "/agent/v2/chat",
        headers={**USER_HEADERS, "X-Request-ID": "req-answer-receipt"},
        json={"question": "Policy?", "top_k": 3},
    )

    assert response.status_code == 200
    assert observed["user"].model_dump(mode="json") == {
        "user_id": "employee-one",
        "tenant_id": "tenant-one",
        "region": "cn",
        "groups": ["employees"],
        "roles": [],
    }
    receipt = response.headers["x-feedback-receipt"]
    principal = container.identity_verifier.verify_bearer(
        USER_HEADERS["Authorization"]
    )
    assert container.feedback_actor_hasher.verify_feedback_receipt(
        principal,
        target_request_id="req-answer-receipt",
        question="Policy?",
        answer="No visible evidence.",
        receipt=receipt,
    )


def test_unavailable_identity_boundary_is_retryable_service_failure() -> None:
    container = make_container(identity_verifier=UnavailableIdentityVerifier())
    response = TestClient(create_app(container)).post(
        "/agent/v2/chat",
        headers=USER_HEADERS,
        json={"question": "Policy?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert "JWKS" not in response.text


def test_duplicate_authorization_headers_fail_closed() -> None:
    response = TestClient(create_app(make_container())).get(
        "/identity/me",
        headers=[
            ("Authorization", "Bearer user-token"),
            ("Authorization", "Bearer operator-token"),
        ],
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_authentication_failure_records_only_low_sensitivity_request_metadata() -> None:
    container = make_container()
    response = TestClient(create_app(container)).post(
        "/agent/v2/chat",
        headers={
            "Authorization": "Bearer attacker-token",
            "X-Request-ID": "req-auth-failure",
        },
        json={"question": "PROJECT NIGHTFALL secret"},
    )

    trace = container.traces.get("req-auth-failure")
    assert response.status_code == 401
    assert trace is not None
    assert trace.route == "/agent/v2/chat"
    assert trace.status_code == 401
    assert trace.model_calls == 0
    assert trace.model_retries == 0
    assert trace.model_errors == 0
    assert trace.spans == []
    assert "NIGHTFALL" not in trace.model_dump_json()


def test_feedback_binds_target_request_and_hmac_actor(monkeypatch) -> None:
    observed = {}

    def fake_save_feedback_metadata(**kwargs):
        observed.update(kwargs)

    monkeypatch.setattr("app.main.save_feedback_metadata", fake_save_feedback_metadata)
    container = make_container()
    principal = container.identity_verifier.verify_bearer(
        USER_HEADERS["Authorization"]
    )
    receipt = container.feedback_actor_hasher.issue_feedback_receipt(
        principal,
        target_request_id="req-answer-target",
        question="Policy?",
        answer="Answer",
    )
    response = TestClient(create_app(container)).post(
        "/feedback",
        headers={**USER_HEADERS, "X-Request-ID": "req-feedback-submit"},
        json={
            "target_request_id": "req-answer-target",
            "question": "Policy?",
            "answer": "Answer",
            "helpful": True,
            "receipt": receipt,
        },
    )

    assert response.status_code == 200
    assert observed["request_id"] == "req-feedback-submit"
    assert observed["target_request_id"] == "req-answer-target"
    assert len(observed["actor_pseudonym"]) == 64
    assert "employee-one" not in observed["actor_pseudonym"]
    assert "question" not in observed
    assert "answer" not in observed
    assert len(observed["question_hmac_sha256"]) == 64
    assert len(observed["answer_hmac_sha256"]) == 64
    assert observed["settings"] is container.settings


def test_feedback_rejects_tampered_binding_before_database_write(monkeypatch) -> None:
    writes = 0

    def forbidden_write(**kwargs):
        nonlocal writes
        writes += 1

    monkeypatch.setattr("app.main.save_feedback_metadata", forbidden_write)
    container = make_container()
    principal = container.identity_verifier.verify_bearer(
        USER_HEADERS["Authorization"]
    )
    receipt = container.feedback_actor_hasher.issue_feedback_receipt(
        principal,
        target_request_id="req-answer-target",
        question="Policy?",
        answer="Original answer",
    )

    response = TestClient(create_app(container)).post(
        "/feedback",
        headers=USER_HEADERS,
        json={
            "target_request_id": "req-answer-target",
            "question": "Policy?",
            "answer": "Tampered answer",
            "helpful": True,
            "receipt": receipt,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_feedback_binding"
    assert writes == 0


def test_feedback_fails_closed_when_actor_hmac_is_unavailable(monkeypatch) -> None:
    writes = 0

    def forbidden_write(**kwargs):
        nonlocal writes
        writes += 1

    monkeypatch.setattr("app.main.save_feedback_metadata", forbidden_write)
    container = replace(
        make_container(),
        feedback_actor_hasher=UnavailableFeedbackActorHasher(),
    )
    response = TestClient(create_app(container)).post(
        "/feedback",
        headers=USER_HEADERS,
        json={
            "target_request_id": "req-answer-target",
            "question": "Policy?",
            "answer": "Answer",
            "helpful": True,
            "receipt": "a" * 64,
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_unavailable"
    assert response.json()["error"]["retryable"] is True
    assert writes == 0
