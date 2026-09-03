from app import ollama_chat


def test_chat_can_return_transport_counts(monkeypatch) -> None:
    class _Response:
        def json(self):
            return {"message": {"content": "ok"}}

    class _Result:
        response = _Response()
        attempts = 2
        retries = 1

    monkeypatch.setattr(ollama_chat, "perform_model_request", lambda *args, **kwargs: _Result())
    monkeypatch.setattr(
        ollama_chat,
        "get_settings",
        lambda: type("Settings", (), {"llm_base_url": "http://127.0.0.1:11434", "model_request_timeout_seconds": 30, "model_max_attempts": 2, "model_retry_backoff_ms": 1})(),
    )

    assert ollama_chat.chat_with_ollama(
        "fixture", [{"role": "user", "content": "test"}], return_transport=True
    ) == ("ok", 2, 1)
