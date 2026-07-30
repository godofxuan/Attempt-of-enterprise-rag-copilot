try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from app.config import get_settings
from app.evaluation.ollama_evaluation_lock import evaluation_lock
from app.evaluation.resumable_checkpoint import (
    ResumableCaseCheckpoint,
    run_resumable_cases,
)
from app.external_datasets.finqa import (
    DEFAULT_PRIVATE_ROOT,
    DEFAULT_SOURCE_ROOT,
    FINQA_DEV_SHA256,
    load_finqa_split,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_calibration_run import (
    FinQATypedCalibrationRunCase,
    verify_calibration_run,
)
from app.external_datasets.finqa_typed_planner_v23 import (
    PLANNER_VERSION,
    LocalFinQATypedProgramPlannerV23,
)
from app.external_datasets.finqa_typed_contract_v23 import (
    COMPILER_VERSION,
    VALIDATOR_VERSION,
)
from app.external_datasets.finqa_typed_retrospective import FrozenModelIdentity
from app.external_datasets.finqa_v23_calibration_protocol import (
    load_v23_calibration_protocol,
)
from app.external_datasets.finqa_v23_calibration_run import (
    FinQAV23CalibrationCase,
    FinQAV23CalibrationRunManifest,
    publish_v23_calibration_run,
    summarize_v23_calibration,
    verify_v23_calibration_run,
)
from app.external_datasets.finqa_v23_runtime import evaluate_v23_case
from scripts.eval_finqa_typed_calibration_v2 import (
    _ollama_model_digest,
    _timed_chat,
)
from scripts.verify_finqa_numeric_evidence_public import (
    verify_public_evidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_v23_paired_calibration_protocol_v1.json"
)
DEFAULT_E2_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_typed_contract_calibration_public_v1.json"
)
DEFAULT_E3_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_numeric_evidence_calibration_public_v1.json"
)
DEFAULT_E2_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "typed_contract_calibration_runs"
    / "finqa-typed-contract-v2-2-calibration-v1"
)
DEFAULT_E3_RUN_ROOT = DEFAULT_PRIVATE_ROOT / "numeric_evidence_audits"
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "v23_calibration_runs"
DEFAULT_CHECKPOINT_ROOT = (
    DEFAULT_PRIVATE_ROOT / "checkpoints" / "v23_calibration"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa_typed_contract_v23.py",
    "app/external_datasets/finqa_typed_planner_v23.py",
    "app/external_datasets/finqa_v23_calibration_run.py",
    "app/external_datasets/finqa_v23_runtime.py",
    "scripts/eval_finqa_v23_calibration.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.resolve().read_bytes()).hexdigest()


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


def _implementation_hashes() -> dict[str, str]:
    return {
        relative: _sha256(REPOSITORY_ROOT / relative)
        for relative in IMPLEMENTATION_FILES
    }


def _load_e2_rows(path: Path) -> list[FinQATypedCalibrationRunCase]:
    return [
        FinQATypedCalibrationRunCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Gate E4 v2.3 paired development calibration."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--e2-public", type=Path, default=DEFAULT_E2_PUBLIC)
    parser.add_argument("--e3-public", type=Path, default=DEFAULT_E3_PUBLIC)
    parser.add_argument("--e2-run", type=Path, default=DEFAULT_E2_RUN)
    parser.add_argument("--e3-run-root", type=Path, default=DEFAULT_E3_RUN_ROOT)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    parser.add_argument("--fail-closed-suite-passed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_v23_calibration_protocol(args.protocol)
    if _sha256(args.e2_public) != protocol.source_gate_e2_public_sha256:
        raise ValueError("Gate E2 public evidence does not match v2.3 protocol")
    if _sha256(args.e3_public) != protocol.source_gate_e3_public_sha256:
        raise ValueError("Gate E3 public evidence does not match v2.3 protocol")
    e3_summary = verify_public_evidence(
        args.e3_public,
        private_root=args.e3_run_root,
    )
    input_gate_passed = e3_summary.decision == "INPUT_GATE_PASSED"

    e2_run = args.e2_run.resolve()
    e2_manifest = verify_calibration_run(e2_run)
    if (
        e2_manifest.run_id != protocol.source_gate_e2_run_id
        or _sha256(e2_run / "details.jsonl")
        != protocol.source_gate_e2_private_details_sha256
    ):
        raise ValueError("sealed Gate E2 run does not match v2.3 protocol")
    e3_run = args.e3_run_root.resolve() / protocol.source_gate_e3_run_id
    if (
        _sha256(e3_run / "manifest.json")
        != protocol.source_gate_e3_private_manifest_sha256
        or _sha256(e3_run / "details.jsonl")
        != protocol.source_gate_e3_private_details_sha256
    ):
        raise ValueError("sealed Gate E3 run does not match v2.3 protocol")

    rows = _load_e2_rows(e2_run / "details.jsonl")
    case_ids = [row.case_id for row in rows]
    if (
        len(rows) != protocol.calibration_case_count
        or case_ids_sha256(case_ids) != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("v2.3 calibration cohort does not match protocol")
    cases, dataset_sha256 = load_finqa_split(
        args.dataset,
        expected_sha256=protocol.dataset_sha256,
    )
    if dataset_sha256 != FINQA_DEV_SHA256:
        raise ValueError("v2.3 dataset is not the pinned FinQA dev split")
    cases_by_id = {case.id: case for case in cases}
    if set(case_ids) - set(cases_by_id):
        raise ValueError("v2.3 cohort references an absent FinQA case")
    implementation_hashes = _implementation_hashes()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN_OK",
                    "case_count": len(case_ids),
                    "case_ids_sha256": case_ids_sha256(case_ids),
                    "protocol_sha256": protocol_sha256,
                    "input_gate_e3_passed": input_gate_passed,
                    "fail_closed_regression_suite_passed": (
                        args.fail_closed_suite_passed
                    ),
                    "model_calls": 0,
                    "implementation_file_sha256": implementation_hashes,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.fail_closed_suite_passed:
        raise ValueError(
            "live v2.3 calibration requires the fail-closed suite"
        )

    model_digest = _ollama_model_digest(protocol.answer_model_name)
    if model_digest != protocol.answer_model_sha256:
        raise ValueError("Ollama model digest does not match v2.3 protocol")
    planner = LocalFinQATypedProgramPlannerV23(
        model=protocol.answer_model_name,
        chat_fn=_timed_chat(protocol.timeout_seconds),
        max_attempts=protocol.max_attempts_per_case,
    )
    checkpoint = ResumableCaseCheckpoint.open(
        root=args.checkpoint_root,
        run_id=args.run_id,
        contract={
            "kind": "finqa_v23_paired_calibration_v1",
            "protocol_sha256": protocol_sha256,
            "source_gate_e2_details_sha256": (
                protocol.source_gate_e2_private_details_sha256
            ),
            "source_gate_e3_manifest_sha256": (
                protocol.source_gate_e3_private_manifest_sha256
            ),
            "answer_model": {
                "name": protocol.answer_model_name,
                "sha256": model_digest,
            },
            "implementation_file_sha256": implementation_hashes,
            "planner_version": PLANNER_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "compiler_version": COMPILER_VERSION,
        },
        expected_case_ids=case_ids,
    )
    existing = checkpoint.load_rows(FinQAV23CalibrationCase)
    if existing:
        print(
            f"resuming after {len(existing)}/{len(case_ids)} cases",
            file=sys.stderr,
            flush=True,
        )

    def evaluate(index: int, source: FinQATypedCalibrationRunCase):
        print(
            f"[{index + 1}/{len(case_ids)}] v2.3 calibration",
            file=sys.stderr,
            flush=True,
        )
        return evaluate_v23_case(
            case=cases_by_id[source.case_id],
            source=source,
            planner=planner,
        )

    settings = get_settings()
    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        result_rows = run_resumable_cases(
            checkpoint=checkpoint,
            row_type=FinQAV23CalibrationCase,
            cases=rows,
            evaluate=evaluate,
        )
    summary = summarize_v23_calibration(
        result_rows,
        protocol=protocol,
        input_gate_e3_passed=input_gate_passed,
        fail_closed_regression_suite_passed=True,
    )
    manifest = FinQAV23CalibrationRunManifest(
        run_id=args.run_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e2_details_sha256=(
            protocol.source_gate_e2_private_details_sha256
        ),
        source_gate_e3_manifest_sha256=(
            protocol.source_gate_e3_private_manifest_sha256
        ),
        selected_case_ids_sha256=case_ids_sha256(case_ids),
        answer_model=FrozenModelIdentity(
            name=protocol.answer_model_name,
            sha256=model_digest,
        ),
        execution_code_revision=_git_head(),
        implementation_file_sha256=implementation_hashes,
        planner_version=PLANNER_VERSION,
        validator_version=VALIDATOR_VERSION,
        compiler_version=COMPILER_VERSION,
        timeout_seconds=protocol.timeout_seconds,
        max_attempts=protocol.max_attempts_per_case,
        summary=summary,
    )
    output = publish_v23_calibration_run(
        root=args.out_root,
        manifest=manifest,
        details=result_rows,
    )
    verified = verify_v23_calibration_run(output)
    checkpoint.seal(
        final_manifest_sha256=_sha256(output / "manifest.json"),
        final_details_sha256=_sha256(output / "details.jsonl"),
    )
    print(
        json.dumps(
            {
                "run_id": verified.run_id,
                "output_dir": str(output),
                "summary": verified.summary.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
