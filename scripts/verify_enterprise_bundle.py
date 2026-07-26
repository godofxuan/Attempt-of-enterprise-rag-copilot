from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.lifecycle.enterprise_bundle import (
    EnterpriseBundleError,
    load_enterprise_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a fictional enterprise lifecycle bundle offline."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/enterprise_bundle"),
        help="Bundle root containing manifest.json and sources/.",
    )
    return parser


def _emit(payload: object) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = load_enterprise_bundle(args.root)
    except EnterpriseBundleError as exc:
        _emit(
            {
                "schema_version": "enterprise_bundle_verification_v1",
                "status": "FAILED",
                "error": {"code": exc.code},
            }
        )
        return 2

    manifest = bundle.manifest
    domains = sorted({asset.domain for asset in manifest.assets})
    _emit(
        {
            "schema_version": "enterprise_bundle_verification_v1",
            "status": "VERIFIED",
            "bundle_id": manifest.bundle_id,
            "manifest_sha256": bundle.manifest_sha256,
            "synthetic": manifest.synthetic,
            "identity_policy": manifest.identity_policy,
            "asset_count": len(manifest.assets),
            "asset_byte_count": sum(
                asset.byte_count for asset in manifest.assets
            ),
            "event_count": len(manifest.events),
            "initial_event_count": sum(
                event.batch == "initial" for event in manifest.events
            ),
            "change_event_count": sum(
                event.batch == "change" for event in manifest.events
            ),
            "query_count": len(manifest.fixed_queries),
            "domains": domains,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
