from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.evaluation.quality_review import verify_quality_review_packet


DEFAULT_PACKET = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "v2"
    / "quality_review"
    / "r2-s8-calibration-v3"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a frozen quality-review packet and its claim boundary."
    )
    parser.add_argument("--packet-dir", type=Path, default=DEFAULT_PACKET)
    parser.add_argument(
        "--require-claim-status",
        choices=["NOT_RUN"],
        default="NOT_RUN",
    )
    parser.add_argument(
        "--require-population-kind",
        choices=[
            "public_synthetic",
            "licensed_public",
            "approved_deidentified",
            "private_holdout",
        ],
        default="public_synthetic",
    )
    parser.add_argument(
        "--require-independence-status",
        choices=["not_independent", "owner_attested"],
        default="not_independent",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = verify_quality_review_packet(args.packet_dir)
    if manifest.claim_status != args.require_claim_status:
        raise ValueError("quality review packet claim status changed")
    if manifest.source.population_kind != args.require_population_kind:
        raise ValueError("quality review packet population kind changed")
    if (
        manifest.source.independence_status
        != args.require_independence_status
    ):
        raise ValueError("quality review packet independence status changed")
    print(
        json.dumps(
            {
                "packet_id": manifest.packet_id,
                "item_count": manifest.item_count,
                "purpose": manifest.purpose,
                "claim_status": manifest.claim_status,
                "population_kind": manifest.source.population_kind,
                "independence_status": manifest.source.independence_status,
                "dataset_sha256": manifest.source.dataset_sha256,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
