from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

import pytest

from app.lifecycle.evidence import (
    EvidenceArtifactHash,
    ExperimentRecord,
    load_jsonl_records,
    validate_experiment_history,
)
from app.lifecycle.performance_evidence import (
    G10EnvironmentArtifact,
    G10RunStatusArtifact,
    LifecyclePerformanceEvidencePackageManifest,
    LifecyclePerformancePublicSummary,
    build_public_performance_summary,
    canonical_performance_package_checksums,
    canonical_performance_package_manifest_bytes,
    canonical_public_performance_summary_bytes,
    verify_public_performance_evidence_package,
)
from scripts import export_lifecycle_performance_evidence as exporter
from scripts import verify_lifecycle_performance_evidence as verifier_cli


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = (
    REPOSITORY_ROOT / "data" / "v2" / "public" / "lifecycle_g10"
)


def _completed_experiment() -> ExperimentRecord:
    records = load_jsonl_records(
        REPOSITORY_ROOT / "docs" / "lifecycle" / "EXPERIMENTS.jsonl",
        ExperimentRecord,
    )
    validate_experiment_history(records)
    return next(
        item for item in records if item.experiment_id == "EXP-LC-006"
    )


def _v2_evidence(
    tmp_path: Path,
) -> tuple[Path, list[ExperimentRecord], ExperimentRecord]:
    legacy = _completed_experiment()
    root = tmp_path / "v2-repository"
    run_root = root / "artifacts" / "lifecycle" / "g10-v2-fixture"
    run_root.mkdir(parents=True)
    source_run = (
        REPOSITORY_ROOT
        / "artifacts"
        / "lifecycle"
        / "g10-paired-20260727-02"
    )
    aggregate_names = (
        "summary.json",
        "pairs.jsonl",
        "environment.json",
        "commands.txt",
        "status.json",
    )
    for name in aggregate_names:
        shutil.copyfile(source_run / name, run_root / name)
    for pair_number in range(1, 11):
        source_pair = source_run / "pairs" / f"{pair_number:03d}"
        target_pair = run_root / "pairs" / f"{pair_number:03d}"
        target_pair.mkdir(parents=True)
        for name in (
            "baseline.json",
            "intervention.json",
            "pair.json",
            "commands.txt",
        ):
            shutil.copyfile(source_pair / name, target_pair / name)

    legacy_environment = json.loads(
        (source_run / "environment.json").read_text(encoding="utf-8")
    )
    registered_id = "EXP-LC-004"
    running_id = "EXP-LC-900"
    completed_id = "EXP-LC-901"
    run_id = "g10-v2-fixture"
    source_commit_sha = "1" * 40
    source_tree_sha256 = "2" * 64
    source_paths_sha256 = "3" * 64
    requirements_sha256 = "4" * 64
    runtime_dependencies_sha256 = "5" * 64
    source_file_count = 421
    started_at = datetime(2026, 7, 27, 5, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=30)
    environment_payload = {
        "schema_version": "g10_environment_v2",
        "run_id": run_id,
        "experiment_id": registered_id,
        "host_identity_sha256": legacy.environment[
            "host_identity_sha256"
        ],
        "source_commit_sha": source_commit_sha,
        "configuration_sha256": legacy.environment[
            "configuration_sha256"
        ],
        "source_tree_sha256": source_tree_sha256,
        "source_paths_sha256": source_paths_sha256,
        "requirements_sha256": requirements_sha256,
        "runtime_dependencies_sha256": runtime_dependencies_sha256,
        "pipeline_sha256": legacy.environment["pipeline_sha256"],
        "bundle_manifest_sha256": legacy.dataset_sha256,
        "source_corpus_manifest_sha256": legacy_environment[
            "source_corpus_manifest_sha256"
        ],
        "source_file_count": source_file_count,
    }
    status_payload = {
        "schema_version": "g10_run_status_v2",
        "run_id": run_id,
        "experiment_id": registered_id,
        "bundle_manifest_sha256": legacy.dataset_sha256,
        "configuration_sha256": legacy.environment[
            "configuration_sha256"
        ],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "status": "COMPLETED",
        "completed_pairs": 10,
        "requested_pairs": 10,
        "worker_exit_code": 0,
    }
    (run_root / "environment.json").write_text(
        json.dumps(environment_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_root / "status.json").write_text(
        json.dumps(status_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    record_environment = {
        **legacy.environment,
        "registered_experiment_id": registered_id,
        "source_commit_sha": source_commit_sha,
        "source_tree_sha256": source_tree_sha256,
        "source_paths_sha256": source_paths_sha256,
        "requirements_sha256": requirements_sha256,
        "runtime_dependencies_sha256": runtime_dependencies_sha256,
        "source_file_count": source_file_count,
    }
    registered_payload = legacy.model_dump(mode="json")
    registered_payload.update(
        {
            "schema_version": 2,
            "experiment_id": registered_id,
            "status": "REGISTERED",
            "started_at": None,
            "completed_at": None,
            "environment": record_environment,
            "raw_artifact_paths": [],
            "raw_artifact_hashes": [],
            "result_summary": {},
            "uncertainty": {},
            "final_status": None,
            "decision": "",
            "limitations": [],
            "revision_of": None,
            "revision_reason": None,
        }
    )
    registered = ExperimentRecord.model_validate(registered_payload)
    running_payload = registered.model_dump(mode="json")
    running_payload.update(
        {
            "experiment_id": running_id,
            "status": "RUNNING",
            "started_at": started_at,
            "revision_of": registered_id,
            "revision_reason": "Fixture execution started.",
        }
    )
    running = ExperimentRecord.model_validate(running_payload)

    aggregate_paths = [
        (run_root / name).relative_to(root).as_posix()
        for name in aggregate_names
    ]
    child_paths = sorted(
        (
            path.relative_to(root).as_posix()
            for path in (run_root / "pairs").rglob("*")
            if path.is_file()
        )
    )
    raw_paths = aggregate_paths + child_paths
    raw_hashes = [
        hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in raw_paths
    ]
    completed_payload = running.model_dump(mode="json")
    completed_payload.update(
        {
            "experiment_id": completed_id,
            "status": "COMPLETED",
            "completed_at": completed_at,
            "revision_of": running_id,
            "revision_reason": "Fixture execution completed.",
            "raw_artifact_paths": raw_paths,
            "raw_artifact_hashes": raw_hashes,
            "result_summary": legacy.result_summary,
            "uncertainty": legacy.uncertainty,
            "final_status": legacy.final_status.value,
            "decision": legacy.decision,
            "limitations": legacy.limitations,
        }
    )
    completed = ExperimentRecord.model_validate(completed_payload)
    history = [registered, running, completed]
    validate_experiment_history(history)
    return root, history, completed


def _copy_bound_evidence(
    tmp_path: Path,
    record: ExperimentRecord,
) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    for relative_path in record.raw_artifact_paths:
        source = REPOSITORY_ROOT / relative_path
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return root


def _replace_artifact_binding(
    record: ExperimentRecord,
    root: Path,
    suffix: str,
    content: bytes,
) -> ExperimentRecord:
    matches = [
        (index, relative_path)
        for index, relative_path in enumerate(record.raw_artifact_paths)
        if relative_path.endswith(suffix)
    ]
    assert len(matches) == 1
    index, relative_path = matches[0]
    (root / relative_path).write_bytes(content)
    hashes = list(record.raw_artifact_hashes)
    hashes[index] = hashlib.sha256(content).hexdigest()
    payload = record.model_dump(mode="json")
    payload["raw_artifact_hashes"] = hashes
    return ExperimentRecord.model_validate(payload)


def _replace_exact_artifact_binding(
    record: ExperimentRecord,
    root: Path,
    relative_path: str,
    content: bytes,
) -> ExperimentRecord:
    index = record.raw_artifact_paths.index(relative_path)
    (root / relative_path).write_bytes(content)
    hashes = list(record.raw_artifact_hashes)
    hashes[index] = hashlib.sha256(content).hexdigest()
    payload = record.model_dump(mode="json")
    payload["raw_artifact_hashes"] = hashes
    return ExperimentRecord.model_validate(payload)


def _write_experiment_history(
    path: Path,
    history: list[ExperimentRecord],
) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(
            json.dumps(
                record.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in history
        ),
        encoding="utf-8",
    )


def _rebind_packaged_raw_artifact(
    package_root: Path,
    suffix: str,
    content: bytes,
) -> None:
    manifest_payload = json.loads(
        (package_root / "manifest.json").read_text(encoding="utf-8")
    )
    raw_payload = next(
        item
        for item in manifest_payload["raw_artifacts"]
        if item["source_path"].endswith(suffix)
    )
    package_path = package_root / raw_payload["package_file"]["path"]
    package_path.write_bytes(content)
    raw_payload["package_file"]["byte_count"] = len(content)
    raw_payload["package_file"]["sha256"] = hashlib.sha256(
        content
    ).hexdigest()

    summary_path = package_root / "summary.json"
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_raw = next(
        item
        for item in summary_payload["raw_artifacts"]
        if item["path"].endswith(suffix)
    )
    summary_raw["byte_count"] = len(content)
    summary_raw["sha256"] = hashlib.sha256(content).hexdigest()
    summary = LifecyclePerformancePublicSummary.model_validate(
        summary_payload
    )
    summary_content = canonical_public_performance_summary_bytes(summary)
    summary_path.write_bytes(summary_content)
    manifest_payload["summary"]["byte_count"] = len(summary_content)
    manifest_payload["summary"]["sha256"] = hashlib.sha256(
        summary_content
    ).hexdigest()

    manifest = LifecyclePerformanceEvidencePackageManifest.model_validate(
        manifest_payload
    )
    manifest_content = canonical_performance_package_manifest_bytes(manifest)
    (package_root / "manifest.json").write_bytes(manifest_content)
    manifest_binding = EvidenceArtifactHash(
        path="manifest.json",
        byte_count=len(manifest_content),
        sha256=hashlib.sha256(manifest_content).hexdigest(),
    )
    checksum_content = canonical_performance_package_checksums(
        [
            manifest_binding,
            manifest.summary,
            *(item.package_file for item in manifest.raw_artifacts),
            *manifest.dataset_metadata,
        ]
    )
    (package_root / "checksums.sha256").write_bytes(checksum_content)


def test_public_g10_summary_recomputes_from_bound_raw_artifacts() -> None:
    completed = _completed_experiment()

    expected = build_public_performance_summary(
        REPOSITORY_ROOT,
        completed,
    )
    content = (PUBLIC_ROOT / "summary.json").read_bytes()
    observed = LifecyclePerformancePublicSummary.model_validate_json(content)

    assert content == canonical_public_performance_summary_bytes(observed)
    assert observed == expected
    assert observed.final_status == "SUPPORTED"
    assert observed.correctness_equivalent_pair_count == 10
    assert observed.active_index_deleted_residual_count == 0
    assert observed.faster_pair_count == 10


def test_public_g10_checksum_binds_only_canonical_summary() -> None:
    summary = (PUBLIC_ROOT / "summary.json").read_bytes()
    checksum = hashlib.sha256(summary).hexdigest()

    assert (PUBLIC_ROOT / "checksums.sha256").read_bytes() == (
        f"{checksum}  summary.json\n".encode("ascii")
    )


def test_v2_environment_status_and_registered_identity_are_strict(
    tmp_path: Path,
) -> None:
    root, history, completed = _v2_evidence(tmp_path)
    run_root = root / "artifacts" / "lifecycle" / "g10-v2-fixture"
    environment = G10EnvironmentArtifact.model_validate_json(
        (run_root / "environment.json").read_bytes()
    )
    status = G10RunStatusArtifact.model_validate_json(
        (run_root / "status.json").read_bytes()
    )

    summary = build_public_performance_summary(
        root,
        completed,
        history=history,
    )

    assert environment.schema_version == "g10_environment_v2"
    assert status.schema_version == "g10_run_status_v2"
    assert completed.revision_of == "EXP-LC-900"
    assert summary.registered_experiment_id == "EXP-LC-004"
    assert summary.artifact_schema_version == 2
    assert summary.source_commit_sha == "1" * 40
    assert summary.source_tree_sha256 == "2" * 64
    assert len(summary.raw_artifacts) == 45
    with pytest.raises(ValueError, match="full experiment history"):
        build_public_performance_summary(root, completed)

    environment_payload = json.loads(
        (run_root / "environment.json").read_text(encoding="utf-8")
    )
    environment_payload.pop("source_file_count")
    with pytest.raises(ValueError, match="strict schema"):
        G10EnvironmentArtifact.model_validate(environment_payload)

    status_payload = json.loads(
        (run_root / "status.json").read_text(encoding="utf-8")
    )
    status_payload["started_at"] = "2026-07-27T05:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        G10RunStatusArtifact.model_validate(status_payload)


def test_v2_record_threshold_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    root, history, _ = _v2_evidence(tmp_path)
    changed_history: list[ExperimentRecord] = []
    for record in history:
        payload = record.model_dump(mode="json")
        thresholds = dict(payload["success_thresholds"])
        thresholds["median_total_time_ratio_at_most"] = 0.76
        payload["success_thresholds"] = thresholds
        changed_history.append(ExperimentRecord.model_validate(payload))
    validate_experiment_history(changed_history)

    with pytest.raises(
        ValueError,
        match="differ from the frozen G10 protocol",
    ):
        build_public_performance_summary(
            root,
            changed_history[-1],
            history=changed_history,
        )


def test_v2_aggregate_and_child_pair_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    root, history, completed = _v2_evidence(tmp_path)
    relative_path = next(
        path
        for path in completed.raw_artifact_paths
        if path.endswith("/pairs/001/pair.json")
    )
    payload = json.loads((root / relative_path).read_text(encoding="utf-8"))
    payload["baseline"]["peak_rss_bytes"] += 1
    tampered = _replace_exact_artifact_binding(
        completed,
        root,
        relative_path,
        json.dumps(payload, sort_keys=True).encode("utf-8"),
    )
    tampered_history = [*history[:-1], tampered]

    with pytest.raises(
        ValueError,
        match="child does not match pairs.jsonl",
    ):
        build_public_performance_summary(
            root,
            tampered,
            history=tampered_history,
        )


def test_v2_pair_command_identity_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    root, history, completed = _v2_evidence(tmp_path)
    relative_path = next(
        path
        for path in completed.raw_artifact_paths
        if path.endswith("/pairs/001/commands.txt")
    )
    text = (root / relative_path).read_text(encoding="utf-8")
    text = text.replace(completed.dataset_sha256, "0" * 64, 1)
    tampered = _replace_exact_artifact_binding(
        completed,
        root,
        relative_path,
        text.encode("utf-8"),
    )

    with pytest.raises(ValueError, match="mixed execution identity"):
        build_public_performance_summary(
            root,
            tampered,
            history=[*history[:-1], tampered],
        )


def test_ambiguous_shallow_aggregate_commands_are_rejected(
    tmp_path: Path,
) -> None:
    root, history, completed = _v2_evidence(tmp_path)
    aggregate_commands = next(
        path
        for path in completed.raw_artifact_paths
        if path.endswith("/g10-v2-fixture/commands.txt")
    )
    extra_path = "artifacts/lifecycle/g10-v2-shadow/commands.txt"
    extra = root / extra_path
    extra.parent.mkdir(parents=True)
    content = (root / aggregate_commands).read_bytes() + b"# shadow\n"
    extra.write_bytes(content)
    payload = completed.model_dump(mode="json")
    payload["raw_artifact_paths"] = [
        *completed.raw_artifact_paths,
        extra_path,
    ]
    payload["raw_artifact_hashes"] = [
        *completed.raw_artifact_hashes,
        hashlib.sha256(content).hexdigest(),
    ]
    tampered = ExperimentRecord.model_validate(payload)

    with pytest.raises(
        ValueError,
        match="ambiguous shallow aggregate commands.txt",
    ):
        build_public_performance_summary(
            root,
            tampered,
            history=[*history[:-1], tampered],
        )


@pytest.mark.parametrize(
    ("field_name", "message"),
    [
        ("bundle_manifest_sha256", "mixed bundle manifest identity"),
        ("configuration_sha256", "mixed configuration identity"),
        ("host_identity_sha256", "mixed host identity"),
        ("source_corpus_manifest_sha256", "mixed source manifest identity"),
    ],
)
def test_environment_identity_tamper_is_rejected_even_when_rebound(
    tmp_path: Path,
    field_name: str,
    message: str,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    environment_path = next(
        root / path
        for path in completed.raw_artifact_paths
        if path.endswith("/environment.json")
    )
    payload = json.loads(environment_path.read_text(encoding="utf-8"))
    payload[field_name] = "0" * 64
    content = json.dumps(payload, sort_keys=True).encode("utf-8")
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/environment.json",
        content,
    )

    with pytest.raises(ValueError, match=message):
        build_public_performance_summary(root, tampered)


def test_legacy_environment_rejects_v2_only_field(
    tmp_path: Path,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    environment_path = next(
        root / path
        for path in completed.raw_artifact_paths
        if path.endswith("/environment.json")
    )
    payload = json.loads(environment_path.read_text(encoding="utf-8"))
    payload["pipeline_sha256"] = completed.environment["pipeline_sha256"]
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/environment.json",
        json.dumps(payload, sort_keys=True).encode("utf-8"),
    )

    with pytest.raises(ValueError, match="strict schema"):
        build_public_performance_summary(root, tampered)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("completed_pairs", 9, "pair counts"),
        ("worker_exit_code", 1, "worker_exit_code"),
        ("status", "FAILED", "status"),
    ],
)
def test_status_tamper_is_rejected_even_when_rebound(
    tmp_path: Path,
    field_name: str,
    value: object,
    message: str,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    status_path = next(
        root / path
        for path in completed.raw_artifact_paths
        if path.endswith("/status.json")
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload[field_name] = value
    content = json.dumps(payload, sort_keys=True).encode("utf-8")
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/status.json",
        content,
    )

    with pytest.raises(ValueError, match=message):
        build_public_performance_summary(root, tampered)


@pytest.mark.parametrize(
    "field_name",
    [
        "bundle_manifest_sha256",
        "configuration_sha256",
        "host_identity_sha256",
        "pipeline_sha256",
    ],
)
def test_measurement_identity_tamper_is_rejected_even_when_rebound(
    tmp_path: Path,
    field_name: str,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    pairs_path = next(
        root / path
        for path in completed.raw_artifact_paths
        if path.endswith("/pairs.jsonl")
    )
    rows = [
        json.loads(line)
        for line in pairs_path.read_text(encoding="utf-8").splitlines()
    ]
    for row in rows:
        row["baseline"][field_name] = "0" * 64
        row["intervention"][field_name] = "0" * 64
    content = (
        "\n".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"))
            for row in rows
        )
        + "\n"
    ).encode("utf-8")
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/pairs.jsonl",
        content,
    )

    with pytest.raises(
        ValueError,
        match=f"mixed {field_name} identity",
    ):
        build_public_performance_summary(root, tampered)


def test_measurement_pair_id_tamper_is_rejected_even_when_rebound(
    tmp_path: Path,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    pairs_path = next(
        root / path
        for path in completed.raw_artifact_paths
        if path.endswith("/pairs.jsonl")
    )
    rows = [
        json.loads(line)
        for line in pairs_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["baseline"]["pair_number"] = 11
    rows[0]["intervention"]["pair_number"] = 11
    content = (
        "\n".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"))
            for row in rows
        )
        + "\n"
    ).encode("utf-8")
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/pairs.jsonl",
        content,
    )

    with pytest.raises(ValueError, match="ordered and contiguous"):
        build_public_performance_summary(root, tampered)


def test_commands_with_machine_absolute_path_are_rejected_when_rebound(
    tmp_path: Path,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    commands_path = next(
        root / path
        for path in completed.raw_artifact_paths
        if path.endswith("/commands.txt")
    )
    text = commands_path.read_text(encoding="utf-8")
    text = text.replace(
        ".private\\lifecycle\\g10-expanded-lifecycle-v3",
        r"C:\Users\example\g10-expanded-lifecycle-v3",
        1,
    )
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/commands.txt",
        text.encode("utf-8"),
    )

    with pytest.raises(ValueError, match="unsafe command or machine path"):
        build_public_performance_summary(root, tampered)


def test_empty_commands_are_rejected_even_when_rebound(
    tmp_path: Path,
) -> None:
    completed = _completed_experiment()
    root = _copy_bound_evidence(tmp_path, completed)
    tampered = _replace_artifact_binding(
        completed,
        root,
        "/commands.txt",
        b"",
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        build_public_performance_summary(root, tampered)


def test_exported_package_is_self_contained_and_recomputes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    monkeypatch.setattr(exporter, "PUBLIC_ROOT", public_root)
    output = exporter.export_completed_experiment(
        completed_experiment_id="EXP-LC-006",
        output_directory=public_root / "g10-package",
    )

    observed = verify_public_performance_evidence_package(output)
    manifest_content = (output / "manifest.json").read_bytes()
    manifest = LifecyclePerformanceEvidencePackageManifest.model_validate_json(
        manifest_content
    )
    completed = _completed_experiment()

    assert observed.completed_experiment_id == "EXP-LC-006"
    assert manifest_content == canonical_performance_package_manifest_bytes(
        manifest
    )
    assert {
        item.source_path for item in manifest.raw_artifacts
    } == set(completed.raw_artifact_paths)
    assert manifest.dataset_metadata == ()
    assert all(
        (output / item.package_file.path).is_file()
        for item in manifest.raw_artifacts
    )


def test_v2_exporter_uses_full_history_and_packages_source_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, history, completed = _v2_evidence(tmp_path)
    experiments_path = root / "docs" / "lifecycle" / "EXPERIMENTS.jsonl"
    _write_experiment_history(experiments_path, history)
    public_root = root / "public"
    public_root.mkdir()
    monkeypatch.setattr(exporter, "BASE_DIR", root)
    monkeypatch.setattr(exporter, "EXPERIMENTS_PATH", experiments_path)
    monkeypatch.setattr(exporter, "PUBLIC_ROOT", public_root)

    output = exporter.export_completed_experiment(
        completed_experiment_id=completed.experiment_id,
        output_directory=public_root / "g10-v2-package",
    )
    summary = verify_public_performance_evidence_package(output)
    manifest = LifecyclePerformanceEvidencePackageManifest.model_validate_json(
        (output / "manifest.json").read_bytes()
    )

    assert summary.registered_experiment_id == "EXP-LC-004"
    assert summary.source_commit_sha == "1" * 40
    assert summary.source_tree_sha256 == "2" * 64
    assert manifest.experiment.artifact_schema_version == 2
    assert manifest.experiment.source_commit_sha == "1" * 40
    assert manifest.experiment.source_tree_sha256 == "2" * 64
    assert manifest.experiment.decision_protocol == (
        manifest.experiment.decision_protocol.model_validate(
            {
                **completed.success_thresholds,
                **completed.failure_thresholds,
            }
        )
    )
    assert len(manifest.raw_artifacts) == 45


def test_packaged_decision_protocol_tamper_is_rejected_after_rebinding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, history, completed = _v2_evidence(tmp_path)
    experiments_path = root / "docs" / "lifecycle" / "EXPERIMENTS.jsonl"
    _write_experiment_history(experiments_path, history)
    public_root = root / "public"
    public_root.mkdir()
    monkeypatch.setattr(exporter, "BASE_DIR", root)
    monkeypatch.setattr(exporter, "EXPERIMENTS_PATH", experiments_path)
    monkeypatch.setattr(exporter, "PUBLIC_ROOT", public_root)
    output = exporter.export_completed_experiment(
        completed_experiment_id=completed.experiment_id,
        output_directory=public_root / "g10-v2-threshold-package",
    )
    manifest_path = output / "manifest.json"
    original = LifecyclePerformanceEvidencePackageManifest.model_validate_json(
        manifest_path.read_bytes()
    )
    payload = original.model_dump(mode="json")
    payload["experiment"]["decision_protocol"][
        "median_total_time_ratio_at_most"
    ] = 0.76
    content = (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(content)
    manifest_binding = EvidenceArtifactHash(
        path="manifest.json",
        byte_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    (output / "checksums.sha256").write_bytes(
        canonical_performance_package_checksums(
            [
                manifest_binding,
                original.summary,
                *(
                    item.package_file
                    for item in original.raw_artifacts
                ),
                *original.dataset_metadata,
            ]
        )
    )

    with pytest.raises(
        ValueError,
        match="differs from frozen G10 protocol",
    ):
        verify_public_performance_evidence_package(output)


def test_dataset_metadata_is_absent_by_default_and_bound_when_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    monkeypatch.setattr(exporter, "PUBLIC_ROOT", public_root)
    source_path = "data/enterprise_bundle/manifest.json"
    output = exporter.export_completed_experiment(
        completed_experiment_id="EXP-LC-006",
        output_directory=public_root / "g10-package-with-dataset",
        dataset_metadata_paths=[source_path],
    )

    manifest = LifecyclePerformanceEvidencePackageManifest.model_validate_json(
        (output / "manifest.json").read_bytes()
    )
    assert len(manifest.dataset_metadata) == 1
    metadata = manifest.dataset_metadata[0]
    assert metadata.path == f"dataset/{source_path}"
    assert (output / metadata.path).read_bytes() == (
        REPOSITORY_ROOT / source_path
    ).read_bytes()
    assert verify_public_performance_evidence_package(output).pair_count == 10


@pytest.mark.parametrize(
    ("artifact_suffix", "tamper_kind", "message"),
    [
        (
            "/environment.json",
            "environment",
            "mixed configuration identity",
        ),
        ("/status.json", "status", "pair counts"),
        (
            "/pairs.jsonl",
            "measurement",
            "mixed configuration_sha256 identity",
        ),
    ],
)
def test_package_semantic_tamper_is_rejected_after_all_hashes_are_rebound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_suffix: str,
    tamper_kind: str,
    message: str,
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    monkeypatch.setattr(exporter, "PUBLIC_ROOT", public_root)
    output = exporter.export_completed_experiment(
        completed_experiment_id="EXP-LC-006",
        output_directory=public_root / f"g10-package-{tamper_kind}",
    )
    manifest = LifecyclePerformanceEvidencePackageManifest.model_validate_json(
        (output / "manifest.json").read_bytes()
    )
    raw = next(
        output / item.package_file.path
        for item in manifest.raw_artifacts
        if item.source_path.endswith(artifact_suffix)
    )
    if tamper_kind == "environment":
        payload = json.loads(raw.read_text(encoding="utf-8"))
        payload["configuration_sha256"] = "0" * 64
        content = json.dumps(payload, sort_keys=True).encode("utf-8")
    elif tamper_kind == "status":
        payload = json.loads(raw.read_text(encoding="utf-8"))
        payload["completed_pairs"] = 9
        content = json.dumps(payload, sort_keys=True).encode("utf-8")
    else:
        rows = [
            json.loads(line)
            for line in raw.read_text(encoding="utf-8").splitlines()
        ]
        for row in rows:
            row["baseline"]["configuration_sha256"] = "0" * 64
            row["intervention"]["configuration_sha256"] = "0" * 64
        content = (
            "\n".join(
                json.dumps(row, sort_keys=True, separators=(",", ":"))
                for row in rows
            )
            + "\n"
        ).encode("utf-8")
    _rebind_packaged_raw_artifact(output, artifact_suffix, content)

    with pytest.raises(ValueError, match=message):
        verify_public_performance_evidence_package(output)


def test_verifier_cli_recomputes_exported_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    monkeypatch.setattr(exporter, "PUBLIC_ROOT", public_root)
    output = exporter.export_completed_experiment(
        completed_experiment_id="EXP-LC-006",
        output_directory=public_root / "g10-package-cli",
    )

    assert verifier_cli.main(["--package-dir", str(output)]) == 0
    assert capsys.readouterr().out == (
        "verified EXP-LC-006: 10 pairs, SUPPORTED\n"
    )
