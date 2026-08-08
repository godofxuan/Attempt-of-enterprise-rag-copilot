from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

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
    return parser


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

    def report(progress: EmbeddingProgress) -> None:
        if progress.completed_batches in {1, progress.total_batches} or progress.completed_batches % 10 == 0:
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
        client=client,
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

