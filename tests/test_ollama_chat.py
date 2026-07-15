from types import SimpleNamespace

import app.ollama_chat as ollama_chat


class FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": '{"verdict": "sufficient"}'}}


def test_chat_with_ollama_passes_json_format_without_changing_defaults(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured.update(url=url, payload=payload, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        lambda: SimpleNamespace(llm_base_url="http://127.0.0.1:11434/v1"),
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
    assert captured["timeout"] == 180


def test_chat_with_ollama_passes_think_as_top_level_api_field(monkeypatch):
    captured = {}

    def fake_post(url, payload, timeout):
        captured["payload"] = payload
        return FakeResponse()

    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        lambda: SimpleNamespace(llm_base_url="http://127.0.0.1:11434/v1"),
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
        lambda: SimpleNamespace(llm_base_url="http://127.0.0.1:11434/v1"),
    )
    monkeypatch.setattr(ollama_chat, "_post_ollama", fake_post)

    ollama_chat.chat_with_ollama(
        "qwen2.5:3b",
        [{"role": "user", "content": "answer"}],
    )

    assert "format" not in captured["payload"]
    assert "think" not in captured["payload"]
