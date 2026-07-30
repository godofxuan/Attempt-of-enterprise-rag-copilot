from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_typed_calibration import (
    DEFAULT_SPLIT_SEED,
    CalibrationAdoptionGates,
    FinQATypedCalibrationProtocol,
    build_failure_matrix,
    case_ids_sha256,
    stratified_calibration_split,
)
from app.external_datasets.finqa_typed_retrospective import (
    FinQATypedRetrospectiveCase,
    canonical_json_bytes,
    verify_typed_retrospective_run,
)


DEFAULT_RUN_DIR = (
    Path(".private")
    / "external_datasets"
    / "finqa"
    / "typed_retrospective_runs"
    / "finqa-typed-retrospective-dev-v1"
)
DEFAULT_PROTOCOL_PATH = (
    Path("docs")
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_protocol_v1.json"
)
DEFAULT_EVIDENCE_PATH = (
    Path("docs")
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_failure_matrix_v1.json"
)
DEFAULT_PRIVATE_SPLIT_PATH = (
    Path(".private")
    / "external_datasets"
    / "finqa"
    / "typed_contract_calibration"
    / "gate-e2-v1"
    / "split.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the disclosed-development typed-contract calibration split."
        )
    )
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--protocol-out", type=Path, default=DEFAULT_PROTOCOL_PATH)
    parser.add_argument("--evidence-out", type=Path, default=DEFAULT_EVIDENCE_PATH)
    parser.add_argument(
        "--private-split-out",
        type=Path,
        default=DEFAULT_PRIVATE_SPLIT_PATH,
    )
    parser.add_argument(
        "--implementation-base-revision",
        required=True,
        help="The 40-character Gate E closeout revision.",
    )
    parser.add_argument("--seed", default=DEFAULT_SPLIT_SEED)
    return parser.parse_args()


def _load_rows(path: Path) -> list[FinQATypedRetrospectiveCase]:
    return [
        FinQATypedRetrospectiveCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def main() -> None:
    args = _parse_args()
    run_dir = args.run_dir.resolve()
    manifest = verify_typed_retrospective_run(run_dir)
    rows = _load_rows(run_dir / "details.jsonl")
    calibration, validation, strata = stratified_calibration_split(
        rows,
        seed=args.seed,
    )
    cases, _ = load_finqa_split(
        args.dataset,
        expected_sha256=FINQA_DEV_SHA256,
    )
    source_case_ids = {row.case_id for row in rows}
    gold_programs = {
        case.id: case.qa.program
        for case in cases
        if case.id in source_case_ids
    }
    protocol = FinQATypedCalibrationProtocol(
        status="FROZEN_BEFORE_V2_IMPLEMENTATION",
        protocol_id="finqa-typed-contract-calibration-gate-e2-v1",
        implementation_base_revision=args.implementation_base_revision,
        source_gate_e_run_id=manifest.run_id,
        source_gate_e_manifest_sha256=hashlib.sha256(
            (run_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        source_gate_e_details_sha256=hashlib.sha256(
            (run_dir / "details.jsonl").read_bytes()
        ).hexdigest(),
        source_selected_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in rows]
        ),
        split_seed=args.seed,
        validation_fraction=0.4,
        stratification_fields=(
            "diagnostic_category",
            "b1_v1_outcome",
        ),
        calibration_case_count=len(calibration),
        internal_validation_case_count=len(validation),
        calibration_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in calibration]
        ),
        internal_validation_case_ids_sha256=case_ids_sha256(
            [row.case_id for row in validation]
        ),
        strata=strata,
        adoption_gates=CalibrationAdoptionGates(
            min_coverage=0.5,
            min_execution_accuracy_delta_vs_b0=-0.05,
            min_grounded_accuracy_delta_vs_b0=-0.05,
            max_correct_to_wrong_rate=0.05,
            min_wrong_to_correct_count=1,
            min_prevented_operand_failure_count=1,
            max_protocol_error_rate=0.1,
            max_latency_mean_multiplier=15,
            max_latency_p95_ms=40_000,
        ),
        immutable_safety_invariants=(
            "candidate references remain allowlisted and provenance-bound",
            "numeric literals remain forbidden in model-generated programs",
            "known unit, period, metric, entity, and sign conflicts fail closed",
            "division by zero and Decimal magnitude overflow fail closed",
            "unknown metadata may be relaxed only by explicit v2 policy",
            "v1 runtime behavior and evidence remain immutable",
        ),
        non_claims=(
            "not a held-out or confirmatory result",
            "not a frozen-test result",
            "not evidence that typed planning is production-ready",
            "gold programs are offline diagnostic labels, never runtime inputs",
        ),
    )
    matrix = build_failure_matrix(
        rows=rows,
        gold_program_by_case_id=gold_programs,
        calibration_rows=calibration,
        validation_rows=validation,
        protocol=protocol,
    )
    private_split = {
        "schema_version": "finqa_typed_contract_private_split_v1",
        "protocol_id": protocol.protocol_id,
        "source_gate_e_details_sha256": (
            protocol.source_gate_e_details_sha256
        ),
        "calibration_case_ids": [row.case_id for row in calibration],
        "internal_validation_case_ids": [row.case_id for row in validation],
    }
    for path, payload in (
        (args.protocol_out, protocol.model_dump(mode="json")),
        (args.evidence_out, matrix.model_dump(mode="json")),
        (args.private_split_out, private_split),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(payload, newline=True))
    print(
        json.dumps(
            {
                "protocol": str(args.protocol_out.resolve()),
                "evidence": str(args.evidence_out.resolve()),
                "private_split": str(args.private_split_out.resolve()),
                "calibration_count": len(calibration),
                "internal_validation_count": len(validation),
                "protocol_sha256": matrix.protocol_sha256,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
