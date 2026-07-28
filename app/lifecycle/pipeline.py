from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pydantic
import requests  # noqa: F401  # compatibility hook for transport tests

from app.config import Settings
from app.indexing.computation_cache import (
    ComponentFingerprint,
    EmbeddingFingerprint,
)
from app.indexing.incremental_computation import EmbedText, PipelineConfiguration
from app.ingestion.chunking import ChunkerConfig
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


@dataclass(frozen=True)
class LifecyclePipelineRuntime:
    pipeline: PipelineConfiguration
    embed_text: EmbedText


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


def build_ollama_lifecycle_runtime(
    settings: Settings,
) -> LifecyclePipelineRuntime:
    client = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="lifecycle embedding dimension probe",
        endpoint_context="lifecycle embedding",
    )
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
            model_identifier=client.model_identifier,
            model_sha256=client.model_sha256,
            dimension=client.dimension,
            normalization="l2",
        ),
    )
    return LifecyclePipelineRuntime(
        pipeline=pipeline,
        embed_text=client.embed_text,
    )


__all__ = [
    "LifecyclePipelineRuntime",
    "build_ollama_lifecycle_runtime",
]
