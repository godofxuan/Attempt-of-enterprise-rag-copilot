from __future__ import annotations

from dataclasses import dataclass

import pytest
import requests

from app.runtime.model_transport import ModelRequestError, perform_model_request
from app.runtime.request_context import (
    bind_request_context,
    current_request_context,
    reset_request_context,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


@dataclass
class MutableClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def test_successful_request_uses_configured_timeout_without_api_context() -> None:
    timeouts: list[float] = []

    result = perform_model_request(
        lambda timeout: timeouts.append(timeout) or FakeResponse(200),
        operation="chat",
        timeout_seconds=12.0,
        max_attempts=2,
        backoff_seconds=0.1,
    )

    assert result.response.status_code == 200
    assert result.attempts == 1
    assert result.retries == 0
    assert timeouts == [12.0]


def test_retryable_503_retries_once_and_records_request_telemetry() -> None:
    responses = iter([FakeResponse(503), FakeResponse(200)])
    clock = MutableClock(0.0)
    token = bind_request_context(
        "req",
        deadline_ms=5_000,
        clock_ms=lambda: clock() * 1000.0,
    )
    try:
        result = perform_model_request(
            lambda timeout: next(responses),
            operation="chat",
            timeout_seconds=2.0,
            max_attempts=2,
            backoff_seconds=0,
            clock=clock,
        )
        context = current_request_context()
        assert context is not None
        assert context.model_calls == 2
        assert context.model_retries == 1
        assert context.model_errors == 0
        assert [span["status"] for span in context.spans] == ["error", "ok"]
    finally:
        reset_request_context(token)

    assert result.attempts == 2
    assert result.retries == 1


def test_timeout_is_retryable_but_stops_at_max_attempts() -> None:
    calls = 0

    def send(timeout: float):
        nonlocal calls
        calls += 1
        raise requests.Timeout("socket timed out at D:/secret/model.bin")

    with pytest.raises(ModelRequestError) as exc_info:
        perform_model_request(
            send,
            operation="embed",
            timeout_seconds=1.0,
            max_attempts=2,
            backoff_seconds=0,
        )

    assert calls == 2
    assert exc_info.value.code == "transport_timeout"
    assert exc_info.value.retryable is True
    assert exc_info.value.attempts == 2
    assert "secret" not in str(exc_info.value).casefold()
    assert "D:/" not in str(exc_info.value)


def test_non_retryable_400_is_attempted_once_and_response_body_is_not_exposed() -> None:
    calls = 0

    def send(timeout: float):
        nonlocal calls
        calls += 1
        return FakeResponse(400, "password=never-show D:/vault/model.bin")

    with pytest.raises(ModelRequestError) as exc_info:
        perform_model_request(
            send,
            operation="chat",
            timeout_seconds=1.0,
            max_attempts=3,
            backoff_seconds=0,
        )

    assert calls == 1
    assert exc_info.value.code == "http_400"
    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False
    assert "never-show" not in str(exc_info.value)
    assert "vault" not in str(exc_info.value)


def test_request_deadline_exhaustion_prevents_send() -> None:
    clock = MutableClock(0.2)
    calls = 0
    token = bind_request_context("req", deadline_ms=100, clock_ms=lambda: 0.0)
    try:
        def send(timeout: float):
            nonlocal calls
            calls += 1
            return FakeResponse(200)

        with pytest.raises(ModelRequestError) as exc_info:
            perform_model_request(
                send,
                operation="chat",
                timeout_seconds=12.0,
                max_attempts=2,
                backoff_seconds=0.1,
                clock=clock,
            )
    finally:
        reset_request_context(token)

    assert calls == 0
    assert exc_info.value.code == "deadline_exhausted"
    assert exc_info.value.attempts == 0
    assert exc_info.value.retryable is False


def test_retry_is_not_slept_when_backoff_exceeds_remaining_deadline() -> None:
    clock = MutableClock(0.0)
    sleeps: list[float] = []
    token = bind_request_context("req", deadline_ms=150, clock_ms=lambda: 0.0)
    try:
        def send(timeout: float):
            clock.value = 0.1
            return FakeResponse(503)

        with pytest.raises(ModelRequestError) as exc_info:
            perform_model_request(
                send,
                operation="embed",
                timeout_seconds=12.0,
                max_attempts=2,
                backoff_seconds=0.1,
                sleeper=sleeps.append,
                clock=clock,
            )
    finally:
        reset_request_context(token)

    assert sleeps == []
    assert exc_info.value.code == "deadline_exhausted"
    assert exc_info.value.attempts == 1


def test_invalid_operation_and_attempts_are_rejected_before_send() -> None:
    with pytest.raises(ValueError, match="operation"):
        perform_model_request(
            lambda timeout: FakeResponse(200),
            operation="question.secret",
            timeout_seconds=1.0,
            max_attempts=1,
            backoff_seconds=0,
        )
    with pytest.raises(ValueError, match="max_attempts"):
        perform_model_request(
            lambda timeout: FakeResponse(200),
            operation="chat",
            timeout_seconds=1.0,
            max_attempts=0,
            backoff_seconds=0,
        )
