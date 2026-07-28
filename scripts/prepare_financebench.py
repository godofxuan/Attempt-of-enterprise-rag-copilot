from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.external_datasets.financebench import (
    DEFAULT_PREPARED_ROOT,
    DEFAULT_SOURCE_ROOT,
    download_financebench,
    prepare_financebench,
    verify_financebench_preparation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download and prepare the version-pinned FinanceBench open sample "
            "as an isolated external Enterprise RAG evaluation corpus."
        )
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED_ROOT)
    parser.add_argument("--split-seed", type=int, default=20260728)
    parser.add_argument("--dev-ratio", type=float, default=1 / 3)
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Validate and prepare files already present under source-root.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify an existing prepared dataset without downloading or rewriting.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify_only:
        manifest = verify_financebench_preparation(
            args.source_root,
            args.prepared_root,
        )
        payload = {
            "action": "verify",
            "status": "PASSED",
            **manifest.model_dump(mode="json"),
        }
    else:
        download_summary = None
        if not args.skip_download:
            download_summary = download_financebench(args.source_root)
        result = prepare_financebench(
            args.source_root,
            args.prepared_root,
            split_seed=args.split_seed,
            dev_ratio=args.dev_ratio,
        )
        payload = {
            "action": "prepare",
            "status": "PASSED",
            "source_root": str(result.source_root),
            "prepared_root": str(result.prepared_root),
            "download": download_summary,
            **result.manifest.model_dump(mode="json"),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
