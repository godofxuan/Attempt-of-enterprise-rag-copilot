from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.evaluation.indirect_injection_exposure_writer import (
    verify_exposure_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an immutable R2-S3 private exposure run."
    )
    parser.add_argument("run_dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = verify_exposure_run(args.run_dir)
    except (FileNotFoundError, ValueError) as exc:
        _write_json(
            sys.stderr,
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "status": "VERIFICATION_FAILED",
            },
        )
        return 1
    _write_json(
        sys.stdout,
        {
            "decision": manifest.decision,
            "run_id": manifest.run_id,
            "status": "VERIFIED",
        },
    )
    return 0


def _write_json(stream, payload: dict[str, object]) -> None:
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

