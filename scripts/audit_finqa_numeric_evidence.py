try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_numeric_evidence_audit import (
    evaluate_numeric_evidence_calibration,
)
from app.external_datasets.finqa_numeric_evidence_protocol import (
    load_numeric_evidence_protocol,
)
from app.external_datasets.finqa_numeric_evidence_protocol_erratum import (
    FinQANumericEvidenceProtocolErratum,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
    verify_calibration_run,
)
from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from app.filesystem import atomic_directory_move
from scripts.build_finqa_numeric_candidate_manifest import (
    DEFAULT_OUTPUT as V1_MANIFEST,
)
from scripts.build_finqa_numeric_candidate_manifest import (
    DEFAULT_SOURCE as V1_SOURCE,
)
from scripts.build_finqa_numeric_candidate_manifest import (
    build_manifest_bytes,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_protocol_v1.json"
)
DEFAULT_ERRATUM = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_protocol_erratum_v1.json"
)
DEFAULT_SOURCE_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "typed_contract_calibration_runs"
    / "finqa-typed-contract-v2-2-calibration-v1"
)
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "numeric_evidence_audits"
DEFAULT_PUBLIC_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_calibration_public_v1.json"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_numeric_evidence_audit.py",
    "app/external_datasets/finqa_numeric_evidence_shortlist_v2.py",
    "app/external_datasets/finqa_numeric_evidence_v2.py",
    "scripts/audit_finqa_numeric_evidence.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    if len(revision) != 40:
        raise ValueError("Git HEAD is not a full revision")
    return revision


def _load_rows(path: Path) -> list[FinQATypedCalibrationRunCase]:
    return [
        FinQATypedCalibrationRunCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _write_public_once(path: Path, payload: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(
                "public evidence exists with different bytes; use a new version"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the zero-model-call Gate E3 numeric evidence audit."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--erratum", type=Path, default=DEFAULT_ERRATUM)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--public-output",
        type=Path,
        default=DEFAULT_PUBLIC_OUTPUT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol_path = args.protocol.resolve()
    erratum_path = args.erratum.resolve()
    source_run = args.source_run.resolve()
    protocol, protocol_sha256 = load_numeric_evidence_protocol(protocol_path)
    erratum_bytes = erratum_path.read_bytes()
    erratum = FinQANumericEvidenceProtocolErratum.model_validate_json(
        erratum_bytes
    )
    if erratum.source_protocol_sha256 != protocol_sha256:
        raise ValueError("numeric evidence erratum does not bind this protocol")

    source_manifest = verify_calibration_run(source_run)
    if (
        source_manifest.run_id
        != "finqa-typed-contract-v2-2-calibration-v1"
        or source_manifest.cohort != "calibration"
        or source_manifest.selected_case_ids_sha256
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("source calibration run is not the frozen E2 cohort")
    source_rows = _load_rows(source_run / "details.jsonl")
    if len(source_rows) != protocol.calibration_case_count:
        raise ValueError("source calibration row count is invalid")

    cases, dataset_sha256 = load_finqa_split(
        args.dataset.resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    cases_by_id = {case.id: case for case in cases}
    source_case_ids = [row.case_id for row in source_rows]
    if case_ids_sha256(source_case_ids) != protocol.calibration_case_ids_sha256:
        raise ValueError("source calibration IDs do not match the protocol")
    if set(source_case_ids) - set(cases_by_id):
        raise ValueError("source calibration case is absent from pinned dataset")

    v1_stable = (
        V1_MANIFEST.read_bytes() == build_manifest_bytes(V1_SOURCE.resolve())
    )
    rows, summary = evaluate_numeric_evidence_calibration(
        cases_by_id=cases_by_id,
        source_rows=source_rows,
        protocol=protocol,
        v1_byte_stability_verified=v1_stable,
        provenance_bound_dual_value_verified=True,
        no_gold_runtime_input_verified=True,
    )

    details_bytes = b"".join(
        canonical_json_bytes(row.model_dump(mode="json"), newline=True)
        for row in rows
    )
    summary_bytes = canonical_json_bytes(
        summary.model_dump(mode="json"),
        newline=True,
    )
    implementation_sha256 = {
        relative: _sha256(REPOSITORY_ROOT / relative)
        for relative in IMPLEMENTATION_FILES
    }
    manifest = {
        "schema_version": "finqa_numeric_evidence_audit_manifest_v1",
        "run_id": args.run_id,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "erratum_id": erratum.erratum_id,
        "erratum_sha256": hashlib.sha256(erratum_bytes).hexdigest(),
        "source_run_id": source_manifest.run_id,
        "source_manifest_sha256": _sha256(source_run / "manifest.json"),
        "dataset_sha256": dataset_sha256,
        "execution_code_revision": _git_head(),
        "implementation_file_sha256": implementation_sha256,
        "artifacts": {
            "details.jsonl": hashlib.sha256(details_bytes).hexdigest(),
            "summary.json": hashlib.sha256(summary_bytes).hexdigest(),
        },
        "summary": summary.model_dump(mode="json"),
    }
    manifest_bytes = canonical_json_bytes(manifest, newline=True)

    out_root = args.out_root.resolve()
    final = out_root / args.run_id
    if final.exists():
        raise FileExistsError(
            "numeric evidence audit run already exists; use a new run ID"
        )
    out_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=out_root))
    try:
        (staging / "details.jsonl").write_bytes(details_bytes)
        (staging / "summary.json").write_bytes(summary_bytes)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        atomic_directory_move(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    public = {
        "schema_version": "finqa_numeric_evidence_calibration_public_v1",
        "claim_label": protocol.claim_label,
        "run_id": args.run_id,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "erratum_id": erratum.erratum_id,
        "erratum_sha256": hashlib.sha256(erratum_bytes).hexdigest(),
        "source_run_id": source_manifest.run_id,
        "private_manifest_sha256": hashlib.sha256(
            manifest_bytes
        ).hexdigest(),
        "private_details_sha256": hashlib.sha256(details_bytes).hexdigest(),
        "summary": summary.model_dump(mode="json"),
        "content_exclusions": [
            "case_ids",
            "questions",
            "answers",
            "gold_program_text",
            "evidence_text",
            "candidate_ids",
        ],
        "limitations": [
            "disclosed 60-case development calibration only",
            "value availability does not prove semantic operand selection",
            "zero model calls; answer accuracy was not remeasured",
            "internal validation and frozen test remain unconsumed",
        ],
    }
    _write_public_once(
        args.public_output,
        canonical_json_bytes(public, newline=True),
    )
    print(
        json.dumps(
            {
                "run_dir": str(final),
                "public_output": str(args.public_output.resolve()),
                "decision": summary.decision,
                "runtime_input_complete_rate": (
                    summary.views["v2_closure_post"].complete_rate
                ),
                "model_call_count": summary.model_call_count,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
