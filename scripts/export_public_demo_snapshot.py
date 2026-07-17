from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from app.evaluation.public_snapshot import export_public_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a sanitized, hash-traceable public demo snapshot."
    )
    parser.add_argument("--deterministic-run", required=True, type=Path)
    parser.add_argument("--live-run", required=True, type=Path)
    parser.add_argument("--ablation-run", required=True, type=Path)
    parser.add_argument("--load-run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = export_public_snapshot(
        deterministic_run=args.deterministic_run,
        live_run=args.live_run,
        ablation_run=args.ablation_run,
        load_run=args.load_run,
        output=args.output,
    )
    print(f"public snapshot written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
