from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import requests

from app.domain.queries import UserContext
from streamlit_app.api_client import EnterpriseRagClient, UiApiError


USER = UserContext(
    user_id="demo-user",
    tenant_id="starbridge-cn",
    region="cn",
    groups=["all_employees"],
    roles=[],
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any,
        *,
        request_id: str = "req-ui",
        raw_text: str = "",
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = {"X-Request-ID": request_id}
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
) -> EnterpriseRagClient:
    return EnterpriseRagClient(
        "http://127.0.0.1:8000/",
        session=session,
        timeout_seconds=7.5,
        request_id_factory=request_id_factory,
    )


def test_ask_sends_exact_v2_payload_timeout_and_request_id() -> None:
    session = FakeSession([FakeResponse(200, _response_payload())])
    client = _client(session)

    result = client.ask("How much notice is required?", USER, top_k=5)

    assert session.trust_env is False
    assert session.calls == [
        {
            "method": "POST",
            "url": "http://127.0.0.1:8000/agent/v2/chat",
            "json": {
                "question": "How much notice is required?",
                "user_context": USER.model_dump(mode="json"),
                "top_k": 5,
            },
            "headers": {"X-Request-ID": "req-ui"},
            "timeout": 7.5,
        }
    ]
    assert result.request_id == "req-ui"
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
        [FakeResponse(200, payload, request_id=header_id)]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(session, request_id_factory=lambda: header_id).ask(
            "How much notice is required?",
            USER,
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
            )
        ]
    )

    with pytest.raises(UiApiError) as exc_info:
        _client(session, request_id_factory=lambda: "req-sent").ask(
            "How much notice is required?",
            USER,
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
        _client(invalid).ask("Question", USER, top_k=5)
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
        "checks": {"database": "ok", "index": "ok", "models": "error"},
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
        question="How much notice is required?",
        answer="Two working days.",
        helpful=True,
    )

    assert result.status == "ok"
    assert session.calls == [
        {
            "method": "POST",
            "url": "http://127.0.0.1:8000/feedback",
            "json": {
                "question": "How much notice is required?",
                "answer": "Two working days.",
                "helpful": True,
            },
            "headers": {"X-Request-ID": "req-feedback"},
            "timeout": 7.5,
        }
    ]
