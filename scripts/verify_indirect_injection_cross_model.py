from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.evaluation.indirect_injection_cross_model_writer import (
    load_verified_cross_model_run_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify one private R2-S4 cross-model matrix package."
    )
    parser.add_argument("run_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    snapshot = load_verified_cross_model_run_snapshot(args.run_dir)
    print(
        json.dumps(
            {
                "matrix_run_id": snapshot.manifest.matrix_run_id,
                "decision": snapshot.manifest.decision,
                "row_count": len(snapshot.rows),
                "manifest_sha256": snapshot.manifest_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
