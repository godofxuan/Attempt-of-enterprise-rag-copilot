import json
from types import SimpleNamespace

import pytest
import requests

from app.agent.generation_v2 import _bounded_default_chat
from app.runtime import serving_chat
from app.runtime.model_transport import ModelRequestError
from app.runtime.request_context import (
    bind_request_context,
    current_request_context,
    reset_request_context,
)


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": "ok"}}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(
        serving_chat,
        "get_settings",
        lambda: SimpleNamespace(
            llm_base_url="http://127.0.0.1:11434/v1",
            model_request_timeout_seconds=30,
            model_max_attempts=2,
            model_retry_backoff_ms=0,
        ),
    )


@pytest.mark.parametrize("seed", [None, 42])
def test_serving_serializes_fixed_options_and_uses_request_budget(monkeypatch, seed):
    captured = []

    def post(url, payload, timeout):
        captured.append((url, json.loads(json.dumps(payload)), timeout))
        return FakeResponse()

    monkeypatch.setattr(serving_chat, "_post_ollama", post)
    token = bind_request_context("fixture", deadline_ms=500)
    try:
        if seed is None:
            result = _bounded_default_chat("fixture", [], response_format="json", think=False)
        else:
            result = serving_chat.serving_chat(
                "fixture", [], response_format="json", think=False, seed=seed
            )
        context = current_request_context()
        assert context.model_calls == 1
        assert context.model_retries == 0
    finally:
        reset_request_context(token)
    assert result == "ok"
    url, payload, timeout = captured[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    expected = {"temperature": 0, "num_predict": 1024, "num_ctx": 8192}
    if seed is not None:
        expected["seed"] = seed
    assert payload["options"] == expected
    assert payload["format"] == "json"
    assert payload["think"] is False
    assert payload["stream"] is False
    assert 0 < timeout <= 0.5


@pytest.mark.parametrize("recover", [True, False])
def test_only_shared_transport_retries_and_records_usage(monkeypatch, recover):
    calls = []

    def post(url, payload, timeout):
        calls.append(json.loads(json.dumps(payload)))
        if recover and len(calls) == 2:
            return FakeResponse()
        raise requests.Timeout("private transport detail")

    monkeypatch.setattr(serving_chat, "_post_ollama", post)
    token = bind_request_context("fixture", deadline_ms=5000)
    try:
        if recover:
            assert _bounded_default_chat("fixture", []) == "ok"
        else:
            with pytest.raises(ModelRequestError) as error:
                _bounded_default_chat("fixture", [])
            assert error.value.attempts == 2
            assert "private" not in str(error.value)
        context = current_request_context()
        assert context.model_calls == 2
        assert context.model_retries == 1
        assert context.model_errors == int(not recover)
    finally:
        reset_request_context(token)
    assert len(calls) == 2
    assert all(
        call["options"] == {"temperature": 0, "num_predict": 1024, "num_ctx": 8192}
        for call in calls
    )


def test_exhausted_request_budget_prevents_post(monkeypatch):
    def post(*args):
        pytest.fail("exhausted request must not send")

    monkeypatch.setattr(serving_chat, "_post_ollama", post)
    token = bind_request_context("fixture", deadline_ms=1, clock_ms=lambda: 0)
    try:
        with pytest.raises(ModelRequestError) as error:
            _bounded_default_chat("fixture", [])
        assert error.value.code == "deadline_exhausted"
        assert error.value.attempts == 0
        assert current_request_context().model_calls == 0
    finally:
        reset_request_context(token)


@pytest.mark.parametrize(
    "kwargs", [{"seed": True}, {"seed": -1}, {"seed": 2147483648}, {"max_output_tokens": 2048}]
)
def test_fixed_policy_and_seed_validation_precede_transport(monkeypatch, kwargs):
    def post(*args):
        pytest.fail("invalid policy must not send")

    monkeypatch.setattr(serving_chat, "_post_ollama", post)
    with pytest.raises(ValueError):
        serving_chat.serving_chat("fixture", [], **kwargs)
