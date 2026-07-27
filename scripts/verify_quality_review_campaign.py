from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.evaluation.quality_campaign import (
    verify_quality_review_campaign_readiness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a blank quality-review campaign readiness package."
    )
    parser.add_argument("--campaign-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = verify_quality_review_campaign_readiness(args.campaign_dir)
    print(
        json.dumps(
            {
                "campaign_id": manifest.campaign_id,
                "packet_id": manifest.packet_id,
                "reviewer_slots": list(manifest.reviewer_slots),
                "human_judgements_completed": (
                    manifest.human_judgements_completed
                ),
                "claim_status": manifest.claim_status,
                "status": manifest.status,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
