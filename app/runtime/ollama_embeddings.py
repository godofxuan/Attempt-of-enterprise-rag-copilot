from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np
import requests

from app.config import Settings
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint


_SHA256 = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


@dataclass(frozen=True)
class OllamaEmbeddingClient:
    origin: str
    model_identifier: str
    model_sha256: str
    dimension: int
    _session: requests.Session
    _timeout_seconds: float
    _max_attempts: int
    _backoff_seconds: float

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        probe_text: str = "embedding dimension probe",
        endpoint_context: str = "embedding",
    ) -> OllamaEmbeddingClient:
        try:
            origin = parse_pinned_model_endpoint(settings.llm_base_url).origin
        except ValueError as exc:
            raise ValueError(
                f"{endpoint_context} requires a pinned local Ollama origin"
            ) from exc

        session = requests.Session()
        session.trust_env = False
        request = _request_factory(settings)
        tags = request(
            lambda timeout: session.get(
                f"{origin}/api/tags",
                timeout=timeout,
                allow_redirects=False,
            )
        ).json()
        model_identifier = settings.embedding_model
        model_sha256 = _model_digest(tags, model_identifier)
        probe_payload = request(
            lambda timeout: session.post(
                f"{origin}/api/embed",
                json={"model": model_identifier, "input": probe_text},
                timeout=timeout,
                allow_redirects=False,
            )
        ).json()
        probe = _decode_embeddings(
            probe_payload,
            expected_count=1,
            expected_dimension=None,
        )[0]
        return cls(
            origin=origin,
            model_identifier=model_identifier,
            model_sha256=model_sha256,
            dimension=len(probe),
            _session=session,
            _timeout_seconds=settings.model_request_timeout_seconds,
            _max_attempts=settings.model_max_attempts,
            _backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
        )

    def embed_text(self, text: str) -> list[float]:
        payload = self._request_embeddings(text)
        return _decode_embeddings(
            payload,
            expected_count=1,
            expected_dimension=self.dimension,
        )[0]

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        if not texts:
            raise ValueError("embedding batch must not be empty")
        if any(not isinstance(text, str) or not text for text in texts):
            raise ValueError("embedding batch inputs must be non-empty strings")
        payload = self._request_embeddings(texts)
        vectors = _decode_embeddings(
            payload,
            expected_count=len(texts),
            expected_dimension=self.dimension,
        )
        return np.ascontiguousarray(vectors, dtype="float32")

    def _request_embeddings(self, input_value: str | list[str]) -> object:
        response = perform_model_request(
            lambda timeout: self._session.post(
                f"{self.origin}/api/embed",
                json={"model": self.model_identifier, "input": input_value},
                timeout=timeout,
                allow_redirects=False,
            ),
            operation="embed",
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
        ).response
        return response.json()


def _request_factory(
    settings: Settings,
) -> Callable[[Callable[[float], requests.Response]], requests.Response]:
    def request(send: Callable[[float], requests.Response]) -> requests.Response:
        return perform_model_request(
            send,
            operation="embed",
            timeout_seconds=settings.model_request_timeout_seconds,
            max_attempts=settings.model_max_attempts,
            backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
        ).response

    return request


def _model_digest(payload: object, model_identifier: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ValueError("Ollama tags response is invalid")
    exact: list[object] = []
    base: list[object] = []
    for item in payload["models"]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        if name == model_identifier:
            exact.append(item.get("digest"))
        elif name.removesuffix(":latest") == model_identifier:
            base.append(item.get("digest"))
    candidates = exact or base
    if len(candidates) != 1:
        raise ValueError("configured embedding model identity is ambiguous")
    digest = candidates[0]
    match = _SHA256.fullmatch(digest) if isinstance(digest, str) else None
    if match is None:
        raise ValueError("configured embedding model digest is invalid")
    return match.group(1)


def _decode_embeddings(
    payload: object,
    *,
    expected_count: int,
    expected_dimension: int | None,
) -> list[list[float]]:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("embeddings"),
        list,
    ):
        raise ValueError("Ollama embedding response is invalid")
    rows = payload["embeddings"]
    if len(rows) != expected_count or any(not isinstance(row, list) for row in rows):
        raise ValueError("Ollama embedding response is invalid")

    decoded: list[list[float]] = []
    for row in rows:
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in row
        ):
            raise ValueError("Ollama embedding values must be JSON numbers")
        vector = [float(value) for value in row]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Ollama embedding values must be finite numbers")
        if not vector or len(vector) > 65_536:
            raise ValueError("Ollama embedding dimension is invalid")
        if expected_dimension is not None and len(vector) != expected_dimension:
            raise ValueError("Ollama embedding dimension changed after probe")
        decoded.append(vector)
    return decoded


__all__ = ["OllamaEmbeddingClient"]
