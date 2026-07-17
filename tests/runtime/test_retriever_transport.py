from __future__ import annotations

from types import SimpleNamespace

import app.retriever as retriever
from app.runtime.request_context import bind_request_context, reset_request_context


class FakeEmbedResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"embeddings": [[0.25, 0.75]]}


def test_embed_uses_request_remainder_instead_of_larger_config_timeout(
    monkeypatch,
) -> None:
    captured: dict[str, float] = {}
    monkeypatch.setattr(
        retriever,
        "get_settings",
        lambda: SimpleNamespace(
            llm_base_url="http://127.0.0.1:11434/v1",
            model_request_timeout_seconds=10.0,
            model_max_attempts=2,
            model_retry_backoff_ms=0,
        ),
    )

    def fake_post(url, payload, timeout):
        captured["timeout"] = timeout
        return FakeEmbedResponse()

    monkeypatch.setattr(retriever, "_post_ollama", fake_post)
    token = bind_request_context("req", deadline_ms=500)
    try:
        result = retriever._embed_text("bge-m3", "visible policy")
    finally:
        reset_request_context(token)

    assert result == [0.25, 0.75]
    assert 0 < captured["timeout"] <= 0.5
