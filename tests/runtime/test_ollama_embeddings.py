from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from app.config import Settings
from app.runtime import ollama_embeddings as module
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


@dataclass
class FakeResponse:
    payload: object

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, payloads: list[object]) -> None:
        self.responses = deque(FakeResponse(payload) for payload in payloads)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.trust_env = True

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self.responses.popleft()

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self.responses.popleft()


def _settings() -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:11434/v1",
        embedding_model="bge-m3",
        model_max_attempts=1,
        model_retry_backoff_ms=0,
    )


def test_batch_client_binds_identity_and_preserves_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        [
            {
                "models": [
                    {"name": "bge-m3", "digest": f"sha256:{'a' * 64}"},
                ]
            },
            {"embeddings": [[1.0, 0.0, 0.0]]},
            {"embeddings": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]},
        ]
    )
    monkeypatch.setattr(module.requests, "Session", lambda: session)

    client = OllamaEmbeddingClient.from_settings(_settings())
    result = client.embed_batch(["first", "second"])

    assert client.model_sha256 == "a" * 64
    assert client.dimension == 3
    assert session.trust_env is False
    assert result.dtype == np.float32
    np.testing.assert_array_equal(
        result,
        np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype="float32"),
    )
    assert session.calls[-1][2]["json"] == {
        "model": "bge-m3",
        "input": ["first", "second"],
    }
    assert session.calls[-1][2]["allow_redirects"] is False


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        pytest.param(
            {"embeddings": [[1.0, 2.0, 3.0]]},
            "response",
            id="missing-row",
        ),
        pytest.param(
            {"embeddings": [[1.0, 2.0], [3.0, 4.0]]},
            "dimension",
            id="dimension-drift",
        ),
        pytest.param(
            {"embeddings": [[1.0, 2.0, 3.0], [1.0, True, 3.0]]},
            "JSON numbers",
            id="boolean",
        ),
    ],
)
def test_batch_client_rejects_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    error: str,
) -> None:
    session = FakeSession(
        [
            {"models": [{"name": "bge-m3", "digest": "b" * 64}]},
            {"embeddings": [[1.0, 0.0, 0.0]]},
            payload,
        ]
    )
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    client = OllamaEmbeddingClient.from_settings(_settings())

    with pytest.raises(ValueError, match=error):
        client.embed_batch(["first", "second"])


def test_batch_client_rejects_empty_batch_without_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        [
            {"models": [{"name": "bge-m3", "digest": "c" * 64}]},
            {"embeddings": [[1.0, 0.0]]},
        ]
    )
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    client = OllamaEmbeddingClient.from_settings(_settings())

    with pytest.raises(ValueError, match="must not be empty"):
        client.embed_batch([])

    assert len(session.calls) == 2
