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
from app.external_datasets.finqa_semantic_calibration_run import (
    FinQASemanticCalibrationManifest,
    FinQASemanticPlanningCase,
    publish_semantic_calibration_run,
    semantic_arm_order,
    summarize_semantic_calibration,
    verify_semantic_calibration_run,
)
from app.external_datasets.finqa_semantic_demos import (
    DEMO_RETRIEVER_VERSION,
    FINQA_TRAIN_SHA256,
    FinQAStructuralDemoIndex,
    load_finqa_demo_sources,
)
from app.external_datasets.finqa_semantic_planner import (
    PLANNER_VERSION,
    LocalFinQASemanticPlanner,
)
from app.external_datasets.finqa_semantic_planning_protocol import (
    load_semantic_planning_protocol,
)
from app.external_datasets.finqa_semantic_runtime import (
    evaluate_semantic_case,
)
from app.external_datasets.finqa_typed_calibration import case_ids_sha256
from app.external_datasets.finqa_typed_contract_v23 import (
    COMPILER_VERSION,
    VALIDATOR_VERSION,
)
from app.external_datasets.finqa_typed_retrospective import (
    FrozenModelIdentity,
)
from app.external_datasets.finqa_v23_calibration_run import (
    FinQAV23CalibrationCase,
    verify_v23_calibration_run,
)
from scripts.eval_finqa_typed_calibration_v2 import (
    _ollama_model_digest,
    _timed_chat,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_semantic_planning_calibration_protocol_v1.json"
)
DEFAULT_E4_PUBLIC = (
    REPOSITORY_ROOT
    / "docs"
    / "external_datasets"
    / "evidence"
    / "finqa_v23_paired_calibration_public_v1.json"
)
DEFAULT_E4_RUN = (
    DEFAULT_PRIVATE_ROOT
    / "v23_calibration_runs"
    / "finqa-v23-paired-calibration-v1"
)
DEFAULT_OUT_ROOT = DEFAULT_PRIVATE_ROOT / "semantic_planning_calibration_runs"
DEFAULT_CHECKPOINT_ROOT = (
    DEFAULT_PRIVATE_ROOT / "checkpoints" / "semantic_planning_calibration"
)
IMPLEMENTATION_FILES = (
    "app/external_datasets/finqa.py",
    "app/external_datasets/finqa_semantic_calibration_run.py",
    "app/external_datasets/finqa_semantic_demos.py",
    "app/external_datasets/finqa_semantic_planner.py",
    "app/external_datasets/finqa_semantic_program.py",
    "app/external_datasets/finqa_semantic_runtime.py",
    "scripts/eval_finqa_semantic_planning.py",
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


def _load_e4_rows(path: Path) -> list[FinQAV23CalibrationCase]:
    return [
        FinQAV23CalibrationCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen Gate E5 semantic planning calibration."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--e4-public", type=Path, default=DEFAULT_E4_PUBLIC)
    parser.add_argument("--e4-run", type=Path, default=DEFAULT_E4_RUN)
    parser.add_argument(
        "--development-dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "dev.json",
    )
    parser.add_argument(
        "--training-dataset",
        type=Path,
        default=DEFAULT_SOURCE_ROOT / "dataset" / "train.json",
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=DEFAULT_CHECKPOINT_ROOT,
    )
    parser.add_argument("--demo-isolation-suite-passed", action="store_true")
    parser.add_argument("--fail-closed-suite-passed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol, protocol_sha256 = load_semantic_planning_protocol(
        args.protocol
    )
    if _sha256(args.e4_public) != protocol.source_gate_e4_public_sha256:
        raise ValueError("Gate E4 public evidence does not match E5 protocol")
    e4_run = args.e4_run.resolve()
    e4_manifest = verify_v23_calibration_run(e4_run)
    if (
        e4_manifest.run_id != protocol.source_gate_e4_run_id
        or _sha256(e4_run / "manifest.json")
        != protocol.source_gate_e4_private_manifest_sha256
        or _sha256(e4_run / "details.jsonl")
        != protocol.source_gate_e4_private_details_sha256
    ):
        raise ValueError("sealed Gate E4 run does not match E5 protocol")
    rows = _load_e4_rows(e4_run / "details.jsonl")
    case_ids = [row.case_id for row in rows]
    if (
        len(rows) != protocol.calibration_case_count
        or case_ids_sha256(case_ids)
        != protocol.calibration_case_ids_sha256
    ):
        raise ValueError("Gate E5 calibration cohort does not match protocol")

    cases, dev_sha256 = load_finqa_split(
        args.development_dataset,
        expected_sha256=protocol.development_split_sha256,
    )
    if dev_sha256 != FINQA_DEV_SHA256:
        raise ValueError("Gate E5 development split is not pinned FinQA dev")
    cases_by_id = {case.id: case for case in cases}
    if set(case_ids) - set(cases_by_id):
        raise ValueError("Gate E5 cohort references an absent FinQA case")
    demo_sources, train_sha256 = load_finqa_demo_sources(
        args.training_dataset,
        expected_sha256=protocol.training_split_sha256,
    )
    if train_sha256 != FINQA_TRAIN_SHA256:
        raise ValueError("Gate E5 demo split is not pinned FinQA train")
    demo_index = FinQAStructuralDemoIndex(
        demo_sources,
        forbidden_case_ids=set(cases_by_id),
    )
    implementation_hashes = _implementation_hashes()
    dry_run = {
        "status": "DRY_RUN_OK",
        "case_count": len(case_ids),
        "case_ids_sha256": case_ids_sha256(case_ids),
        "protocol_sha256": protocol_sha256,
        "development_split_sha256": dev_sha256,
        "training_split_sha256": train_sha256,
        "demo_index_count": demo_index.demo_count,
        "demo_index_sha256": demo_index.identity_sha256,
        "demo_retriever_version": demo_index.version,
        "demo_isolation_suite_passed": args.demo_isolation_suite_passed,
        "fail_closed_regression_suite_passed": (
            args.fail_closed_suite_passed
        ),
        "model_calls": 0,
        "implementation_file_sha256": implementation_hashes,
    }
    if args.dry_run:
        print(json.dumps(dry_run, indent=2, sort_keys=True))
        return 0
    if not (
        args.demo_isolation_suite_passed
        and args.fail_closed_suite_passed
    ):
        raise ValueError(
            "live E5 calibration requires both frozen regression suites"
        )

    model_digest = _ollama_model_digest(protocol.answer_model_name)
    if model_digest != protocol.answer_model_sha256:
        raise ValueError("Ollama model digest does not match E5 protocol")
    planner = LocalFinQASemanticPlanner(
        model=protocol.answer_model_name,
        chat_fn=_timed_chat(protocol.timeout_seconds_per_call),
        max_attempts=protocol.max_attempts_per_stage,
    )
    checkpoint = ResumableCaseCheckpoint.open(
        root=args.checkpoint_root,
        run_id=args.run_id,
        contract={
            "kind": "finqa_semantic_planning_calibration_v1",
            "protocol_sha256": protocol_sha256,
            "source_gate_e4_manifest_sha256": (
                protocol.source_gate_e4_private_manifest_sha256
            ),
            "source_gate_e4_details_sha256": (
                protocol.source_gate_e4_private_details_sha256
            ),
            "development_split_sha256": dev_sha256,
            "training_split_sha256": train_sha256,
            "demo_index_sha256": demo_index.identity_sha256,
            "answer_model": {
                "name": protocol.answer_model_name,
                "sha256": model_digest,
            },
            "implementation_file_sha256": implementation_hashes,
            "planner_version": PLANNER_VERSION,
            "demo_retriever_version": DEMO_RETRIEVER_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "compiler_version": COMPILER_VERSION,
        },
        expected_case_ids=case_ids,
    )
    existing = checkpoint.load_rows(FinQASemanticPlanningCase)
    if existing:
        print(
            f"resuming after {len(existing)}/{len(case_ids)} cases",
            file=sys.stderr,
            flush=True,
        )

    def evaluate(index: int, source: FinQAV23CalibrationCase):
        print(
            f"[{index + 1}/{len(case_ids)}] Gate E5 semantic planning",
            file=sys.stderr,
            flush=True,
        )
        return evaluate_semantic_case(
            case=cases_by_id[source.case_id],
            source_e4=source,
            planner=planner,
            demo_index=demo_index,
            arm_order=semantic_arm_order(index),
            demo_count=protocol.dynamic_demo_count,
        )

    settings = get_settings()
    lock_root = Path(settings.runtime_cache_dir).resolve() / "evaluation_locks"
    with evaluation_lock(settings.llm_base_url, lock_root=lock_root):
        result_rows = run_resumable_cases(
            checkpoint=checkpoint,
            row_type=FinQASemanticPlanningCase,
            cases=rows,
            evaluate=evaluate,
        )
    summary = summarize_semantic_calibration(
        result_rows,
        protocol=protocol,
        demo_isolation_suite_passed=True,
        fail_closed_regression_suite_passed=True,
    )
    manifest = FinQASemanticCalibrationManifest(
        run_id=args.run_id,
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        source_gate_e4_manifest_sha256=(
            protocol.source_gate_e4_private_manifest_sha256
        ),
        source_gate_e4_details_sha256=(
            protocol.source_gate_e4_private_details_sha256
        ),
        selected_case_ids_sha256=case_ids_sha256(case_ids),
        development_split_sha256=dev_sha256,
        training_split_sha256=train_sha256,
        demo_index_sha256=demo_index.identity_sha256,
        demo_index_count=demo_index.demo_count,
        answer_model=FrozenModelIdentity(
            name=protocol.answer_model_name,
            sha256=model_digest,
        ),
        execution_code_revision=_git_head(),
        implementation_file_sha256=implementation_hashes,
        planner_version=PLANNER_VERSION,
        demo_retriever_version=DEMO_RETRIEVER_VERSION,
        validator_version=VALIDATOR_VERSION,
        compiler_version=COMPILER_VERSION,
        timeout_seconds_per_call=protocol.timeout_seconds_per_call,
        max_attempts_per_stage=protocol.max_attempts_per_stage,
        summary=summary,
    )
    output = publish_semantic_calibration_run(
        root=args.out_root,
        manifest=manifest,
        details=result_rows,
    )
    verified = verify_semantic_calibration_run(
        output,
        protocol=protocol,
        protocol_sha256=protocol_sha256,
    )
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
