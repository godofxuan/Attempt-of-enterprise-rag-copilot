from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from scripts import _bootstrap  # noqa: F401

from app.lifecycle.performance_evidence import (
    verify_public_performance_evidence_package,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and independently recompute a public lifecycle "
            "performance evidence package."
        )
    )
    parser.add_argument("--package-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = verify_public_performance_evidence_package(
            args.package_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(
        f"verified {summary.completed_experiment_id}: "
        f"{summary.pair_count} pairs, {summary.final_status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
