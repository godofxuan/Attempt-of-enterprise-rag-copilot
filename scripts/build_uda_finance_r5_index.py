from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.external_datasets.uda_finance_r5 import (
    R5_PREPARED_ROOT,
    R5_PRIVATE_ROOT,
    R5_SOURCE_ROOT,
    verify_uda_finance_r5_preparation,
)
from app.indexing.builder import preview_build
from app.indexing.resumable_embeddings import EmbeddingProgress, ResumableBatchEmbedder
from app.indexing.store import build_index_version, load_index_version
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.parsers_pdf import PdfDocumentParser
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the isolated UDA R5 index.")
    parser.add_argument("--source-root", type=Path, default=R5_SOURCE_ROOT)
    parser.add_argument("--prepared-root", type=Path, default=R5_PREPARED_ROOT)
    parser.add_argument("--output-dir", type=Path, default=R5_PRIVATE_ROOT / "indexes")
    parser.add_argument("--run-id", default="uda-finance-r5-bge-m3-v1")
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-batch-chars", type=int, default=24_000)
    parser.add_argument(
        "--embedding-cache-dir", type=Path, default=R5_PRIVATE_ROOT / "embedding_cache"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = verify_uda_finance_r5_preparation(
        source_root=args.source_root,
        prepared_root=args.prepared_root,
    )
    chunker = ChunkerConfig(mode="heading", chunk_size=args.chunk_size, overlap=args.overlap)
    if args.dry_run:
        payload = {
            "action": "preview",
            **preview_build(
                input_dir=args.source_root.resolve(), chunker_config=chunker
            ).model_dump(mode="json"),
        }
    else:
        settings = get_settings()
        client = OllamaEmbeddingClient.from_settings(
            settings,
            probe_text="UDA finance R5 embedding dimension probe",
            endpoint_context="UDA finance R5 embedding",
        )

        def report(progress: EmbeddingProgress) -> None:
            if (
                progress.completed_batches in {1, progress.total_batches}
                or progress.completed_batches % 20 == 0
            ):
                print(
                    f"Embedding {progress.completed_batches}/{progress.total_batches} batches, "
                    f"{progress.completed_rows}/{progress.total_rows} vectors ({progress.event})",
                    file=sys.stderr,
                    flush=True,
                )

        embedder = ResumableBatchEmbedder(
            cache_root=args.embedding_cache_dir.resolve(),
            client=client,
            corpus_manifest_sha256=dataset.corpus_manifest_sha256,
            parser_versions={"pdf": PdfDocumentParser.version},
            chunker_config=chunker,
            batch_size=args.batch_size,
            max_batch_chars=args.max_batch_chars,
            progress_observer=report,
        )
        started = time.perf_counter()
        manifest = build_index_version(
            root=args.output_dir.resolve(),
            input_dir=args.source_root.resolve(),
            run_id=args.run_id,
            chunker_config=chunker,
            embedding_model=client.model_identifier,
            embed_chunks=embedder,
            activate=True,
            force=args.force,
        )
        loaded = load_index_version(args.output_dir.resolve())
        if embedder.summary is None:
            raise AssertionError("R5 embedding build completed without a cache summary")
        payload = {
            "action": "build_and_activate",
            "build_duration_ms": (time.perf_counter() - started) * 1000,
            "embedding_model": client.model_identifier,
            "embedding_model_sha256": client.model_sha256,
            "embedding_cache": {
                "build_id": embedder.summary.build_id,
                "total_batches": embedder.summary.total_batches,
                "cache_hit_batches": embedder.summary.cache_hit_batches,
                "computed_batches": embedder.summary.computed_batches,
                "recomputed_batches": embedder.summary.recomputed_batches,
                "vector_count": embedder.summary.vector_count,
                "dimension": embedder.summary.dimension,
            },
            "manifest_sha256": loaded.manifest_sha256,
            **manifest.model_dump(mode="json"),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
