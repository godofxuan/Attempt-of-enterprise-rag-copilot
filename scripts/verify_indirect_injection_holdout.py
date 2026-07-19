from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.evaluation.indirect_injection_holdout import (
    current_holdout_code_baseline,
    verify_holdout_submission,
)


BASE_DIR = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute a frozen local indirect-injection holdout package without "
            "network, retrieval, embedding, or model calls."
        )
    )
    parser.add_argument("submission_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    baseline = current_holdout_code_baseline(BASE_DIR)
    manifest = verify_holdout_submission(
        args.submission_dir,
        baseline=baseline,
    )
    manifest_path = args.submission_dir.resolve() / "freeze_manifest.json"
    receipt = {
        "verification": "VERIFIED",
        "state": manifest.state,
        "submission_id": manifest.submission_id,
        "holdout_id": manifest.holdout_id,
        "case_count": manifest.coverage.case_count,
        "case_identity_sha256": manifest.coverage.case_identity_sha256,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "git_head": manifest.code_baseline.git_head,
        "branch": manifest.code_baseline.branch,
    }
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
