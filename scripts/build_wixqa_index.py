from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.external_datasets.wixqa import (
    DEFAULT_WIXQA_MANIFEST,
    DEFAULT_WIXQA_ROOT,
    load_wixqa_articles,
    verify_wixqa_source,
)
from app.external_datasets.wixqa_retrieval import build_wixqa_flat_index
from app.indexing.resumable_embeddings import EmbeddingProgress, ResumableBatchEmbedder
from app.ingestion.chunking import ChunkerConfig
from app.runtime.model_transport import ModelRequestError
from app.runtime.ollama_embeddings import OllamaEmbeddingClient

DEFAULT_INDEX_ROOT = Path(".private/external/wixqa/indexes")
DEFAULT_CACHE_ROOT = Path(".private/external/wixqa/embedding_cache")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the pinned WixQA flat index.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_WIXQA_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_WIXQA_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--embedding-cache", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--run-id", default="wixqa-flat-bge-m3-v1")
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-batch-chars", type=int, default=48_000)
    parser.add_argument(
        "--split-on-embedding-http-500",
        action="store_true",
        help=(
            "Retry only an Ollama HTTP 500 batch as bounded half-batches. "
            "Intended for GPU backends that emit NaN for a specific large batch."
        ),
    )
    parser.add_argument(
        "--embedding-http-500-single-fallback-url",
        help=(
            "Pinned local Ollama base URL used only when a one-text GPU batch "
            "still returns HTTP 500 after bounded splitting."
        ),
    )
    return parser


class _SplitOnHttp500EmbeddingClient:
    """Keep the frozen outer cache plan while bounding a backend-only fallback."""

    def __init__(
        self,
        client: OllamaEmbeddingClient,
        *,
        single_fallback: OllamaEmbeddingClient | None = None,
    ) -> None:
        self._client = client
        self._single_fallback = single_fallback
        self.model_identifier = client.model_identifier
        self.model_sha256 = client.model_sha256
        self.dimension = client.dimension
        if single_fallback is not None and (
            single_fallback.model_identifier != self.model_identifier
            or single_fallback.model_sha256 != self.model_sha256
            or single_fallback.dimension != self.dimension
        ):
            raise ValueError("embedding HTTP 500 fallback model identity differs")

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        try:
            return self._client.embed_batch(texts)
        except ModelRequestError as exc:
            if exc.status_code != 500:
                raise
            if len(texts) == 1:
                if self._single_fallback is None:
                    raise
                print(
                    "embedding GPU HTTP 500 persisted for one text; "
                    "using the identity-matched pinned local fallback",
                    file=sys.stderr,
                    flush=True,
                )
                return self._single_fallback.embed_batch(texts)
            midpoint = len(texts) // 2
            return np.concatenate(
                (
                    self.embed_batch(texts[:midpoint]),
                    self.embed_batch(texts[midpoint:]),
                ),
                axis=0,
            )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verify_wixqa_source(args.source_root, args.manifest)
    articles = load_wixqa_articles(args.source_root)
    settings = get_settings()
    client = OllamaEmbeddingClient.from_settings(
        settings,
        probe_text="WixQA embedding dimension probe",
        endpoint_context="WixQA flat index embedding",
    )
    fallback_client = None
    if args.embedding_http_500_single_fallback_url:
        fallback_client = OllamaEmbeddingClient.from_settings(
            settings.model_copy(
                update={
                    "llm_base_url": args.embedding_http_500_single_fallback_url,
                }
            ),
            probe_text="WixQA fallback embedding dimension probe",
            endpoint_context="WixQA flat index embedding fallback",
        )
    embedding_client = (
        _SplitOnHttp500EmbeddingClient(
            client,
            single_fallback=fallback_client,
        )
        if args.split_on_embedding_http_500
        else client
    )

    def report(progress: EmbeddingProgress) -> None:
        if (
            progress.completed_batches in {1, progress.total_batches}
            or progress.completed_batches % 10 == 0
        ):
            print(
                f"embedding {progress.completed_batches}/{progress.total_batches} "
                f"batches, {progress.completed_rows}/{progress.total_rows} chunks "
                f"({progress.event})",
                file=sys.stderr,
                flush=True,
            )

    dataset_manifest_sha256 = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    embedder = ResumableBatchEmbedder(
        cache_root=args.embedding_cache.resolve(),
        client=embedding_client,
        corpus_manifest_sha256=dataset_manifest_sha256,
        parser_versions={"wixqa_adapter": "wixqa_v1"},
        chunker_config=ChunkerConfig(
            mode="fixed",
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        ),
        batch_size=args.batch_size,
        max_batch_chars=args.max_batch_chars,
        progress_observer=report,
    )

    def cache_build_id() -> str:
        if embedder.summary is None:
            raise AssertionError("WixQA embedding summary is missing")
        return embedder.summary.build_id

    manifest = build_wixqa_flat_index(
        output_root=args.output_root,
        run_id=args.run_id,
        articles=articles,
        dataset_manifest_sha256=dataset_manifest_sha256,
        embedding_model=client.model_identifier,
        embedding_model_sha256=client.model_sha256,
        embed_chunks=embedder,  # type: ignore[arg-type]
        embedding_cache_build_id=cache_build_id,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
    )
    print(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
