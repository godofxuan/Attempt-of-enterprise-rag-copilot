try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_SOURCE_ROOT,
    download_finqa_split,
    load_finqa_split,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one hash-pinned FinQA split into private D-drive data."
    )
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--execute-frozen-test-download", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target, digest, byte_count = download_finqa_split(
        split=args.split,
        source_root=args.source_root,
        allow_test=args.execute_frozen_test_download,
    )
    case_count = None
    if args.split == "dev":
        cases, _ = load_finqa_split(target, expected_sha256=digest)
        case_count = len(cases)
    print(
        json.dumps(
            {
                "split": args.split,
                "target": str(target),
                "sha256": digest,
                "byte_count": byte_count,
                "case_count": case_count,
                "test_labels_loaded": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
