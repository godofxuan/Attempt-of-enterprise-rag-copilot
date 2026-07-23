from __future__ import annotations

from collections.abc import Callable
from email.message import Message
from typing import Any

import pytest
import requests

from app.security.identity import IdentityConfigurationError
from streamlit_app.api_client import EnterpriseRagClient, UiApiError


USER_TOKEN = "dXNlcg.cGF5bG9hZA.c2lnbmF0dXJl"
OPERATOR_TOKEN = "b3BlcmF0b3I.cGF5bG9hZA.c2lnbmF0dXJl"
FEEDBACK_RECEIPT = "a" * 64


class PersonaTokens:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_token(self, persona_id: str) -> str:
        self.calls.append(persona_id)
        return USER_TOKEN


class OperatorToken:
    def __init__(self) -> None:
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return OPERATOR_TOKEN


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any,
        *,
        request_id: str = "req-ui",
        raw_text: str = "",
        feedback_receipt: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = {"X-Request-ID": request_id}
        if feedback_receipt is not None:
            self.headers["X-Feedback-Receipt"] = feedback_receipt
        self.text = raw_text

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.trust_env = True

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CookieTrackingSession:
    def __init__(self) -> None:
        self.cookies = requests.cookies.RequestsCookieJar()
        self.trust_env = True
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        prepared = requests.Request(
            method,
            url,
            headers=kwargs.get("headers"),
        ).prepare()
        outgoing_cookie = requests.cookies.get_cookie_header(self.cookies, prepared)
        self.calls.append(
            {
                "method": method,
                "url": url,
                "outgoing_cookie": outgoing_cookie,
            }
        )

        request_id = kwargs["headers"]["X-Request-ID"]
        path = url.removeprefix("http://127.0.0.1:8000")
        if path == "/health/ready":
            payload = {
                "status": "ready",
                "checks": {
                    "database": "ok",
                    "index": "ok",
                    "models": "ok",
                    "identity": "ok",
                },
                "retrieved_guard": "ready",
                "index": None,
                "checked_at_utc": "2026-07-22T00:00:00Z",
            }
        elif path == "/agent/v2/chat":
            payload = _response_payload(request_id)
        elif path == "/observability/traces/req-agent":
            payload = {
                "request_id": "req-agent",
                "method": "POST",
                "route": "/agent/v2/chat",
                "status_code": 200,
                "duration_ms": 1.0,
                "outcome": "answered",
                "model_calls": 1,
                "model_retries": 0,
                "model_errors": 0,
                "spans": [],
            }
        else:
            raise AssertionError(f"unexpected request path: {path}")

        response_headers = Message()
        response_headers.add_header(
            "Set-Cookie",
            "server_cookie=credential; Path=/; HttpOnly",
        )
        self.cookies.extract_cookies(
            requests.cookies.MockResponse(response_headers),
            requests.cookies.MockRequest(prepared),
        )
        return FakeResponse(
            200,
            payload,
            request_id=request_id,
            feedback_receipt=(
                FEEDBACK_RECEIPT
                if path == "/agent/v2/chat"
                else None
            ),
        )


def _response_payload(request_id: str = "req-ui") -> dict[str, Any]:
    return {
        "mode": "answered",
        "answer": "Remote work requests require two working days notice.",
        "claims": [
            {
                "claim_id": "claim-1",
                "text": "Two working days notice is required.",
                "critical": True,
                "cited_chunk_ids": ["chunk-1"],
            }
        ],
        "citations": [
            {
                "claim_id": "claim-1",
                "cited_chunk_ids": ["chunk-1"],
                "citation_present": True,
                "references_visible_evidence": True,
                "lexical_support": 1.0,
                "supported": True,
                "unsupported_reason": None,
            }
        ],
        "sources": [
            {
                "doc_id": "policy-1",
                "source_path": "policies/remote.md",
                "section_path": ["Notice"],
                "chunk_id": "chunk-1",
                "preview": "Two working days notice is required.",
            }
        ],
        "warnings": [],
        "stop_reason": "completed",
        "trace": {"request_id": request_id, "steps": []},
    }


def _client(
    session: FakeSession,
    *,
    request_id_factory: Callable[[], str] = lambda: "req-ui",
    persona_tokens: Any | None = None,
    operator_token: Any | None = None,
) -> EnterpriseRagClient:
    return EnterpriseRagClient(
        "http://127.0.0.1:8000/",
        session=session,
        timeout_seconds=7.5,
        request_id_factory=request_id_factory,
        persona_tokens=persona_tokens or PersonaTokens(),
        operator_token=operator_token or OperatorToken(),
    )


def test_default_sessions_isolate_identity_channels_and_reject_response_cookies(
    monkeypatch,
) -> None:
    sessions: list[CookieTrackingSession] = []

    def session_factory() -> CookieTrackingSession:
        session = CookieTrackingSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        "streamlit_app.api_client.requests.Session",
        session_factory,
    )
    ids = iter(["req-ready", "req-ask-1", "req-lookup", "req-ask-2"])
    client = EnterpriseRagClient(
        "http://127.0.0.1:8000",
        timeout_seconds=7.5,
        request_id_factory=lambda: next(ids),
        persona_tokens=PersonaTokens(),
        operator_token=OperatorToken(),
    )

    client.readiness()
    client.ask("Question one", persona_id="demo-user", top_k=5)
    client.trace("req-agent")
    client.ask("Question two", persona_id="demo-user", top_k=5)

    assert len(sessions) == 3
    assert sorted(len(session.calls) for session in sessions) == [1, 1, 2]
    assert all(session.trust_env is False for session in sessions)
    assert all(
        call["outgoing_cookie"] is None
        for session in sessions
        for call in session.calls
    )
    assert all(not session.cookies for session in sessions)


def test_ask_sends_exact_v2_payload_timeout_and_request_id() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                _response_payload(),
                feedback_receipt=FEEDBACK_RECEIPT,
            )
        ]
    )
    client = _client(session)

    result = client.ask(
        "How much notice is required?",
        persona_id="demo-user",
        top_k=5,
    )

    assert session.trust_env is False
    assert session.calls == [
        {
            "method": "POST",
            "url": "http://127.0.0.1:8000/agent/v2/chat",
            "json": {
                "question": "How much notice is required?",
                "top_k": 5,
            },
            "headers": {
                "X-Request-ID": "req-ui",
                "Authorization": f"Bearer {USER_TOKEN}",
            },
            "timeout": 7.5,
            "allow_redirects": False,
        }
    ]
    assert result.request_id == "req-ui"
    assert result.feedback_receipt == FEEDBACK_RECEIPT
    assert result.response.mode == "answered"


@pytest.mark.parametrize(
    ("header_id", "body_id"),
    [("req-header", "req-body"), ("req-header", None)],
)
def test_ask_requires_header_and_body_request_id_equality(
    header_id: str,
    body_id: str | None,
) -> None:
    payload = _response_payload(body_id or "req-placeholder")
    if body_id is None:
        payload["trace"].pop("request_id")
    session = FakeSession(
        [
            FakeResponse(
                200,
                payload,
                request_id=header_id,
                feedback_receipt=FEEDBACK_RECEIPT,
            )
        ]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(session, request_id_factory=lambda: header_id).ask(
            "How much notice is required?",
            persona_id="demo-user",
            top_k=5,
        )

    assert exc_info.value.code == "invalid_service_response"
    assert str(exc_info.value) == "The service returned an invalid response."
    assert "req-body" not in str(exc_info.value)


def test_ask_rejects_header_and_body_for_a_different_sent_request() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                _response_payload("req-other"),
                request_id="req-other",
                feedback_receipt=FEEDBACK_RECEIPT,
            )
        ]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(session, request_id_factory=lambda: "req-sent").ask(
            "How much notice is required?",
            persona_id="demo-user",
            top_k=5,
        )

    assert exc_info.value.code == "invalid_service_response"
    assert exc_info.value.request_id == "req-sent"


def test_invalid_success_payload_and_network_error_are_safely_wrapped() -> None:
    invalid = FakeSession(
        [
            FakeResponse(
                200,
                {"answer": "secret from D:\\private\\model.bin"},
                raw_text="token=never-expose",
            )
        ]
    )
    with pytest.raises(UiApiError) as invalid_error:
        _client(invalid).ask("Question", persona_id="demo-user", top_k=5)
    assert invalid_error.value.code == "invalid_service_response"
    assert "secret" not in str(invalid_error.value)
    assert "token" not in str(invalid_error.value)

    unavailable = FakeSession(
        [requests.ConnectionError("failed at D:\\private\\ollama")]
    )
    with pytest.raises(UiApiError) as network_error:
        _client(unavailable).readiness()
    assert network_error.value.code == "service_unavailable"
    assert network_error.value.retryable is True
    assert str(network_error.value) == "The service is unavailable."
    assert "ollama" not in str(network_error.value)


@pytest.mark.parametrize("receipt", [None, "A" * 64, "a" * 63, "not-a-receipt"])
def test_ask_rejects_missing_or_malformed_feedback_receipt(
    receipt: str | None,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                _response_payload(),
                feedback_receipt=receipt,
            )
        ]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(session).ask(
            "How much notice is required?",
            persona_id="demo-user",
            top_k=5,
        )

    assert exc_info.value.code == "invalid_service_response"
    assert receipt is None or receipt not in str(exc_info.value)


def test_trace_404_uses_typed_safe_api_error_without_raw_body() -> None:
    session = FakeSession(
        [
            FakeResponse(
                404,
                {
                    "error": {
                        "code": "trace_not_found",
                        "message": "The requested trace was not found.",
                        "request_id": "req-lookup",
                        "retryable": False,
                    }
                },
                request_id="req-lookup",
                raw_text="internal path D:\\secret",
            )
        ]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(session, request_id_factory=lambda: "req-lookup").trace(
            "missing-id"
        )

    error = exc_info.value
    assert error.code == "trace_not_found"
    assert error.request_id == "req-lookup"
    assert error.retryable is False
    assert str(error) == "The requested trace was not found."
    assert "D:\\secret" not in str(error)


def test_readiness_accepts_structured_503_and_trace_validates_model() -> None:
    readiness = {
        "status": "not_ready",
        "checks": {
            "database": "ok",
            "index": "ok",
            "models": "error",
            "identity": "ok",
        },
        "retrieved_guard": "ready",
        "index": None,
        "checked_at_utc": "2026-07-17T08:00:00Z",
    }
    trace = {
        "request_id": "req-agent",
        "method": "POST",
        "route": "/agent/v2/chat",
        "status_code": 200,
        "duration_ms": 1200.0,
        "outcome": "answered",
        "model_calls": 2,
        "model_retries": 0,
        "model_errors": 0,
        "spans": [
            {"name": "agent.run", "status": "ok", "duration_ms": 1190.0}
        ],
    }
    session = FakeSession(
        [
            FakeResponse(503, readiness, request_id="req-ready"),
            FakeResponse(200, trace, request_id="req-trace"),
        ]
    )
    ids = iter(["req-ready", "req-trace"])
    client = _client(session, request_id_factory=lambda: next(ids))

    assert client.readiness().status == "not_ready"
    assert client.trace("req-agent").model_calls == 2


def test_trace_rejects_a_valid_trace_for_another_target_request() -> None:
    trace = {
        "request_id": "req-other",
        "method": "POST",
        "route": "/agent/v2/chat",
        "status_code": 200,
        "duration_ms": 1200.0,
        "outcome": "answered",
        "model_calls": 2,
        "model_retries": 0,
        "model_errors": 0,
        "spans": [],
    }
    session = FakeSession(
        [FakeResponse(200, trace, request_id="req-lookup")]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(
            session,
            request_id_factory=lambda: "req-lookup",
        ).trace("req-agent")

    assert exc_info.value.code == "invalid_service_response"
    assert exc_info.value.request_id == "req-lookup"


def test_feedback_posts_exact_privacy_bounded_payload() -> None:
    session = FakeSession(
        [FakeResponse(200, {"status": "ok"}, request_id="req-feedback")]
    )
    client = _client(
        session,
        request_id_factory=lambda: "req-feedback",
    )

    result = client.feedback(
        persona_id="demo-user",
        target_request_id="req-answer",
        question="How much notice is required?",
        answer="Two working days.",
        helpful=True,
        receipt=FEEDBACK_RECEIPT,
    )

    assert result.status == "ok"
    assert session.calls == [
        {
            "method": "POST",
            "url": "http://127.0.0.1:8000/feedback",
            "json": {
                "target_request_id": "req-answer",
                "question": "How much notice is required?",
                "answer": "Two working days.",
                "helpful": True,
                "receipt": FEEDBACK_RECEIPT,
            },
            "headers": {
                "X-Request-ID": "req-feedback",
                "Authorization": f"Bearer {USER_TOKEN}",
            },
            "timeout": 7.5,
            "allow_redirects": False,
        }
    ]


def test_feedback_rejects_invalid_receipt_before_network_or_token_lookup() -> None:
    persona_tokens = PersonaTokens()
    session = FakeSession([])
    client = _client(session, persona_tokens=persona_tokens)

    with pytest.raises(UiApiError) as exc_info:
        client.feedback(
            persona_id="demo-user",
            target_request_id="req-answer",
            question="Question",
            answer="Answer",
            helpful=True,
            receipt="invalid",
        )

    assert exc_info.value.code == "invalid_service_response"
    assert session.calls == []
    assert persona_tokens.calls == []


def test_trace_uses_operator_token_and_tokens_are_resolved_per_call() -> None:
    trace = {
        "request_id": "req-agent",
        "method": "POST",
        "route": "/agent/v2/chat",
        "status_code": 200,
        "duration_ms": 1.0,
        "outcome": "answered",
        "model_calls": 1,
        "model_retries": 0,
        "model_errors": 0,
        "spans": [],
    }
    session = FakeSession(
        [
            FakeResponse(200, trace, request_id="lookup-1"),
            FakeResponse(200, trace, request_id="lookup-2"),
        ]
    )
    operator = OperatorToken()
    ids = iter(["lookup-1", "lookup-2"])
    client = _client(
        session,
        request_id_factory=lambda: next(ids),
        operator_token=operator,
    )

    client.trace("req-agent")
    client.trace("req-agent")

    assert operator.calls == 2
    assert all(
        call["headers"]["Authorization"] == f"Bearer {OPERATOR_TOKEN}"
        for call in session.calls
    )
    assert all(call["allow_redirects"] is False for call in session.calls)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8000",
        "http://[::1]:8000",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/api",
        "http://127.0.0.1:8000?next=evil",
        "http://127.0.0.1:8000#fragment",
        "https://127.0.0.1:8000",
        "http://127.0.0.2:8000",
        " http://127.0.0.1:8000",
    ],
)
def test_client_rejects_noncanonical_or_non_loopback_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError, match="base URL"):
        EnterpriseRagClient(
            base_url,
            session=FakeSession([]),
            persona_tokens=PersonaTokens(),
            operator_token=OperatorToken(),
        )


def test_token_source_failure_is_safe_and_never_reaches_error_or_repr() -> None:
    fixture_token = "dXNlcg.c2VjcmV0.c2lnbmF0dXJl"

    class BrokenTokens:
        def get_token(self, persona_id: str) -> str:
            raise IdentityConfigurationError(
                f"token unavailable: {fixture_token}"
            )

    client = _client(FakeSession([]), persona_tokens=BrokenTokens())

    with pytest.raises(UiApiError) as exc_info:
        client.ask("Question", persona_id="demo-user", top_k=5)

    assert exc_info.value.code == "identity_unavailable"
    assert fixture_token not in str(exc_info.value)
    assert fixture_token not in repr(exc_info.value)
    assert fixture_token not in repr(client)
