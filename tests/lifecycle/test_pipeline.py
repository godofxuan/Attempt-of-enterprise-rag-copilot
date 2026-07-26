from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import pytest

from app.config import Settings
from app.lifecycle import pipeline as pipeline_module
from app.lifecycle.pipeline import build_ollama_lifecycle_runtime


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP status {self.status_code}")

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.trust_env_during_calls: list[bool] = []
        self.trust_env = True

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.trust_env_during_calls.append(self.trust_env)
        self.calls.append(("GET", url, kwargs))
        return self.responses.popleft()

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.trust_env_during_calls.append(self.trust_env)
        self.calls.append(("POST", url, kwargs))
        return self.responses.popleft()


def _settings(base_url: str = "http://127.0.0.1:11434/v1") -> Settings:
    return Settings(
        llm_base_url=base_url,
        embedding_model="bge-m3",
        model_max_attempts=1,
        model_retry_backoff_ms=0,
    )


def test_runtime_binds_actual_model_digest_dimension_and_embed_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "a" * 64
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {
                            "name": "bge-m3",
                            "digest": f"sha256:{digest}",
                        }
                    ]
                }
            ),
            FakeResponse({"embeddings": [[0.25, -0.5, 1.0]]}),
            FakeResponse({"embeddings": [[0.75, 0.0, -0.25]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    runtime = build_ollama_lifecycle_runtime(_settings())
    result = runtime.embed_text("operator query")

    assert runtime.pipeline.embedding.model_identifier == "bge-m3"
    assert runtime.pipeline.embedding.model_sha256 == digest
    assert runtime.pipeline.embedding.dimension == 3
    assert result == [0.75, 0.0, -0.25]
    assert session.trust_env is False
    assert session.trust_env_during_calls == [False, False, False]
    assert session.calls == [
        (
            "GET",
            "http://127.0.0.1:11434/api/tags",
            {"timeout": 12.0, "allow_redirects": False},
        ),
        (
            "POST",
            "http://127.0.0.1:11434/api/embed",
            {
                "json": {
                    "model": "bge-m3",
                    "input": "lifecycle embedding dimension probe",
                },
                "timeout": 12.0,
                "allow_redirects": False,
            },
        ),
        (
            "POST",
            "http://127.0.0.1:11434/api/embed",
            {
                "json": {
                    "model": "bge-m3",
                    "input": "operator query",
                },
                "timeout": 12.0,
                "allow_redirects": False,
            },
        ),
    ]


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "http://ollama.internal:11434",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://user@127.0.0.1:11434",
        "http://127.0.0.1:11434?target=remote",
        "http://127.0.0.1:11434#fragment",
    ],
)
def test_runtime_rejects_non_loopback_or_unpinned_origins_before_session_creation(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    session_created = False

    def fail_if_session_is_created() -> FakeSession:
        nonlocal session_created
        session_created = True
        raise AssertionError("invalid origins must fail before transport setup")

    monkeypatch.setattr(pipeline_module.requests, "Session", fail_if_session_is_created)

    with pytest.raises(
        ValueError,
        match="pinned local Ollama origin",
    ):
        build_ollama_lifecycle_runtime(_settings(base_url))

    assert session_created is False


@pytest.mark.parametrize(
    ("base_url", "origin"),
    [
        ("http://localhost:11434/v1", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://[::1]:11434/v1", "http://[::1]:11434"),
    ],
)
def test_runtime_allows_only_explicit_loopback_http_origins(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    origin: str,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "7" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[0.1, 0.2]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    build_ollama_lifecycle_runtime(_settings(base_url))

    assert [call[1] for call in session.calls] == [
        f"{origin}/api/tags",
        f"{origin}/api/embed",
    ]
    assert session.trust_env_during_calls == [False, False]


def test_runtime_rejects_malformed_exact_digest_instead_of_falling_back_to_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "not-a-sha256"},
                        {"name": "bge-m3:latest", "digest": "b" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[0.1, 0.2]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    with pytest.raises(ValueError, match="digest is invalid"):
        build_ollama_lifecycle_runtime(_settings())

    assert [call[1] for call in session.calls] == [
        "http://127.0.0.1:11434/api/tags"
    ]


@pytest.mark.parametrize("invalid_value", [math.nan, math.inf, -math.inf])
def test_runtime_rejects_non_finite_embedding_probe_values(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: float,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "c" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[invalid_value]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    with pytest.raises(ValueError, match="finite numbers"):
        build_ollama_lifecycle_runtime(_settings())


@pytest.mark.parametrize("invalid_value", [True, "0.25"])
def test_runtime_rejects_embedding_values_that_are_not_json_numbers(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: object,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "d" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[invalid_value]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    with pytest.raises(ValueError, match="JSON numbers"):
        build_ollama_lifecycle_runtime(_settings())


def test_embed_callback_rejects_dimension_drift_after_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "e" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[0.1, 0.2, 0.3]]}),
            FakeResponse({"embeddings": [[0.4, 0.5]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)
    runtime = build_ollama_lifecycle_runtime(_settings())

    with pytest.raises(ValueError, match="dimension"):
        runtime.embed_text("dimension drift")


def test_embed_callback_keeps_the_model_identity_bound_at_runtime_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "f" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[0.1, 0.2]]}),
            FakeResponse({"embeddings": [[0.3, 0.4]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)
    settings = _settings()
    runtime = build_ollama_lifecycle_runtime(settings)

    settings.embedding_model = "unreviewed-model"
    runtime.embed_text("stable identity")

    assert session.calls[-1][2]["json"]["model"] == "bge-m3"
    assert runtime.pipeline.embedding.model_identifier == "bge-m3"


@pytest.mark.parametrize(
    "models",
    [
        [
            {"name": "bge-m3", "digest": "1" * 64},
            {"name": "bge-m3", "digest": "2" * 64},
        ],
        [
            {"name": "bge-m3:latest", "digest": "3" * 64},
            {"name": "bge-m3:latest", "digest": "4" * 64},
        ],
    ],
)
def test_runtime_rejects_ambiguous_model_digest_candidates(
    monkeypatch: pytest.MonkeyPatch,
    models: list[dict[str, str]],
) -> None:
    session = FakeSession([FakeResponse({"models": models})])
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    with pytest.raises(ValueError, match="identity is ambiguous"):
        build_ollama_lifecycle_runtime(_settings())

    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "embedding_payload",
    [
        pytest.param({}, id="missing-embeddings"),
        pytest.param({"embeddings": None}, id="null-embeddings"),
        pytest.param({"embeddings": []}, id="no-vectors"),
        pytest.param({"embeddings": [0.1]}, id="vector-not-nested"),
        pytest.param(
            {"embeddings": [[0.1], [0.2]]},
            id="multiple-vectors",
        ),
        pytest.param({"embeddings": [[]]}, id="empty-vector"),
        pytest.param(
            {"embeddings": [[0.0] * 65_537]},
            id="dimension-over-limit",
        ),
    ],
)
def test_runtime_rejects_malformed_embedding_probe_shapes(
    monkeypatch: pytest.MonkeyPatch,
    embedding_payload: object,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "5" * 64},
                    ]
                }
            ),
            FakeResponse(embedding_payload),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)

    with pytest.raises(ValueError, match=r"Ollama embedding (response|dimension)"):
        build_ollama_lifecycle_runtime(_settings())


@pytest.mark.parametrize(
    ("invalid_value", "error"),
    [
        pytest.param(math.nan, "finite numbers", id="nan"),
        pytest.param(True, "JSON numbers", id="boolean"),
        pytest.param("0.1", "JSON numbers", id="numeric-string"),
    ],
)
def test_embed_callback_rejects_malformed_numeric_values(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: object,
    error: str,
) -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "models": [
                        {"name": "bge-m3", "digest": "6" * 64},
                    ]
                }
            ),
            FakeResponse({"embeddings": [[0.1]]}),
            FakeResponse({"embeddings": [[invalid_value]]}),
        ]
    )
    monkeypatch.setattr(pipeline_module.requests, "Session", lambda: session)
    runtime = build_ollama_lifecycle_runtime(_settings())

    with pytest.raises(ValueError, match=error):
        runtime.embed_text("malformed callback vector")
