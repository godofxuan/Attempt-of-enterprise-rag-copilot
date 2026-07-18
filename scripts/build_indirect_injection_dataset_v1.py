from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import _bootstrap  # noqa: F401

from app.evaluation.indirect_injection_dataset import build_v1_bundle, sha256_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the immutable R2-S1 indirect-injection v1 dataset bundle."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--frozen-at-utc", required=True)
    parser.add_argument("--freeze-git-head", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = build_v1_bundle(
        args.output_root,
        frozen_at_utc=args.frozen_at_utc,
        freeze_git_head=args.freeze_git_head,
    )
    result = {
        key: {
            "path": path.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for key, path in sorted(paths.items())
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
