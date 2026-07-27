from __future__ import annotations

import hashlib
import json
import sys
import warnings
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.documents import DocumentRecord, DocumentVersion
from app.lifecycle.evidence import (
    ExperimentRecord,
    ExperimentStatus,
    append_jsonl_record,
    load_jsonl_records,
)
from app.lifecycle.performance_bundle import generate_performance_bundle
from app.lifecycle.performance_runner import (
    PerformanceRunnerError,
    host_identity_sha256,
    runner_environment_identity,
    runner_configuration_sha256,
)
from scripts import benchmark_lifecycle_incremental as cli


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _document(number: int) -> DocumentRecord:
    text = f"CLI benchmark document {number:04d} unique token {number:04d}."
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return DocumentRecord(
        doc_id=f"cli-doc-{number:04d}",
        title=f"CLI Document {number:04d}",
        source_type="policy",
        source_path=f"cli/policy-{number:04d}.md",
        format="markdown",
        department="Engineering",
        filed_department="Engineering",
        policy_id=f"cli-policy-{number:04d}",
        region="global",
        tenant_id="cli-tenant",
        acl_groups=["employees"],
        document_version=DocumentVersion(
            version_id=f"cli-version-{number:04d}",
            version="1",
            status="active",
            effective_from=date(2026, 1, 1),
            authority_level=80,
        ),
        authority_level=80,
        checksum=digest,
        normalized_text_hash=digest,
        ingested_at=NOW,
        parser_name="fixture-markdown",
        parser_version="1",
        text=text,
        fact_ids=[f"cli-fact-{number:04d}"],
        variant="canonical",
    )


def test_run_refuses_to_create_work_before_matching_registration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_root = (tmp_path / "private").absolute()
    artifact_root = (tmp_path / "artifacts").absolute()
    private_root.mkdir()
    artifact_root.mkdir()
    experiments = tmp_path / "EXPERIMENTS.jsonl"
    experiments.write_bytes(b"")
    bundle_root = private_root / "bundle"
    generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        bundle_root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    monkeypatch.setattr(cli, "PRIVATE_ROOT", private_root)
    monkeypatch.setattr(cli, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(cli, "EXPERIMENTS_PATH", experiments)

    exit_code = cli.main(
        [
            "run",
            "--bundle-dir",
            str(bundle_root),
            "--run-id",
            "g10-unregistered-test",
            "--experiment-id",
            "EXP-LC-900",
            "--running-id",
            "EXP-LC-901",
            "--completed-id",
            "EXP-LC-902",
            "--repetitions",
            "10",
        ]
    )

    assert exit_code == 2
    assert not (private_root / "g10-unregistered-test").exists()
    assert not (artifact_root / "g10-unregistered-test").exists()


def test_pair_worker_rejects_result_outside_its_pair_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_root = (tmp_path / "private").absolute()
    artifact_root = (tmp_path / "artifacts").absolute()
    run_work_root = private_root / "g10-boundary-test"
    template_root = run_work_root / "base-template"
    pair_artifact = artifact_root / run_work_root.name / "pairs" / "001"
    template_root.mkdir(parents=True)
    pair_artifact.mkdir(parents=True)
    bundle_root = private_root / "bundle"
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        bundle_root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    monkeypatch.setattr(cli, "PRIVATE_ROOT", private_root)
    monkeypatch.setattr(cli, "ARTIFACT_ROOT", artifact_root)

    args = Namespace(
        bundle_dir=bundle_root,
        bundle_sha256=bundle.manifest_sha256,
        run_work_root=run_work_root,
        base_template=template_root,
        pair_artifact_dir=pair_artifact,
        result_file=artifact_root / "misbound.json",
        experiment_id="EXP-LC-900",
        pair_number=1,
    )

    try:
        cli._pair_worker(args)
    except ValueError as exc:
        assert "pair artifact paths" in str(exc)
    else:
        raise AssertionError("misbound pair result was accepted")
    assert not (run_work_root / "pair-001").exists()


def test_public_command_removes_machine_absolute_paths() -> None:
    command = [
        sys.executable,
        "-m",
        "scripts.benchmark_lifecycle_incremental",
        "--bundle-dir",
        str(cli.BASE_DIR / ".private" / "lifecycle" / "bundle"),
        "--external",
        str(Path.home() / "outside-repository"),
    ]

    rendered = cli._public_command(command)

    assert str(Path(sys.executable).resolve()) not in rendered
    assert str(cli.BASE_DIR.resolve()) not in rendered
    assert "python" in rendered
    assert ".private/lifecycle/bundle" in rendered
    assert "<external-path>" in rendered


def test_formal_run_requires_runner_sources_to_match_commit(
    monkeypatch,
) -> None:
    responses = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout="a" * 40 + "\n",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=" M app/lifecycle/performance_runner.py\n",
            ),
        ]
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(
        RuntimeError,
        match="sources differ from the source commit",
    ):
        cli._source_commit_sha(require_clean_runner=True)


@pytest.mark.parametrize(
    "failure_code",
    ["expected_query_miss", "acl_query_leak"],
)
def test_arm_worker_records_query_failure_as_correctness_failure(
    tmp_path: Path,
    monkeypatch,
    failure_code: str,
) -> None:
    private_root = (tmp_path / "private").absolute()
    artifact_root = (tmp_path / "artifacts").absolute()
    bundle_root = private_root / "bundle"
    workspace = private_root / "run" / "pair-001" / "baseline"
    result_root = artifact_root / "run" / "pairs" / "001"
    bundle_root.mkdir(parents=True)
    workspace.mkdir(parents=True)
    result_root.mkdir(parents=True)
    monkeypatch.setattr(cli, "PRIVATE_ROOT", private_root)
    monkeypatch.setattr(cli, "ARTIFACT_ROOT", artifact_root)

    def fail_measurement(**_kwargs):
        raise PerformanceRunnerError(
            failure_code,
            "fixture query miss",
        )

    monkeypatch.setattr(cli, "measure_performance_arm", fail_measurement)
    args = Namespace(
        bundle_dir=bundle_root,
        workspace=workspace,
        result_file=result_root / "baseline.json",
        bundle_sha256="a" * 64,
        experiment_id="EXP-LC-900",
        pair_number=1,
        arm="baseline",
        execution_order=1,
        coordinator_process_id=999_999,
        host_sha256="b" * 64,
        configuration_sha256="c" * 64,
    )

    with pytest.raises(PerformanceRunnerError, match=failure_code):
        cli._arm_worker(args)

    failure = json.loads(
        (result_root / "baseline-failure.json").read_text(encoding="utf-8")
    )
    assert failure == {
        "schema_version": "g10_arm_failure_v1",
        "failure_kind": "correctness_mismatch",
        "failure_code": failure_code,
    }


def _registered_record(bundle) -> ExperimentRecord:
    runner_identity = runner_environment_identity(bundle)
    return ExperimentRecord(
        experiment_id="EXP-LC-910",
        registered_at=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
        status=ExperimentStatus.REGISTERED,
        hypothesis="Warm reuse should reduce complete target build time.",
        baseline="Cold target computation cache.",
        intervention="Warm production base computation cache.",
        controlled_variables=["bundle", "pipeline", "host"],
        dataset_id="g10-cli-terminal-fixture",
        dataset_sha256=bundle.manifest_sha256,
        sample_size=12,
        repetitions=10,
        metrics=["paired total wall-time ratio"],
        success_thresholds={
            "active_index_deletion_residual_count": 0,
            "correctness_equivalent_pairs": 10,
            "faster_pair_count_at_least": 8,
            "intervention_embedding_call_ratio_at_most": 0.10,
            "median_total_time_ratio_at_most": 0.75,
        },
        failure_thresholds={
            "any_active_index_deletion_residual": True,
            "any_correctness_mismatch": True,
            "infrastructure_failure_status": "INCONCLUSIVE",
            "median_total_time_ratio_regression_at_or_above": 1.05,
            "unrepresentable_frozen_dataset_status": "BLOCKED",
        },
        environment={
            "registered_experiment_id": "EXP-LC-910",
            "host_identity_sha256": host_identity_sha256(),
            "source_commit_sha": cli._source_commit_sha(),
            **runner_identity,
        },
        commands=["python -m scripts.benchmark_lifecycle_incremental run"],
    )


def test_registration_rejects_posthoc_threshold_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    experiments = tmp_path / "EXPERIMENTS.jsonl"
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        (tmp_path / "bundle").absolute(),
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    registered = _registered_record(bundle)
    changed_success = dict(registered.success_thresholds)
    changed_success["median_total_time_ratio_at_most"] = 0.76
    append_jsonl_record(
        experiments,
        record=registered.model_copy(
            update={"success_thresholds": changed_success}
        ),
        model=ExperimentRecord,
        id_field="experiment_id",
    )
    monkeypatch.setattr(cli, "EXPERIMENTS_PATH", experiments)

    with pytest.raises(
        ValueError,
        match="differ from the frozen G10 protocol",
    ):
        cli._registered_experiment(
            experiment_id=registered.experiment_id,
            bundle_sha256=bundle.manifest_sha256,
            repetitions=10,
            host_sha256=host_identity_sha256(),
            configuration_sha256=runner_configuration_sha256(bundle),
            source_commit_sha=cli._source_commit_sha(),
            runner_identity=runner_environment_identity(bundle),
        )


def test_registration_record_binds_v2_source_and_protocol_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path.absolute()
    monkeypatch.setattr(cli, "BASE_DIR", base_dir)
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        base_dir / "bundle",
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    registered_at = datetime(
        2026,
        7,
        27,
        9,
        0,
        tzinfo=timezone.utc,
    )

    record = cli._build_registration_record(
        bundle=bundle,
        experiment_id="EXP-LC-930",
        running_id="EXP-LC-931",
        completed_id="EXP-LC-932",
        run_id="g10-v2-registration-test",
        repetitions=10,
        source_commit_sha="b" * 40,
        registered_at=registered_at,
        source_manifest_sha256="c" * 64,
    )

    assert record.schema_version == 2
    assert record.registered_at == registered_at
    assert record.started_at is None
    assert record.completed_at is None
    assert record.environment["registered_experiment_id"] == "EXP-LC-930"
    assert record.environment["source_commit_sha"] == "b" * 40
    assert record.environment["source_tree_sha256"]
    assert record.environment["runtime_dependencies_sha256"]
    assert record.success_thresholds[
        "median_total_time_ratio_at_most"
    ] == 0.75
    assert record.failure_thresholds[
        "median_total_time_ratio_regression_at_or_above"
    ] == 1.05
    assert "complete changed target" in record.baseline
    assert "raw-file admission" in record.baseline
    assert "outside the measured operation" in record.baseline
    assert "EXP-LC-931" in record.commands[-1]
    assert "EXP-LC-932" in record.commands[-1]


def test_started_run_closes_experiment_when_base_preparation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base_dir = tmp_path.absolute()
    private_root = base_dir / ".private" / "lifecycle"
    artifact_root = base_dir / "artifacts" / "lifecycle"
    experiments = base_dir / "docs" / "lifecycle" / "EXPERIMENTS.jsonl"
    source_corpus = base_dir / "data" / "source"
    private_root.mkdir(parents=True)
    artifact_root.mkdir(parents=True)
    experiments.parent.mkdir(parents=True)
    source_corpus.mkdir(parents=True)
    (source_corpus / "manifest.json").write_text(
        json.dumps({"fixture": True}),
        encoding="utf-8",
    )
    bundle_root = private_root / "bundle"
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        bundle_root,
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    registered = _registered_record(bundle)
    append_jsonl_record(
        experiments,
        record=registered,
        model=ExperimentRecord,
        id_field="experiment_id",
    )
    monkeypatch.setattr(cli, "BASE_DIR", base_dir)
    monkeypatch.setattr(cli, "PRIVATE_ROOT", private_root)
    monkeypatch.setattr(cli, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(cli, "EXPERIMENTS_PATH", experiments)
    monkeypatch.setattr(cli, "SOURCE_CORPUS", source_corpus)
    monkeypatch.setattr(
        cli,
        "_source_commit_sha",
        lambda **_kwargs: str(
            registered.environment["source_commit_sha"]
        ),
    )

    def fail_base_preparation(**_kwargs) -> None:
        raise RuntimeError("injected base preparation failure")

    monkeypatch.setattr(cli, "prepare_arm_workspace", fail_base_preparation)

    exit_code = cli.main(
        [
            "run",
            "--bundle-dir",
            str(bundle_root),
            "--run-id",
            "g10-terminal-test",
            "--experiment-id",
            "EXP-LC-910",
            "--running-id",
            "EXP-LC-911",
            "--completed-id",
            "EXP-LC-912",
            "--repetitions",
            "10",
        ]
    )

    assert exit_code == 2
    records = load_jsonl_records(experiments, ExperimentRecord)
    assert [record.status.value for record in records] == [
        "REGISTERED",
        "RUNNING",
        "COMPLETED",
    ]
    assert records[-1].final_status.value == "INCONCLUSIVE"
    assert records[-1].result_summary == {
        "completed_pairs": 0,
        "failure_stage": "base_template_preparation",
        "failure_code": "infrastructure_failure",
    }
    status = json.loads(
        (
            artifact_root / "g10-terminal-test" / "status.json"
        ).read_text(encoding="utf-8")
    )
    assert status["status"] == "INCONCLUSIVE"


def test_completed_experiment_serializes_final_status_as_enum(
    tmp_path: Path,
    monkeypatch,
) -> None:
    experiments = tmp_path / "docs" / "lifecycle" / "EXPERIMENTS.jsonl"
    experiments.parent.mkdir(parents=True)
    artifact = tmp_path / "artifacts" / "summary.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cli, "EXPERIMENTS_PATH", experiments)
    distribution = SimpleNamespace(p50=0.7, p95=0.8)
    summary = SimpleNamespace(
        pair_count=10,
        total_time_ratio=distribution,
        faster_pair_count=10,
        intervention_embedding_call_ratio=0.02,
        baseline_peak_rss_bytes=400,
        intervention_peak_rss_bytes=350,
        baseline_first_total_time_ratio=distribution,
        intervention_first_total_time_ratio=distribution,
        decision="SUPPORTED",
    )
    registered = ExperimentRecord(
        experiment_id="EXP-LC-920",
        registered_at=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
        status=ExperimentStatus.REGISTERED,
        hypothesis="Warm reuse should preserve correctness and reduce time.",
        baseline="Cold target cache.",
        intervention="Warm target cache.",
        controlled_variables=["dataset"],
        dataset_id="fixture",
        dataset_sha256="a" * 64,
        sample_size=12,
        repetitions=10,
        metrics=["time"],
        success_thresholds={"ratio": 0.75},
        failure_thresholds={"ratio": 1.05},
        environment={"mode": "fixture"},
        commands=["python fixture.py"],
    )

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        cli._append_completed(
            registered,
            completed_id="EXP-LC-921",
            summary=summary,
            artifact_paths=[artifact],
        )

    assert not [
        item
        for item in captured
        if "PydanticSerializationUnexpectedValue" in str(item.message)
    ]
    completed = load_jsonl_records(experiments, ExperimentRecord)[0]
    assert completed.final_status.value == "SUPPORTED"
