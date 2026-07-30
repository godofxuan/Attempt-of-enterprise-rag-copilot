try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_semantic_planning_protocol import (
    load_semantic_planning_protocol,
)
from app.external_datasets.finqa_semantic_public import (
    build_semantic_public_evidence,
)
from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_protocol_v1.json"
)
DEFAULT_RUN_ROOT = (
    DEFAULT_PRIVATE_ROOT / "semantic_planning_calibration_runs"
)
DEFAULT_RUN_ID = "finqa-semantic-planning-calibration-v1"
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_public_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate-only FinQA Gate E5 evidence."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output.exists():
        raise FileExistsError(
            "Gate E5 public evidence exists; use a new version"
        )
    protocol, protocol_sha256 = load_semantic_planning_protocol(
        args.protocol
    )
    cases, _ = load_finqa_split(
        args.dataset,
        expected_sha256=FINQA_DEV_SHA256,
    )
    evidence = build_semantic_public_evidence(
        run_dir=args.run_root / args.run_id,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
        cases_by_id={case.id: case for case in cases},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        canonical_json_bytes(
            evidence.model_dump(mode="json"),
            newline=True,
        )
    )
    print(
        json.dumps(
            {
                "decision": evidence.summary.decision,
                "diagnostics": evidence.diagnostics.model_dump(mode="json"),
                "output": str(args.output.resolve()),
                "run_id": evidence.run_id,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
