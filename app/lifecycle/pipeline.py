from __future__ import annotations

import hashlib
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pydantic
import requests

from app.config import Settings
from app.indexing.computation_cache import (
    ComponentFingerprint,
    EmbeddingFingerprint,
)
from app.indexing.incremental_computation import EmbedText, PipelineConfiguration
from app.ingestion.chunking import ChunkerConfig
from app.runtime.model_transport import perform_model_request
from app.security.model_endpoint import parse_pinned_model_endpoint


_SHA256 = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


@dataclass(frozen=True)
class LifecyclePipelineRuntime:
    pipeline: PipelineConfiguration
    embed_text: EmbedText


def _local_ollama_origin(value: str) -> str:
    try:
        return parse_pinned_model_endpoint(value).origin
    except ValueError as exc:
        raise ValueError(
            "lifecycle embedding requires a pinned local Ollama origin"
        ) from exc


def _source_digest(*relative_paths: str) -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for relative_path in sorted(relative_paths):
        content = (root / relative_path).read_bytes()
        encoded = relative_path.encode("ascii")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _request(
    settings: Settings,
    send: Callable[[float], requests.Response],
) -> requests.Response:
    return perform_model_request(
        send,
        operation="embed",
        timeout_seconds=settings.model_request_timeout_seconds,
        max_attempts=settings.model_max_attempts,
        backoff_seconds=settings.model_retry_backoff_ms / 1000.0,
    ).response


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


def build_ollama_lifecycle_runtime(
    settings: Settings,
) -> LifecyclePipelineRuntime:
    origin = _local_ollama_origin(settings.llm_base_url)
    model_identifier = settings.embedding_model
    session = requests.Session()
    session.trust_env = False
    tags = _request(
        settings,
        lambda timeout: session.get(
            f"{origin}/api/tags",
            timeout=timeout,
            allow_redirects=False,
        ),
    ).json()
    model_sha256 = _model_digest(tags, model_identifier)
    expected_dimension: int | None = None

    def embed_text(text: str) -> list[float]:
        response = _request(
            settings,
            lambda timeout: session.post(
                f"{origin}/api/embed",
                json={"model": model_identifier, "input": text},
                timeout=timeout,
                allow_redirects=False,
            ),
        )
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("embeddings"), list)
            or len(payload["embeddings"]) != 1
            or not isinstance(payload["embeddings"][0], list)
        ):
            raise ValueError("Ollama embedding response is invalid")
        values = payload["embeddings"][0]
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in values
        ):
            raise ValueError("Ollama embedding values must be JSON numbers")
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Ollama embedding values must be finite numbers")
        if not vector or len(vector) > 65_536:
            raise ValueError("Ollama embedding dimension is invalid")
        if (
            expected_dimension is not None
            and len(vector) != expected_dimension
        ):
            raise ValueError("Ollama embedding dimension changed after probe")
        return vector

    probe = embed_text("lifecycle embedding dimension probe")
    expected_dimension = len(probe)
    dependencies = tuple(
        sorted(
            (
                f"pydantic={pydantic.__version__}",
                f"python={sys.version_info.major}.{sys.version_info.minor}",
            )
        )
    )
    pipeline = PipelineConfiguration(
        materializer=ComponentFingerprint(
            name="production-revision-materializer",
            semantic_version="1",
            implementation_sha256=_source_digest(
                "lifecycle/materializer.py",
                "ingestion/quarantine.py",
                "ingestion/revision_catalog.py",
            ),
            dependency_versions=dependencies,
        ),
        governance=ComponentFingerprint(
            name="enterprise-document-governance",
            semantic_version="1",
            implementation_sha256=_source_digest("ingestion/versions.py"),
            dependency_versions=dependencies,
        ),
        normalizer=ComponentFingerprint(
            name="lifecycle-normalizer",
            semantic_version="1",
            implementation_sha256=_source_digest("lifecycle/materializer.py"),
            dependency_versions=dependencies,
        ),
        chunker=ComponentFingerprint(
            name="enterprise-chunker",
            semantic_version="1",
            implementation_sha256=_source_digest("ingestion/chunking.py"),
            dependency_versions=dependencies,
        ),
        chunker_config=ChunkerConfig(
            mode=settings.v2_chunker_mode,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        ),
        embedding=EmbeddingFingerprint(
            component=ComponentFingerprint(
                name="ollama-embedding",
                semantic_version="1",
                implementation_sha256=_source_digest(
                    "lifecycle/pipeline.py",
                    "runtime/model_transport.py",
                ),
                dependency_versions=dependencies,
            ),
            backend="ollama-local",
            model_identifier=model_identifier,
            model_sha256=model_sha256,
            dimension=len(probe),
            normalization="l2",
        ),
    )
    return LifecyclePipelineRuntime(
        pipeline=pipeline,
        embed_text=embed_text,
    )


__all__ = [
    "LifecyclePipelineRuntime",
    "build_ollama_lifecycle_runtime",
]
