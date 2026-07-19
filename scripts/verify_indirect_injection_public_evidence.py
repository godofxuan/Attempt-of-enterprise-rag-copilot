from __future__ import annotations

import argparse
from pathlib import Path

from app.evaluation.indirect_injection_public_verifier import verify_package
from app.evaluation.indirect_injection_public_writer import FORMAL_D7_PACKAGE_NAME


BASE_DIR = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the redacted R2-S1 D7 public evidence package."
    )
    parser.add_argument(
        "package",
        nargs="?",
        type=Path,
        default=BASE_DIR / "data" / "v2" / "public" / FORMAL_D7_PACKAGE_NAME,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = verify_package(args.package)
    print(
        "VERIFIED "
        f"package={result.package_id} "
        f"source_run={result.source_run_id} "
        f"cases={result.case_pair_count} "
        f"rows={result.row_count} "
        f"metrics={result.metric_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
