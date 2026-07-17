from types import SimpleNamespace

import pytest
import requests

import app.ollama_chat as ollama_chat
from app.runtime.model_transport import ModelRequestError


class FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": '{"verdict": "sufficient"}'}}


def settings():
    return SimpleNamespace(
        llm_base_url="http://127.0.0.1:11434/v1",
        model_request_timeout_seconds=7.0,
        model_max_attempts=2,
        model_retry_backoff_ms=0,
    )


def test_chat_with_ollama_passes_json_format_without_changing_defaults(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured.update(url=url, payload=payload, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        settings,
    )
    monkeypatch.setattr(ollama_chat, "_post_ollama", fake_post)

    result = ollama_chat.chat_with_ollama(
        "qwen2.5:3b",
        [{"role": "user", "content": "judge"}],
        response_format="json",
    )

    assert result == '{"verdict": "sufficient"}'
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["options"] == {"temperature": 0}
    assert captured["payload"]["stream"] is False
    assert captured["timeout"] == 7.0


def test_chat_with_ollama_passes_think_as_top_level_api_field(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured["payload"] = payload
        return FakeResponse()

    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        settings,
    )
    monkeypatch.setattr(ollama_chat, "_post_ollama", fake_post)

    ollama_chat.chat_with_ollama(
        "qwen3:8b",
        [{"role": "user", "content": "judge"}],
        response_format="json",
        think=False,
    )

    assert captured["payload"]["think"] is False
    assert "think" not in captured["payload"]["options"]


def test_chat_with_ollama_omits_format_for_regular_answer_generation(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured["payload"] = payload
        return FakeResponse()

    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        settings,
    )
    monkeypatch.setattr(ollama_chat, "_post_ollama", fake_post)

    ollama_chat.chat_with_ollama(
        "qwen2.5:3b",
        [{"role": "user", "content": "answer"}],
    )

    assert "format" not in captured["payload"]
    assert "think" not in captured["payload"]


def test_chat_with_ollama_does_not_expose_non_retryable_response_body(monkeypatch):
    class ErrorResponse(FakeResponse):
        status_code = 400
        text = "password=never-show D:/vault/model.bin"

        def raise_for_status(self):
            error = requests.HTTPError("bad request")
            error.response = self
            raise error

    monkeypatch.setattr(ollama_chat, "get_settings", settings)
    monkeypatch.setattr(
        ollama_chat,
        "_post_ollama",
        lambda url, payload, timeout: ErrorResponse(),
    )

    with pytest.raises(ModelRequestError) as exc_info:
        ollama_chat.chat_with_ollama(
            "qwen2.5:3b",
            [{"role": "user", "content": "answer"}],
        )

    assert exc_info.value.code == "http_400"
    assert exc_info.value.attempts == 1
    assert "never-show" not in str(exc_info.value)
    assert "vault" not in str(exc_info.value)
