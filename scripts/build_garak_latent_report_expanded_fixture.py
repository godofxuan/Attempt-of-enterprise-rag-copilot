from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.evaluation.garak_latent_report import (
    GarakLatentReportFixture,
    build_garak_latent_report_expanded_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEVELOPMENT = (
    ROOT / "data" / "external_benchmarks" / "garak_latent_report_v1.json"
)
DEFAULT_HOLDOUT = (
    ROOT / "data" / "external_benchmarks" / "garak_latent_report_holdout_v1.json"
)
DEFAULT_OUT = (
    ROOT / "data" / "external_benchmarks" / "garak_latent_report_expanded_v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic expanded garak report stress fixture."
    )
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    parser.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    development_bytes = args.development.resolve().read_bytes()
    holdout_bytes = args.holdout.resolve().read_bytes()
    fixture = build_garak_latent_report_expanded_fixture(
        development=GarakLatentReportFixture.model_validate_json(development_bytes),
        holdout=GarakLatentReportFixture.model_validate_json(holdout_bytes),
    )
    output = args.out.resolve()
    if output.exists():
        raise FileExistsError(f"garak expanded fixture already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(
            fixture.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    output.write_bytes(content)
    print(
        json.dumps(
            {
                "output": str(output),
                "development_sha256": hashlib.sha256(development_bytes).hexdigest(),
                "holdout_sha256": hashlib.sha256(holdout_bytes).hexdigest(),
                "fixture_sha256": hashlib.sha256(content).hexdigest(),
                "attack_case_count": fixture.attack_case_count,
                "benign_case_count": fixture.benign_case_count,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
