from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from scripts import _bootstrap  # noqa: F401

from app.indexing.paired_performance import (
    PairedArmMeasurement,
    PairedMeasurement,
    decision_protocol_from_experiment_thresholds,
    frozen_decision_protocol,
    summarize_paired_measurements,
)
from app.ingestion.normalize import ingest_corpus
from app.ingestion.revision_catalog import revision_catalog_sha256
from app.ingestion.versions import govern_documents
from app.lifecycle.evidence import (
    ExperimentRecord,
    ExperimentFinalStatus,
    ExperimentStatus,
    append_jsonl_record,
    load_jsonl_records,
    validate_experiment_history,
)
from app.lifecycle.performance_bundle import (
    LoadedPerformanceBundle,
    generate_performance_bundle,
    load_performance_bundle,
)
from app.lifecycle.performance_runner import (
    PerformanceRunnerError,
    clone_arm_workspace,
    host_identity_sha256,
    measure_performance_arm,
    prepare_arm_workspace,
    runner_environment_identity,
    runner_configuration_sha256,
)


BASE_DIR = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = (BASE_DIR / ".private" / "lifecycle").resolve()
ARTIFACT_ROOT = (BASE_DIR / "artifacts" / "lifecycle").resolve()
EXPERIMENTS_PATH = BASE_DIR / "docs" / "lifecycle" / "EXPERIMENTS.jsonl"
SOURCE_CORPUS = BASE_DIR / "data" / "v2" / "generated" / "expanded_benchmark"
_SAFE_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_INGESTED_AT = datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc)
_DATASET_ID = "expanded_benchmark_lifecycle_v4"
_CORRECTNESS_FAILURE_MESSAGES = {
    "paired target correctness fingerprints differ",
    "paired target retains deleted active-index state",
}
_CORRECTNESS_RUNNER_CODES = {
    "acl_query_leak",
    "deleted_query_residual",
    "expected_query_miss",
}


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _source_commit_sha(*, require_clean_runner: bool = False) -> str:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = completed.stdout.strip()
    if (
        completed.returncode != 0
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise RuntimeError("benchmark source commit is unavailable")
    if require_clean_runner:
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "app",
                "scripts/benchmark_lifecycle_incremental.py",
                "requirements.txt",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            raise RuntimeError(
                "benchmark runner sources differ from the source commit"
            )
    return commit


def _pretty_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_run_id(value: str) -> str:
    stem = value.split(".", 1)[0].upper()
    if (
        _SAFE_RUN_ID.fullmatch(value) is None
        or stem in _WINDOWS_RESERVED
        or value.endswith((".", " "))
    ):
        raise ValueError("benchmark run ID is unsafe")
    return value


def _validate_pair_number(value: int) -> int:
    if value < 1 or value > 10:
        raise ValueError("G10 pair number must be between 1 and 10")
    return value


def _confined_existing_directory(path: Path, root: Path, label: str) -> Path:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError(f"{label} must remain below {root.name}")
    if not resolved.is_dir():
        raise ValueError(f"{label} is not a directory")
    return resolved


def _confined_new_path(path: Path, root: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError(f"{label} must remain below {root.name}")
    return resolved


def _write_exclusive(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags, 0o600)
    try:
        written = os.write(descriptor, content)
        if written != len(content):
            raise OSError("short benchmark artifact write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_exclusive(path: Path, payload: object) -> None:
    _write_exclusive(path, _pretty_json_bytes(payload))


def _write_json_replace(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(f"temporary status file exists: {temporary}")
    temporary.write_bytes(_pretty_json_bytes(payload))
    os.replace(temporary, path)


def _public_command(arguments: list[str]) -> str:
    normalized: list[str] = []
    executable = Path(sys.executable).resolve()
    for argument in arguments:
        candidate = Path(argument)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if resolved == executable:
                normalized.append("python")
                continue
            try:
                relative = resolved.relative_to(BASE_DIR)
            except ValueError:
                normalized.append("<external-path>")
            else:
                normalized.append(relative.as_posix())
            continue
        normalized.append(argument)
    return subprocess.list2cmdline(normalized)


def _file_binding(bundle, name: str) -> tuple[str, int]:
    item = next(
        (
            item
            for item in bundle.manifest.files
            if item.path == name
        ),
        None,
    )
    if item is None:
        raise ValueError(f"bundle manifest does not bind {name}")
    return item.sha256, item.byte_count


def _bundle_summary(bundle) -> dict[str, object]:
    source_manifest = SOURCE_CORPUS / "manifest.json"
    source_manifest_sha256 = _sha256(source_manifest.read_bytes())
    return {
        "schema_version": "g10_bundle_freeze_summary_v3",
        "dataset_id": _DATASET_ID,
        "source_profile_id": "expanded_benchmark",
        "source_manifest_sha256": source_manifest_sha256,
        "bundle_manifest_sha256": bundle.manifest_sha256,
        "base_catalog_sha256": revision_catalog_sha256(
            bundle.base_catalog
        ),
        "target_catalog_sha256": revision_catalog_sha256(
            bundle.target_catalog
        ),
        "change_descriptor_sha256": _file_binding(
            bundle, "change_descriptor.json"
        )[0],
        "query_descriptor_sha256": _file_binding(
            bundle, "query_descriptor.json"
        )[0],
        "counts": bundle.manifest.counts.model_dump(mode="json"),
    }


def _freeze(args: argparse.Namespace) -> int:
    output = _confined_new_path(args.output_dir, PRIVATE_ROOT, "bundle output")
    if output.exists():
        raise FileExistsError("performance bundle output already exists")
    governed = govern_documents(
        ingest_corpus(SOURCE_CORPUS, ingested_at=_INGESTED_AT)
    )
    if len(governed.documents) != 1225:
        raise RuntimeError(
            "expanded_benchmark no longer produces 1225 canonical documents"
        )
    bundle = generate_performance_bundle(
        governed.documents,
        output,
    )
    summary = _bundle_summary(bundle)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


def _inspect(args: argparse.Namespace) -> int:
    bundle_root = _confined_existing_directory(
        args.bundle_dir,
        PRIVATE_ROOT,
        "bundle directory",
    )
    bundle = load_performance_bundle(bundle_root)
    print(
        json.dumps(
            _bundle_summary(bundle),
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


def _arm_worker(args: argparse.Namespace) -> int:
    pair_number = _validate_pair_number(args.pair_number)
    bundle_root = _confined_existing_directory(
        args.bundle_dir,
        PRIVATE_ROOT,
        "bundle directory",
    )
    workspace = _confined_existing_directory(
        args.workspace,
        PRIVATE_ROOT,
        "arm workspace",
    )
    result_file = _confined_new_path(
        args.result_file,
        ARTIFACT_ROOT,
        "arm result",
    )
    if result_file.exists():
        raise FileExistsError("arm result already exists")
    if (
        result_file.name != f"{args.arm}.json"
        or result_file.parent.name != f"{pair_number:03d}"
        or workspace.name != args.arm
        or workspace.parent.name != f"pair-{pair_number:03d}"
    ):
        raise ValueError("arm worker paths do not match its frozen pair identity")
    try:
        measurement = measure_performance_arm(
            bundle_root=bundle_root,
            expected_bundle_manifest_sha256=args.bundle_sha256,
            workspace_root=workspace,
            experiment_id=args.experiment_id,
            pair_number=pair_number,
            arm=args.arm,
            execution_order=args.execution_order,
            coordinator_process_id=args.coordinator_process_id,
            expected_host_identity_sha256=args.host_sha256,
            expected_configuration_sha256=args.configuration_sha256,
        )
    except PerformanceRunnerError as exc:
        _write_json_exclusive(
            result_file.with_name(f"{args.arm}-failure.json"),
            {
                "schema_version": "g10_arm_failure_v1",
                "failure_kind": (
                    "correctness_mismatch"
                    if exc.code in _CORRECTNESS_RUNNER_CODES
                    else "arm_execution_failure"
                ),
                "failure_code": exc.code,
            },
        )
        raise
    _write_json_exclusive(
        result_file,
        measurement.model_dump(mode="json"),
    )
    return 0


def _arm_command(
    *,
    args: argparse.Namespace,
    arm: str,
    execution_order: int,
    workspace: Path,
    result_file: Path,
    host_sha256: str,
    configuration_sha256: str,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.benchmark_lifecycle_incremental",
        "arm-worker",
        "--bundle-dir",
        str(args.bundle_dir),
        "--bundle-sha256",
        args.bundle_sha256,
        "--workspace",
        str(workspace),
        "--experiment-id",
        args.experiment_id,
        "--pair-number",
        str(args.pair_number),
        "--arm",
        arm,
        "--execution-order",
        str(execution_order),
        "--coordinator-process-id",
        str(os.getpid()),
        "--host-sha256",
        host_sha256,
        "--configuration-sha256",
        configuration_sha256,
        "--result-file",
        str(result_file),
    ]


def _pair_worker(args: argparse.Namespace) -> int:
    pair_number = _validate_pair_number(args.pair_number)
    bundle_root = _confined_existing_directory(
        args.bundle_dir,
        PRIVATE_ROOT,
        "bundle directory",
    )
    bundle = load_performance_bundle(bundle_root)
    if bundle.manifest_sha256 != args.bundle_sha256:
        raise ValueError("pair worker bundle identity mismatch")
    run_work_root = _confined_existing_directory(
        args.run_work_root,
        PRIVATE_ROOT,
        "run work root",
    )
    template_root = _confined_existing_directory(
        args.base_template,
        PRIVATE_ROOT,
        "base template",
    )
    if template_root != run_work_root / "base-template":
        raise ValueError("base template does not belong to the run work root")
    pair_artifact = _confined_existing_directory(
        args.pair_artifact_dir,
        ARTIFACT_ROOT,
        "pair artifact directory",
    )
    pair_result_file = _confined_new_path(
        args.result_file,
        ARTIFACT_ROOT,
        "pair result",
    )
    expected_pair_name = f"{pair_number:03d}"
    if (
        pair_artifact.name != expected_pair_name
        or pair_artifact.parent.name != "pairs"
        or pair_artifact.parent.parent.name != run_work_root.name
        or pair_result_file != pair_artifact / "pair.json"
    ):
        raise ValueError("pair artifact paths do not match the frozen run identity")

    pair_work = run_work_root / f"pair-{pair_number:03d}"
    if pair_work.exists():
        raise FileExistsError("pair work directory already exists")
    pair_work.mkdir()
    baseline_root = pair_work / "baseline"
    intervention_root = pair_work / "intervention"
    baseline_prestate = clone_arm_workspace(
        bundle=bundle,
        template_root=template_root,
        workspace_root=baseline_root,
    )
    intervention_prestate = clone_arm_workspace(
        bundle=bundle,
        template_root=template_root,
        workspace_root=intervention_root,
    )
    comparable_fields = (
        "bundle_manifest_sha256",
        "base_catalog_sha256",
        "pipeline_sha256",
        "base_manifest_sha256",
        "base_index_prestate_sha256",
        "base_cache_prestate_sha256",
    )
    for field_name in comparable_fields:
        if getattr(baseline_prestate, field_name) != getattr(
            intervention_prestate, field_name
        ):
            raise RuntimeError(
                f"arm base prestates differ in {field_name}"
            )

    host_sha256 = host_identity_sha256()
    configuration_sha256 = runner_configuration_sha256(bundle)
    baseline_first = pair_number % 2 == 1
    order = (
        ("baseline", "intervention")
        if baseline_first
        else ("intervention", "baseline")
    )
    measurements: dict[str, PairedArmMeasurement] = {}
    commands: list[str] = []
    temp_root = pair_work / "temp"
    temp_root.mkdir()
    environment = os.environ.copy()
    environment["TEMP"] = str(temp_root)
    environment["TMP"] = str(temp_root)
    for execution_order, arm in enumerate(order, start=1):
        workspace = (
            baseline_root if arm == "baseline" else intervention_root
        )
        arm_result_file = pair_artifact / f"{arm}.json"
        command = _arm_command(
            args=args,
            arm=arm,
            execution_order=execution_order,
            workspace=workspace,
            result_file=arm_result_file,
            host_sha256=host_sha256,
            configuration_sha256=configuration_sha256,
        )
        commands.append(_public_command(command))
        log_root = pair_work / "logs"
        log_root.mkdir(exist_ok=True)
        log_path = log_root / f"{arm}.log"
        with log_path.open("x", encoding="utf-8", newline="\n") as log:
            completed = subprocess.run(
                command,
                cwd=BASE_DIR,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        if completed.returncode != 0:
            arm_failure_path = pair_artifact / f"{arm}-failure.json"
            arm_failure = (
                json.loads(arm_failure_path.read_text(encoding="utf-8"))
                if arm_failure_path.is_file()
                else {}
            )
            _write_json_exclusive(
                pair_artifact / "failure.json",
                {
                    "schema_version": "g10_pair_failure_v1",
                    "failure_kind": arm_failure.get(
                        "failure_kind",
                        "arm_worker_failure",
                    ),
                    "failure_code": arm_failure.get(
                        "failure_code",
                        "worker_nonzero_exit",
                    ),
                    "failed_arm": arm,
                    "worker_exit_code": completed.returncode,
                },
            )
            raise RuntimeError(
                f"{arm} worker failed with exit code {completed.returncode}"
            )
        measurements[arm] = PairedArmMeasurement.model_validate_json(
            arm_result_file.read_text(encoding="utf-8")
        )
    try:
        pair = PairedMeasurement(
            baseline=measurements["baseline"],
            intervention=measurements["intervention"],
        )
    except ValidationError as exc:
        messages = {
            str(item.get("msg", "")).removeprefix("Value error, ")
            for item in exc.errors()
        }
        correctness_mismatch = bool(
            messages.intersection(_CORRECTNESS_FAILURE_MESSAGES)
        )
        _write_json_exclusive(
            pair_artifact / "failure.json",
            {
                "schema_version": "g10_pair_failure_v1",
                "failure_kind": (
                    "correctness_mismatch"
                    if correctness_mismatch
                    else "pair_validation_failure"
                ),
                "validation_messages": sorted(messages),
            },
        )
        raise RuntimeError("paired measurement validation failed") from exc
    _write_exclusive(
        pair_artifact / "commands.txt",
        ("\n".join(commands) + "\n").encode("utf-8"),
    )
    _write_json_exclusive(
        pair_result_file,
        pair.model_dump(mode="json"),
    )
    return 0


def _pair_command(
    *,
    args: argparse.Namespace,
    pair_number: int,
    run_work_root: Path,
    pair_artifact_dir: Path,
    result_file: Path,
    bundle_sha256: str,
    base_template: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scripts.benchmark_lifecycle_incremental",
        "pair-worker",
        "--bundle-dir",
        str(args.bundle_dir),
        "--bundle-sha256",
        bundle_sha256,
        "--run-work-root",
        str(run_work_root),
        "--base-template",
        str(base_template),
        "--pair-artifact-dir",
        str(pair_artifact_dir),
        "--result-file",
        str(result_file),
        "--experiment-id",
        args.experiment_id,
        "--pair-number",
        str(pair_number),
    ]


def _registered_experiment(
    *,
    experiment_id: str,
    bundle_sha256: str,
    repetitions: int,
    host_sha256: str,
    configuration_sha256: str,
    source_commit_sha: str,
    runner_identity: dict[str, str | int],
) -> ExperimentRecord:
    records = load_jsonl_records(EXPERIMENTS_PATH, ExperimentRecord)
    validate_experiment_history(records)
    record = next(
        (
            item
            for item in records
            if item.experiment_id == experiment_id
        ),
        None,
    )
    if record is None or record.status is not ExperimentStatus.REGISTERED:
        raise ValueError("matching REGISTERED experiment is required")
    if (
        record.dataset_sha256 != bundle_sha256
        or record.repetitions != repetitions
        or record.environment.get("registered_experiment_id")
        != experiment_id
        or record.environment.get("host_identity_sha256") != host_sha256
        or record.environment.get("configuration_sha256")
        != configuration_sha256
        or record.environment.get("source_commit_sha") != source_commit_sha
        or any(
            record.environment.get(key) != value
            for key, value in runner_identity.items()
        )
    ):
        raise ValueError(
            "REGISTERED experiment does not match frozen execution identity"
        )
    decision_protocol_from_experiment_thresholds(
        success_thresholds=record.success_thresholds,
        failure_thresholds=record.failure_thresholds,
        expected_pair_count=repetitions,
    )
    return record


def _build_registration_record(
    *,
    bundle: LoadedPerformanceBundle,
    experiment_id: str,
    running_id: str,
    completed_id: str,
    run_id: str,
    repetitions: int,
    source_commit_sha: str,
    registered_at: datetime,
    source_manifest_sha256: str,
) -> ExperimentRecord:
    if len({experiment_id, running_id, completed_id}) != 3:
        raise ValueError("experiment transition IDs must be distinct")
    protocol = frozen_decision_protocol(repetitions)
    success_thresholds = {
        "active_index_deletion_residual_count": (
            protocol.active_index_deletion_residual_count
        ),
        "correctness_equivalent_pairs": (
            protocol.correctness_equivalent_pairs
        ),
        "faster_pair_count_at_least": (
            protocol.faster_pair_count_at_least
        ),
        "intervention_embedding_call_ratio_at_most": (
            protocol.intervention_embedding_call_ratio_at_most
        ),
        "median_total_time_ratio_at_most": (
            protocol.median_total_time_ratio_at_most
        ),
    }
    failure_thresholds = {
        "any_active_index_deletion_residual": (
            protocol.any_active_index_deletion_residual
        ),
        "any_correctness_mismatch": protocol.any_correctness_mismatch,
        "infrastructure_failure_status": (
            protocol.infrastructure_failure_status
        ),
        "median_total_time_ratio_regression_at_or_above": (
            protocol.median_total_time_ratio_regression_at_or_above
        ),
        "unrepresentable_frozen_dataset_status": (
            protocol.unrepresentable_frozen_dataset_status
        ),
    }
    runner_identity = runner_environment_identity(bundle)
    environment: dict[str, str | int | float | bool | None] = {
        "registered_experiment_id": experiment_id,
        "source_commit_sha": source_commit_sha,
        "host_identity_sha256": host_identity_sha256(),
        **runner_identity,
        "source_manifest_sha256": source_manifest_sha256,
        "bundle_base_catalog_sha256": revision_catalog_sha256(
            bundle.base_catalog
        ),
        "bundle_target_catalog_sha256": revision_catalog_sha256(
            bundle.target_catalog
        ),
        "bundle_change_descriptor_sha256": _sha256(
            _canonical_json_bytes(
                bundle.change_descriptor.model_dump(mode="json")
            )
        ),
        "bundle_query_descriptor_sha256": _sha256(
            _canonical_json_bytes(
                bundle.query_descriptor.model_dump(mode="json")
            )
        ),
        "embedding_backend": "deterministic-local",
        "embedding_model": "deterministic-shake256-128",
        "embedding_dimension": 128,
    }
    run_command = (
        "python -m scripts.benchmark_lifecycle_incremental run "
        f"--bundle-dir {bundle.root.relative_to(BASE_DIR).as_posix()} "
        f"--run-id {run_id} "
        f"--experiment-id {experiment_id} "
        f"--running-id {running_id} "
        f"--completed-id {completed_id} "
        f"--repetitions {repetitions}"
    )
    return ExperimentRecord(
        schema_version=2,
        experiment_id=experiment_id,
        registered_at=registered_at,
        status=ExperimentStatus.REGISTERED,
        hypothesis=(
            "On the frozen canonical lifecycle dataset, production "
            "computation-cache reuse reduces median complete target-build "
            "wall time while preserving exact target, positive and negative "
            "ACL query, and deletion correctness."
        ),
        baseline=(
            "From the same accepted base state, recompute the complete "
            "changed target with a new empty target computation cache; "
            "raw-file admission and base-template construction are outside "
            "the measured operation."
        ),
        intervention=(
            "From the same accepted base state, reuse its production "
            "computation cache for the identical ChangePlan and complete the "
            "same immutable target publication."
        ),
        controlled_variables=[
            "same canonical lifecycle bundle manifest",
            "same byte-copied validated base template",
            "same base and target revision catalogs",
            "same base-to-target ChangePlan",
            "same G6 computation and G7 publication code",
            "same deterministic embedding identity",
            "same source commit and runner source-tree hash",
            "same host and dependency identity",
            "fresh independent arm-worker process per arm",
            "alternating baseline-first and intervention-first order",
        ],
        dataset_id=_DATASET_ID,
        dataset_sha256=bundle.manifest_sha256,
        sample_size=bundle.manifest.counts.base_document_count,
        repetitions=repetitions,
        metrics=[
            "complete target-build wall time",
            "input validation wall time",
            "G6 computation wall time including transaction finalization",
            "G7 publication validation and activation wall time",
            "independent peak RSS bytes",
            "stage callback and cache hit miss counts",
            "exact target artifact fingerprint equality",
            "positive and negative ACL query fingerprint equality",
            "active-index deletion residual count",
            "paired ratio P50 P95 and AB BA order strata",
        ],
        success_thresholds=success_thresholds,
        failure_thresholds=failure_thresholds,
        environment=environment,
        commands=[
            (
                "python -m scripts.benchmark_lifecycle_incremental inspect "
                f"--bundle-dir {bundle.root.relative_to(BASE_DIR).as_posix()}"
            ),
            run_command,
        ],
    )


def _register(args: argparse.Namespace) -> int:
    if args.repetitions != 10:
        raise ValueError("deterministic G10 registration requires 10 pairs")
    run_id = _validate_run_id(args.run_id)
    bundle_root = _confined_existing_directory(
        args.bundle_dir,
        PRIVATE_ROOT,
        "bundle directory",
    )
    bundle = load_performance_bundle(bundle_root)
    source_manifest = SOURCE_CORPUS / "manifest.json"
    record = _build_registration_record(
        bundle=bundle,
        experiment_id=args.experiment_id,
        running_id=args.running_id,
        completed_id=args.completed_id,
        run_id=run_id,
        repetitions=args.repetitions,
        source_commit_sha=_source_commit_sha(require_clean_runner=True),
        registered_at=datetime.now(timezone.utc),
        source_manifest_sha256=_sha256(source_manifest.read_bytes()),
    )
    append_jsonl_record(
        EXPERIMENTS_PATH,
        record=record,
        model=ExperimentRecord,
        id_field="experiment_id",
    )
    print(record.model_dump_json())
    return 0


def _append_running(
    registered: ExperimentRecord,
    *,
    running_id: str,
) -> ExperimentRecord:
    started_at = datetime.now(timezone.utc)
    running = registered.model_copy(
        update={
            "experiment_id": running_id,
            "status": ExperimentStatus.RUNNING,
            "started_at": (
                started_at if registered.schema_version == 2 else None
            ),
            "revision_of": registered.experiment_id,
            "revision_reason": "Execution started after preregistration validation.",
        }
    )
    append_jsonl_record(
        EXPERIMENTS_PATH,
        record=running,
        model=ExperimentRecord,
        id_field="experiment_id",
    )
    return running


def _artifact_hashes(paths: list[Path]) -> tuple[list[str], list[str]]:
    relative_paths: list[str] = []
    hashes: list[str] = []
    for path in paths:
        relative_paths.append(path.relative_to(BASE_DIR).as_posix())
        hashes.append(_sha256(path.read_bytes()))
    return relative_paths, hashes


def _append_completed(
    parent: ExperimentRecord,
    *,
    completed_id: str,
    summary,
    artifact_paths: list[Path],
    completed_at: datetime | None = None,
) -> None:
    transition_completed_at = completed_at or datetime.now(timezone.utc)
    relative_paths, hashes = _artifact_hashes(artifact_paths)
    completed = parent.model_copy(
        update={
            "experiment_id": completed_id,
            "status": ExperimentStatus.COMPLETED,
            "completed_at": (
                transition_completed_at
                if parent.schema_version == 2
                else None
            ),
            "revision_of": parent.experiment_id,
            "revision_reason": "Frozen paired experiment completed.",
            "raw_artifact_paths": relative_paths,
            "raw_artifact_hashes": hashes,
            "result_summary": {
                "pair_count": summary.pair_count,
                "median_total_time_ratio": summary.total_time_ratio.p50,
                "p95_total_time_ratio": summary.total_time_ratio.p95,
                "faster_pair_count": summary.faster_pair_count,
                "embedding_call_ratio": (
                    summary.intervention_embedding_call_ratio
                ),
                "baseline_peak_rss_bytes": (
                    summary.baseline_peak_rss_bytes
                ),
                "intervention_peak_rss_bytes": (
                    summary.intervention_peak_rss_bytes
                ),
            },
            "uncertainty": {
                "baseline_first_median_ratio": (
                    summary.baseline_first_total_time_ratio.p50
                ),
                "intervention_first_median_ratio": (
                    summary.intervention_first_total_time_ratio.p50
                ),
            },
            "final_status": ExperimentFinalStatus(summary.decision),
            "decision": (
                "Applied the preregistered correctness, paired-time, "
                "faster-pair, and embedding-call thresholds without changes."
            ),
            "limitations": [
                "Deterministic embeddings measure local lifecycle pipeline overhead.",
                "AB/BA order reduces but does not eliminate operating-system cache bias.",
                "This result is not a live Ollama latency claim.",
            ],
        }
    )
    append_jsonl_record(
        EXPERIMENTS_PATH,
        record=completed,
        model=ExperimentRecord,
        id_field="experiment_id",
    )


def _append_failed_completion(
    parent: ExperimentRecord,
    *,
    completed_id: str,
    final_status: ExperimentFinalStatus,
    failure_stage: str,
    failure_code: str,
    completed_pairs: int,
    artifact_paths: list[Path],
    completed_at: datetime | None = None,
) -> None:
    transition_completed_at = completed_at or datetime.now(timezone.utc)
    existing_artifacts = [path for path in artifact_paths if path.is_file()]
    relative_paths, hashes = _artifact_hashes(existing_artifacts)
    completed = parent.model_copy(
        update={
            "experiment_id": completed_id,
            "status": ExperimentStatus.COMPLETED,
            "completed_at": (
                transition_completed_at
                if parent.schema_version == 2
                else None
            ),
            "revision_of": parent.experiment_id,
            "revision_reason": (
                "The frozen paired run reached a terminal failure state."
            ),
            "raw_artifact_paths": relative_paths,
            "raw_artifact_hashes": hashes,
            "result_summary": {
                "completed_pairs": completed_pairs,
                "failure_stage": failure_stage,
                "failure_code": failure_code,
            },
            "uncertainty": {
                "performance_hypothesis_evaluated": False,
                "partial_timing_rows_reusable": False,
            },
            "final_status": final_status,
            "decision": (
                "No performance claim is accepted from an incomplete run."
                if final_status is ExperimentFinalStatus.INCONCLUSIVE
                else "The frozen exact-correctness threshold was violated."
            ),
            "limitations": [
                "Incomplete paired runs cannot support a performance claim.",
                "Partial timing rows are retained only for failure diagnosis.",
            ],
        }
    )
    append_jsonl_record(
        EXPERIMENTS_PATH,
        record=completed,
        model=ExperimentRecord,
        id_field="experiment_id",
    )


def _run(args: argparse.Namespace) -> int:
    run_id = _validate_run_id(args.run_id)
    if args.repetitions != 10:
        raise ValueError("deterministic G10 run requires exactly 10 pairs")
    bundle_root = _confined_existing_directory(
        args.bundle_dir,
        PRIVATE_ROOT,
        "bundle directory",
    )
    bundle = load_performance_bundle(bundle_root)
    host_sha256 = host_identity_sha256()
    runner_identity = runner_environment_identity(bundle)
    configuration_sha256 = str(
        runner_identity["configuration_sha256"]
    )
    source_commit_sha = _source_commit_sha(require_clean_runner=True)
    registered = _registered_experiment(
        experiment_id=args.experiment_id,
        bundle_sha256=bundle.manifest_sha256,
        repetitions=args.repetitions,
        host_sha256=host_sha256,
        configuration_sha256=configuration_sha256,
        source_commit_sha=source_commit_sha,
        runner_identity=runner_identity,
    )
    work_root = PRIVATE_ROOT / run_id
    artifact_root = ARTIFACT_ROOT / run_id
    if work_root.exists() or artifact_root.exists():
        raise FileExistsError("benchmark run ID already exists; resume is forbidden")

    running = _append_running(registered, running_id=args.running_id)
    stage = "artifact_initialization"
    completed_pairs = 0
    final_status = ExperimentFinalStatus.INCONCLUSIVE
    failure_code = "infrastructure_failure"
    status_path = artifact_root / "status.json"
    environment_path = artifact_root / "environment.json"
    commands_path = artifact_root / "commands.txt"
    top_level_commands: list[str] = []
    try:
        work_root.mkdir(parents=True)
        artifact_root.mkdir(parents=True)
        status = {
            "schema_version": "g10_run_status_v2",
            "run_id": run_id,
            "experiment_id": registered.experiment_id,
            "bundle_manifest_sha256": bundle.manifest_sha256,
            "configuration_sha256": configuration_sha256,
            "started_at": (
                None
                if running.started_at is None
                else running.started_at.isoformat()
            ),
            "status": "RUNNING",
            "completed_pairs": 0,
            "requested_pairs": args.repetitions,
        }
        _write_json_replace(status_path, status)
        _write_json_exclusive(
            environment_path,
            {
                "schema_version": "g10_environment_v2",
                "run_id": run_id,
                "experiment_id": registered.experiment_id,
                "host_identity_sha256": host_sha256,
                "source_commit_sha": source_commit_sha,
                **runner_identity,
                "bundle_manifest_sha256": bundle.manifest_sha256,
                "source_corpus_manifest_sha256": _sha256(
                    (SOURCE_CORPUS / "manifest.json").read_bytes()
                ),
            },
        )
        stage = "base_template_preparation"
        base_template = work_root / "base-template"
        prepare_arm_workspace(
            bundle=bundle,
            workspace_root=base_template,
        )
        pairs_root = artifact_root / "pairs"
        pairs_root.mkdir()

        pairs: list[PairedMeasurement] = []
        for pair_number in range(1, args.repetitions + 1):
            stage = f"pair_{pair_number:03d}"
            pair_artifact = pairs_root / f"{pair_number:03d}"
            pair_artifact.mkdir()
            result_file = pair_artifact / "pair.json"
            command = _pair_command(
                args=args,
                pair_number=pair_number,
                run_work_root=work_root,
                pair_artifact_dir=pair_artifact,
                result_file=result_file,
                bundle_sha256=bundle.manifest_sha256,
                base_template=base_template,
            )
            top_level_commands.append(_public_command(command))
            log_path = work_root / f"pair-{pair_number:03d}-coordinator.log"
            environment = os.environ.copy()
            environment["TEMP"] = str(work_root)
            environment["TMP"] = str(work_root)
            with log_path.open("x", encoding="utf-8", newline="\n") as log:
                completed = subprocess.run(
                    command,
                    cwd=BASE_DIR,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
            if completed.returncode != 0:
                pair_failure_path = pair_artifact / "failure.json"
                if pair_failure_path.is_file():
                    failure = json.loads(
                        pair_failure_path.read_text(encoding="utf-8")
                    )
                    if failure.get("failure_kind") == "correctness_mismatch":
                        final_status = ExperimentFinalStatus.REGRESSION
                        failure_code = "exact_correctness_mismatch"
                raise RuntimeError("pair worker failed")
            pairs.append(
                PairedMeasurement.model_validate_json(
                    result_file.read_text(encoding="utf-8")
                )
            )
            completed_pairs = pair_number
            status["completed_pairs"] = pair_number
            _write_json_replace(status_path, status)

        stage = "summary"
        summary = summarize_paired_measurements(
            pairs,
            expected_pair_count=args.repetitions,
            decision_protocol=decision_protocol_from_experiment_thresholds(
                success_thresholds=registered.success_thresholds,
                failure_thresholds=registered.failure_thresholds,
                expected_pair_count=args.repetitions,
            ),
        )
        summary_path = artifact_root / "summary.json"
        pairs_path = artifact_root / "pairs.jsonl"
        _write_json_exclusive(summary_path, summary.model_dump(mode="json"))
        _write_exclusive(
            pairs_path,
            b"".join(
                _canonical_json_bytes(pair.model_dump(mode="json")) + b"\n"
                for pair in pairs
            ),
        )
        _write_exclusive(
            commands_path,
            ("\n".join(top_level_commands) + "\n").encode("utf-8"),
        )
        completed_at = datetime.now(timezone.utc)
        status.update(
            {
                "status": "COMPLETED",
                "worker_exit_code": 0,
                "completed_at": completed_at.isoformat(),
            }
        )
        _write_json_replace(status_path, status)
        _append_completed(
            running,
            completed_id=args.completed_id,
            summary=summary,
            artifact_paths=[
                summary_path,
                pairs_path,
                environment_path,
                commands_path,
                status_path,
                *sorted(
                    (
                        path
                        for path in pairs_root.rglob("*")
                        if path.is_file()
                    ),
                    key=lambda path: path.as_posix(),
                ),
            ],
            completed_at=completed_at,
        )
        print(summary.model_dump_json())
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        completed_at = datetime.now(timezone.utc)
        if artifact_root.is_dir():
            if top_level_commands and not commands_path.exists():
                _write_exclusive(
                    commands_path,
                    ("\n".join(top_level_commands) + "\n").encode("utf-8"),
                )
            failure_status = {
                "schema_version": "g10_run_status_v2",
                "run_id": run_id,
                "experiment_id": registered.experiment_id,
                "bundle_manifest_sha256": bundle.manifest_sha256,
                "configuration_sha256": configuration_sha256,
                "started_at": (
                    None
                    if running.started_at is None
                    else running.started_at.isoformat()
                ),
                "completed_at": completed_at.isoformat(),
                "status": final_status.value,
                "completed_pairs": completed_pairs,
                "requested_pairs": args.repetitions,
                "failure_stage": stage,
                "failure_code": failure_code,
                "exception_type": type(exc).__name__,
            }
            _write_json_replace(status_path, failure_status)
        _append_failed_completion(
            running,
            completed_id=args.completed_id,
            final_status=final_status,
            failure_stage=stage,
            failure_code=failure_code,
            completed_pairs=completed_pairs,
            artifact_paths=[environment_path, commands_path, status_path],
            completed_at=completed_at,
        )
        print(f"error: {type(exc).__name__} during {stage}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze and run the G10 paired lifecycle experiment.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--output-dir", type=Path, required=True)

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--bundle-dir", type=Path, required=True)

    register = subparsers.add_parser("register")
    register.add_argument("--bundle-dir", type=Path, required=True)
    register.add_argument("--run-id", required=True)
    register.add_argument("--experiment-id", required=True)
    register.add_argument("--running-id", required=True)
    register.add_argument("--completed-id", required=True)
    register.add_argument("--repetitions", type=int, default=10)

    arm = subparsers.add_parser("arm-worker")
    arm.add_argument("--bundle-dir", type=Path, required=True)
    arm.add_argument("--bundle-sha256", required=True)
    arm.add_argument("--workspace", type=Path, required=True)
    arm.add_argument("--experiment-id", required=True)
    arm.add_argument("--pair-number", type=int, required=True)
    arm.add_argument("--arm", choices=("baseline", "intervention"), required=True)
    arm.add_argument("--execution-order", type=int, choices=(1, 2), required=True)
    arm.add_argument("--coordinator-process-id", type=int, required=True)
    arm.add_argument("--host-sha256", required=True)
    arm.add_argument("--configuration-sha256", required=True)
    arm.add_argument("--result-file", type=Path, required=True)

    pair = subparsers.add_parser("pair-worker")
    pair.add_argument("--bundle-dir", type=Path, required=True)
    pair.add_argument("--bundle-sha256", required=True)
    pair.add_argument("--run-work-root", type=Path, required=True)
    pair.add_argument("--base-template", type=Path, required=True)
    pair.add_argument("--pair-artifact-dir", type=Path, required=True)
    pair.add_argument("--result-file", type=Path, required=True)
    pair.add_argument("--experiment-id", required=True)
    pair.add_argument("--pair-number", type=int, required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--bundle-dir", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--experiment-id", required=True)
    run.add_argument("--running-id", required=True)
    run.add_argument("--completed-id", required=True)
    run.add_argument("--repetitions", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "freeze":
            return _freeze(args)
        if args.command == "inspect":
            return _inspect(args)
        if args.command == "register":
            return _register(args)
        if args.command == "arm-worker":
            return _arm_worker(args)
        if args.command == "pair-worker":
            return _pair_worker(args)
        return _run(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
