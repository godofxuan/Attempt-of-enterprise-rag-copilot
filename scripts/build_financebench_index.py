from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.external_datasets.financebench import (
    DEFAULT_PREPARED_ROOT,
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    verify_financebench_preparation,
)
from app.indexing.builder import preview_build
from app.indexing.resumable_embeddings import (
    EmbeddingProgress,
    ResumableBatchEmbedder,
)
from app.indexing.store import build_index_version, load_index_version
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.parsers_pdf import PdfDocumentParser
from app.runtime.ollama_embeddings import OllamaEmbeddingClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an isolated BGE-M3 index for pinned FinanceBench data."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT / "indexes",
    )
    parser.add_argument("--run-id", default="financebench-bge-m3-v1")
    parser.add_argument(
        "--chunker",
        choices=("fixed", "heading", "parent-child"),
        default="heading",
    )
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--parent-size", type=int, default=4000)
    parser.add_argument("--child-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-batch-chars", type=int, default=48_000)
    parser.add_argument(
        "--embedding-cache-dir",
        type=Path,
        default=DEFAULT_PRIVATE_ROOT / "embedding_cache",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = verify_financebench_preparation(
        args.source_root,
        args.prepared_root,
    )
    settings = get_settings()
    chunker = ChunkerConfig(
        mode=args.chunker.replace("-", "_"),
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        parent_size=args.parent_size,
        child_size=args.child_size,
    )
    if args.dry_run:
        preview = preview_build(
            input_dir=args.source_root.resolve(),
            chunker_config=chunker,
        )
        payload = {
            "action": "preview",
            "dataset_revision": dataset.revision,
            **preview.model_dump(mode="json"),
        }
    else:
        output_root = args.output_dir.resolve()
        print(
            "Binding the exact local Ollama model identity...",
            file=sys.stderr,
            flush=True,
        )
        client = OllamaEmbeddingClient.from_settings(
            settings,
            probe_text="FinanceBench embedding dimension probe",
            endpoint_context="FinanceBench embedding",
        )

        def report_progress(progress: EmbeddingProgress) -> None:
            should_report = (
                progress.completed_batches == 1
                or progress.completed_batches == progress.total_batches
                or progress.completed_batches % 10 == 0
            )
            if should_report:
                print(
                    "Embedding "
                    f"{progress.completed_batches}/{progress.total_batches} batches, "
                    f"{progress.completed_rows}/{progress.total_rows} vectors "
                    f"({progress.event})",
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
            progress_observer=report_progress,
        )
        print(
            "Parsing and chunking 84 pinned FinanceBench PDFs. "
            "This phase can take several minutes...",
            file=sys.stderr,
            flush=True,
        )
        index_manifest = build_index_version(
            root=output_root,
            input_dir=args.source_root.resolve(),
            run_id=args.run_id,
            chunker_config=chunker,
            embedding_model=client.model_identifier,
            embed_chunks=embedder,
            activate=True,
            force=args.force,
        )
        loaded = load_index_version(output_root)
        if embedder.summary is None:
            raise AssertionError("embedding build completed without a cache summary")
        payload = {
            "action": "build_and_activate",
            "dataset_revision": dataset.revision,
            "embedding_model": client.model_identifier,
            "embedding_model_sha256": client.model_sha256,
            "embedding_cache": {
                "build_id": embedder.summary.build_id,
                "cache_dir": str(embedder.summary.cache_dir),
                "total_batches": embedder.summary.total_batches,
                "cache_hit_batches": embedder.summary.cache_hit_batches,
                "computed_batches": embedder.summary.computed_batches,
                "recomputed_batches": embedder.summary.recomputed_batches,
                "vector_count": embedder.summary.vector_count,
                "dimension": embedder.summary.dimension,
            },
            "output_dir": str(output_root),
            "manifest_sha256": loaded.manifest_sha256,
            **index_manifest.model_dump(mode="json"),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
