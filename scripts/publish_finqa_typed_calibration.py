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
from app.external_datasets.finqa_typed_calibration import (
    FinQATypedCalibrationProtocol,
)
from app.external_datasets.finqa_typed_calibration_public import (
    build_public_calibration_evidence,
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
    / "finqa_typed_contract_calibration_protocol_v1.json"
)
DEFAULT_RUN_ROOT = DEFAULT_PRIVATE_ROOT / "typed_contract_calibration_runs"
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_public_v1.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish aggregate-only Gate E2 calibration evidence."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    protocol = FinQATypedCalibrationProtocol.model_validate_json(
        args.protocol.read_bytes()
    )
    cases, _ = load_finqa_split(
        args.dataset,
        expected_sha256=FINQA_DEV_SHA256,
    )
    evidence = build_public_calibration_evidence(
        protocol=protocol,
        run_dirs={
            "v2": (
                args.run_root / "finqa-typed-contract-v2-calibration-v1"
            ),
            "v2_1": (
                args.run_root / "finqa-typed-contract-v2-1-calibration-v1"
            ),
            "v2_2": (
                args.run_root / "finqa-typed-contract-v2-2-calibration-v1"
            ),
        },
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
                "output": str(args.output.resolve()),
                "decision": evidence.decision,
                "best_iteration": evidence.best_iteration,
                "internal_validation_status": (
                    evidence.internal_validation_status
                ),
                "multi_program_status": evidence.multi_program_status,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
