try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import subprocess
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
    FinQATypedCalibrationPublicEvidence,
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
DEFAULT_EVIDENCE = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_public_v1.json"
)
DEFAULT_RUN_ROOT = DEFAULT_PRIVATE_ROOT / "typed_contract_calibration_runs"
_FORBIDDEN_KEYS = {
    "case_id",
    "case_ids",
    "question",
    "answer",
    "answers",
    "evidence_text",
    "gold_program",
    "selected_candidate_ids",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify aggregate-only Gate E2 calibration evidence."
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument(
        "--skip-private-reproduction",
        action="store_true",
    )
    return parser


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _verify_historical_sources(
    evidence: FinQATypedCalibrationPublicEvidence,
) -> int:
    checked = 0
    for iteration in evidence.iterations:
        for path, expected in iteration.implementation_file_sha256.items():
            result = subprocess.run(
                [
                    "git",
                    "show",
                    f"{iteration.execution_code_revision}:{path}",
                ],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
            )
            if hashlib.sha256(result.stdout).hexdigest() != expected:
                raise ValueError(
                    f"historical implementation hash mismatch: {path}"
                )
            checked += 1
    return checked


def main() -> int:
    args = build_parser().parse_args()
    protocol = FinQATypedCalibrationProtocol.model_validate_json(
        args.protocol.read_bytes()
    )
    evidence_bytes = args.evidence.read_bytes()
    evidence = FinQATypedCalibrationPublicEvidence.model_validate_json(
        evidence_bytes
    )
    protocol_sha = hashlib.sha256(
        canonical_json_bytes(protocol.model_dump(mode="json"))
    ).hexdigest()
    if (
        evidence.protocol_id != protocol.protocol_id
        or evidence.protocol_sha256 != protocol_sha
        or evidence.calibration_case_ids_sha256
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("public calibration evidence does not match protocol")
    forbidden = sorted(set(_walk_keys(json.loads(evidence_bytes))) & _FORBIDDEN_KEYS)
    if forbidden:
        raise ValueError(
            "public calibration evidence contains forbidden raw fields: "
            + ",".join(forbidden)
        )
    historical_source_count = _verify_historical_sources(evidence)
    private_reproduced = False
    if not args.skip_private_reproduction:
        cases, _ = load_finqa_split(
            args.dataset,
            expected_sha256=FINQA_DEV_SHA256,
        )
        reproduced = build_public_calibration_evidence(
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
        reproduced_bytes = canonical_json_bytes(
            reproduced.model_dump(mode="json"),
            newline=True,
        )
        if reproduced_bytes != evidence_bytes:
            raise ValueError("public calibration evidence is not reproducible")
        private_reproduced = True
    print(
        json.dumps(
            {
                "status": "PASS",
                "decision": evidence.decision,
                "historical_source_files_verified": historical_source_count,
                "private_reproduction": private_reproduced,
                "forbidden_raw_fields": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
