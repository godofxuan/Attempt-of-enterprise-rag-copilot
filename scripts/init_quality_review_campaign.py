from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.evaluation.quality_campaign import (
    initialize_quality_review_campaign,
    validate_quality_review_campaign_owner_context,
    verify_quality_review_campaign_readiness,
)


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PACKET_DIR = (
    BASE_DIR / "data" / "v2" / "quality_review" / "r2-s8-calibration-v4"
)
DEFAULT_OUT_ROOT = BASE_DIR / ".private" / "quality" / "campaigns"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Initialize a private, immutable two-human quality-review "
            "campaign without creating any review labels."
        )
    )
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--packet-dir", type=Path, default=DEFAULT_PACKET_DIR)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    validate_quality_review_campaign_owner_context()
    campaign_dir = initialize_quality_review_campaign(
        packet_dir=args.packet_dir,
        out_root=args.out_root,
        campaign_id=args.campaign_id,
    )
    manifest = verify_quality_review_campaign_readiness(campaign_dir)
    print(
        json.dumps(
            {
                "campaign_id": manifest.campaign_id,
                "campaign_dir": str(campaign_dir),
                "packet_id": manifest.packet_id,
                "reviewer_slots": list(manifest.reviewer_slots),
                "reviewer_identity_domain_sha256": (
                    manifest.reviewer_identity_domain_sha256
                ),
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
