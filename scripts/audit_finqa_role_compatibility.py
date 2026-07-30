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
from app.external_datasets.finqa_role_compatibility_audit import (
    evaluate_role_compatibility_calibration,
)
from app.external_datasets.finqa_role_compatibility_protocol import (
    load_role_compatibility_protocol,
)
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticPlanningCase,
    verify_semantic_calibration_run,
)
from app.external_datasets.finqa_semantic_planning_protocol import (
    load_semantic_planning_protocol,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_retrospective import (
    canonical_json_bytes,
)
from app.filesystem import atomic_directory_move


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_protocol_v1.json"
)
DEFAULT_E5_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_protocol_v1.json"
)
DEFAULT_E5_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_public_v1.json"
)
DEFAULT_SOURCE_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "semantic_planning_calibration_runs"
    / "finqa-semantic-planning-calibration-v1"
)
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "role_compatibility_audits"
DEFAULT_PUBLIC_OUTPUT = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_role_compatibility_calibration_public_v1.json"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_role_compatibility.py",
    "app/external_datasets/finqa_role_compatibility_audit.py",
    "app/external_datasets/finqa_role_compatibility_protocol.py",
    "scripts/audit_finqa_role_compatibility.py",
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


def _load_source_rows(path: Path) -> tuple[FinQASemanticPlanningCase, ...]:
    return tuple(
        FinQASemanticPlanningCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    )


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
        description=(
            "Run the zero-model-call Gate E6 role compatibility input audit."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--e5-protocol", type=Path, default=DEFAULT_E5_PROTOCOL)
    parser.add_argument("--e5-public", type=Path, default=DEFAULT_E5_PUBLIC)
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
    protocol, protocol_sha256 = load_role_compatibility_protocol(protocol_path)
    e5_protocol_path = args.e5_protocol.resolve()
    e5_protocol, e5_protocol_sha256 = load_semantic_planning_protocol(
        e5_protocol_path
    )
    if (
        e5_protocol_sha256 != protocol.source_gate_e5_protocol_sha256
        or _sha256(args.e5_public.resolve())
        != protocol.source_gate_e5_public_sha256
    ):
        raise ValueError("Gate E6 protocol does not bind current Gate E5 evidence")

    source_run = args.source_run.resolve()
    source_manifest = verify_semantic_calibration_run(
        source_run,
        protocol=e5_protocol,
        protocol_sha256=e5_protocol_sha256,
    )
    if (
        source_manifest.run_id != protocol.source_gate_e5_run_id
        or _sha256(source_run / "manifest.json")
        != protocol.source_gate_e5_private_manifest_sha256
        or _sha256(source_run / "details.jsonl")
        != protocol.source_gate_e5_private_details_sha256
    ):
        raise ValueError("Gate E6 source run does not match frozen Gate E5")
    source_rows = _load_source_rows(source_run / "details.jsonl")
    if (
        len(source_rows) != protocol.calibration_case_count
        or case_ids_sha256([item.case_id for item in source_rows])
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("Gate E6 source cohort does not match protocol")

    cases, dataset_sha256 = load_finqa_split(
        args.dataset.resolve(),
        expected_sha256=FINQA_DEV_SHA256,
    )
    if dataset_sha256 != protocol.development_split_sha256:
        raise ValueError("Gate E6 dataset does not match protocol")
    cases_by_id = {case.id: case for case in cases}
    if set(item.case_id for item in source_rows) - set(cases_by_id):
        raise ValueError("Gate E6 source case is absent from pinned dataset")

    rows, summary = evaluate_role_compatibility_calibration(
        cases_by_id=cases_by_id,
        source_rows=source_rows,
        protocol=protocol,
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
        "schema_version": "finqa_role_compatibility_audit_manifest_v1",
        "run_id": args.run_id,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "source_gate_e5_run_id": source_manifest.run_id,
        "source_gate_e5_manifest_sha256": _sha256(
            source_run / "manifest.json"
        ),
        "source_gate_e5_details_sha256": _sha256(
            source_run / "details.jsonl"
        ),
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
            "role compatibility audit exists; use a new run ID"
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
        "schema_version": "finqa_role_compatibility_calibration_public_v1",
        "claim_label": protocol.claim_label,
        "run_id": args.run_id,
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol_sha256,
        "source_gate_e5_run_id": source_manifest.run_id,
        "source_gate_e5_public_sha256": protocol.source_gate_e5_public_sha256,
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
            "gold_role_values",
            "evidence_text",
            "candidate_ids",
            "compatibility_matrix_rows",
        ],
        "limitations": [
            "disclosed 60-case development calibration only",
            "oracle gold-derived skeletons isolate binding-input recall",
            "zero model calls; answer accuracy was not remeasured",
            "value recall does not prove semantic binding correctness",
            "internal validation and frozen test remain unconsumed",
        ],
        "next_action": (
            "RUN_GATE_E6_LIVE_ABLATION"
            if summary.decision == "INPUT_GATE_PASSED"
            else "REVISE_ROLE_COMPATIBILITY_BEFORE_MODEL_CALLS"
        ),
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
                "gold_role_recall_at_4": summary.gold_role_recall_at_4,
                "gold_role_recall_at_8": summary.gold_role_recall_at_8,
                "complete_case_rate_at_8": (
                    summary.complete_case_rate_at_8
                ),
                "role_candidate_edge_reduction_rate": (
                    summary.role_candidate_edge_reduction_rate
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
