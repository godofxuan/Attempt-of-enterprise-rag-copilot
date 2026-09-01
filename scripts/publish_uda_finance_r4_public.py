from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

from app.external_datasets.uda_finance_r4 import R4_PRIVATE_ROOT
from app.external_datasets.uda_finance_r4_eval import verify_r4_campaign
from app.external_datasets.uda_finance_r4_public import (
    build_r4_public_evidence,
    canonical_json_bytes,
    verify_r4_public_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish aggregate-only UDA R4 evidence.")
    parser.add_argument("--development-run-id", required=True)
    parser.add_argument("--validation-run-id", required=True)
    parser.add_argument(
        "--private-root",
        type=Path,
        default=R4_PRIVATE_ROOT / "page_eval_runs",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("docs/r4/evidence/uda_finance_r4_protocol_v3.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/r4/evidence/uda_finance_r4_public_v1.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.private_root.resolve()
    development_dir = root / args.development_run_id
    validation_dir = root / args.validation_run_id
    development = verify_r4_campaign(development_dir)
    validation = verify_r4_campaign(validation_dir)
    evidence = build_r4_public_evidence(
        development=development,
        development_manifest_sha256=_sha256(development_dir / "manifest.json"),
        validation=validation,
        validation_manifest_sha256=_sha256(validation_dir / "manifest.json"),
        repository_revision=development.code_revision,
    )
    content = canonical_json_bytes(evidence)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_bytes() != content:
        raise FileExistsError("refusing to overwrite different R4 public evidence")
    output.write_bytes(content)
    verify_r4_public_evidence(output, protocol_path=args.protocol)
    print(f"{output} sha256={hashlib.sha256(content).hexdigest()}")
    return 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
