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
from scripts.eval_finqa import (
    DEFAULT_FREEZE_PROTOCOL,
    _validate_frozen_source_hashes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one hash-pinned FinQA split into private D-drive data."
    )
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--execute-frozen-test-download", action="store_true")
    parser.add_argument(
        "--freeze-protocol",
        type=Path,
        default=DEFAULT_FREEZE_PROTOCOL,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.split == "test":
        if not args.execute_frozen_test_download:
            raise ValueError("FinQA test download requires explicit confirmation")
        try:
            protocol = json.loads(
                args.freeze_protocol.resolve().read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "FinQA test download requires an existing frozen protocol"
            ) from exc
        if not isinstance(protocol, dict) or protocol.get("status") != "FROZEN":
            raise ValueError("FinQA test download requires a frozen protocol")
        _validate_frozen_source_hashes(protocol)
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
