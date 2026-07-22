from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.evaluation.indirect_injection_cross_model_public import (
    export_cross_model_public,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export R2-S4 content-free cross-model observation evidence."
    )
    parser.add_argument("private_run", type=Path)
    parser.add_argument("output_dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        package = export_cross_model_public(args.private_run, args.output_dir)
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        _write(
            sys.stderr,
            {
                "status": "EXPORT_FAILED",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        return 1
    _write(
        sys.stdout,
        {
            "status": "EXPORTED_OBSERVATION_EVIDENCE",
            "package": package.as_posix(),
        },
    )
    return 0


def _write(stream, payload: dict[str, object]) -> None:
    stream.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
