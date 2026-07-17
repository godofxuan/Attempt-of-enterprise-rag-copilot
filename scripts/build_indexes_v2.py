from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import _bootstrap  # noqa: F401

from app.config import get_settings
from app.domain.documents import DocumentParseError
from app.indexing.builder import EmbedText, preview_build
from app.indexing.store import (
    activate_version,
    build_index_version,
    load_index_version,
)
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.normalize import load_source_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and activate a validated enterprise v2 index version.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Generated corpus directory containing manifest.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Versioned index store root.",
    )
    parser.add_argument(
        "--profile",
        choices=("demo", "benchmark"),
        help="Expected corpus profile; defaults to the v2 setting.",
    )
    parser.add_argument(
        "--run-id",
        help="Immutable version identifier for a new build.",
    )
    parser.add_argument(
        "--chunker",
        choices=("fixed", "heading", "parent-child"),
        help="Chunking mode; defaults to the v2 setting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, govern, and chunk without embedding or writing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only a validated, inactive version with the same run ID.",
    )
    parser.add_argument(
        "--activate-existing",
        metavar="RUN_ID",
        help="Activate a validated existing version without rebuilding.",
    )
    return parser


def _validate_arguments(parser: argparse.ArgumentParser, args) -> None:
    if args.activate_existing is not None:
        if args.output_dir is None:
            parser.error("--output-dir is required with --activate-existing")
        conflicting = {
            "--input-dir": args.input_dir,
            "--run-id": args.run_id,
            "--profile": args.profile,
            "--chunker": args.chunker,
            "--dry-run": args.dry_run,
            "--force": args.force,
        }
        used = [name for name, value in conflicting.items() if value]
        if used:
            parser.error(
                "--activate-existing cannot be combined with " + ", ".join(used)
            )
        return

    if args.input_dir is None:
        parser.error("--input-dir is required unless --activate-existing is used")
    if args.dry_run:
        if args.force:
            parser.error("--force cannot be combined with --dry-run")
        if args.run_id is not None:
            parser.error("--run-id is not used with --dry-run")
        return
    if args.output_dir is None:
        parser.error("--output-dir is required for a build")
    if args.run_id is None:
        parser.error("--run-id is required for a build")


def _validate_output_root(path: Path) -> Path:
    resolved = Path(path).resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise PermissionError(f"refusing unsafe output root: {resolved}")
    return resolved


def _source_profile(input_dir: Path) -> str:
    manifest = load_source_manifest(Path(input_dir) / "manifest.json")
    return getattr(manifest, "profile_id", None) or manifest.source_profile_id


def _chunker_config(mode: str, *, chunk_size: int, overlap: int) -> ChunkerConfig:
    return ChunkerConfig(
        mode=mode.replace("-", "_"),
        chunk_size=chunk_size,
        overlap=overlap,
    )


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(
    argv: list[str] | None = None,
    *,
    embed_text: EmbedText | None = None,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_arguments(parser, args)
    settings = get_settings()

    try:
        if args.activate_existing is not None:
            output_root = _validate_output_root(args.output_dir)
            pointer = activate_version(output_root, args.activate_existing)
            loaded = load_index_version(output_root)
            _print_json(
                {
                    "action": "activate_existing",
                    "run_id": pointer.run_id,
                    "manifest_sha256": pointer.manifest_sha256,
                    "output_dir": str(output_root),
                    "version_dir": str(loaded.path),
                    "written": False,
                    "activated": True,
                }
            )
            return 0

        input_dir = Path(args.input_dir).resolve()
        profile = args.profile or settings.v2_corpus_profile
        actual_profile = _source_profile(input_dir)
        if actual_profile != profile:
            raise ValueError(
                f"corpus profile is {actual_profile!r}, expected {profile!r}"
            )
        mode = args.chunker or settings.v2_chunker_mode.replace("_", "-")
        chunker_config = _chunker_config(
            mode,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )

        if args.dry_run:
            preview = preview_build(
                input_dir=input_dir,
                chunker_config=chunker_config,
            )
            summary = preview.model_dump(mode="json")
            summary["action"] = "preview"
            summary["input_dir"] = str(input_dir)
            _print_json(summary)
            return 0

        output_root = _validate_output_root(args.output_dir)
        if embed_text is None:
            from app.retriever import _embed_text

            def ollama_embed(text: str) -> list[float]:
                return _embed_text(settings.embedding_model, text)

            embed_text = ollama_embed
        manifest = build_index_version(
            root=output_root,
            input_dir=input_dir,
            run_id=args.run_id,
            chunker_config=chunker_config,
            embedding_model=settings.embedding_model,
            embed_text=embed_text,
            activate=True,
            force=args.force,
        )
        loaded = load_index_version(output_root)
        _print_json(
            {
                "action": "build_and_activate",
                "run_id": manifest.run_id,
                "profile_id": manifest.profile_id,
                "source_document_count": manifest.source_document_count,
                "canonical_document_count": manifest.canonical_document_count,
                "duplicate_count": manifest.duplicate_count,
                "chunk_count": manifest.chunk_count,
                "indexed_chunk_count": manifest.indexed_chunk_count,
                "manifest_sha256": loaded.manifest_sha256,
                "input_dir": str(input_dir),
                "output_dir": str(output_root),
                "version_dir": str(loaded.path),
                "written": True,
                "activated": True,
            }
        )
        return 0
    except DocumentParseError as exc:
        print(
            "error: " + json.dumps(exc.to_dict(), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
