try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import subprocess
from pathlib import Path

from app.evaluation.garak_latent_report import (
    GARAK_REVISION,
    build_garak_latent_report_fixture,
    build_garak_latent_report_holdout_fixture,
)


DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "external_benchmarks"
    / "garak_latent_report_v1.json"
)
DEFAULT_HOLDOUT_OUT = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "external_benchmarks"
    / "garak_latent_report_holdout_v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the pinned NVIDIA garak latent-report fixture."
    )
    parser.add_argument("--garak-root", type=Path, required=True)
    parser.add_argument(
        "--variant",
        choices=("development", "holdout"),
        default="development",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    root = args.garak_root.resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != GARAK_REVISION:
        raise ValueError(f"garak revision mismatch: {revision}")
    builder = (
        build_garak_latent_report_holdout_fixture
        if args.variant == "holdout"
        else build_garak_latent_report_fixture
    )
    fixture = builder(
        probe_source=(root / "garak/probes/latentinjection.py").read_bytes(),
        payload_source=(
            root / "garak/data/payloads/domains_latentinjection.json"
        ).read_bytes(),
    )
    output = (args.out or (
        DEFAULT_HOLDOUT_OUT if args.variant == "holdout" else DEFAULT_OUT
    )).resolve()
    if output.exists():
        raise FileExistsError(f"garak fixture already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            fixture.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "attack_case_count": fixture.attack_case_count,
                "benign_case_count": fixture.benign_case_count,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
