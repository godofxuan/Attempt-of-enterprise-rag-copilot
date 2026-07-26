from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.lifecycle.validation import validate_lifecycle_repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate lifecycle evidence schemas and cross-file invariants."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--skip-public-audit",
        action="store_true",
        help="Skip the separate repository public-evidence audit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_lifecycle_repository(
            args.root,
            run_public_audit=not args.skip_public_audit,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": "lifecycle_evidence_validation_v1",
                    "status": "failed",
                    "error_code": "lifecycle_evidence_invalid",
                    "error_type": type(exc).__name__,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            report.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
