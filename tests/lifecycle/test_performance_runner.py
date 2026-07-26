from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.domain.documents import DocumentRecord, DocumentVersion
from app.lifecycle import performance_runner
from app.lifecycle.performance_bundle import generate_performance_bundle
from app.lifecycle.performance_runner import (
    PerformanceRunnerError,
    clone_arm_workspace,
    host_identity_sha256,
    measure_performance_arm,
    prepare_arm_workspace,
    runner_configuration_descriptor,
    runner_configuration_sha256,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_runner_configuration_binds_transitive_source_and_dependencies(
    tmp_path: Path,
) -> None:
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        (tmp_path / "bundle").absolute(),
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )

    descriptor = runner_configuration_descriptor(bundle)
    source_paths = set(performance_runner.runner_source_paths())

    assert descriptor["schema_version"] == "g10_runner_configuration_v2"
    assert descriptor["source_file_count"] == len(source_paths)
    assert descriptor["source_tree_sha256"]
    assert descriptor["requirements_sha256"]
    assert descriptor["runtime_dependency_versions"]["pydantic"]
    assert {
        "app/filesystem.py",
        "app/indexing/change_plan.py",
        "app/indexing/store.py",
        "app/ingestion/revision_catalog.py",
        "app/observability/metrics.py",
        "app/retrieval/pipeline.py",
        "app/retrieval/snapshot.py",
        "scripts/benchmark_lifecycle_incremental.py",
    }.issubset(source_paths)


def _document(number: int) -> DocumentRecord:
    text = (
        f"Lifecycle runner document {number:04d} "
        f"unique-token-{number:04d}."
    )
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return DocumentRecord(
        doc_id=f"runner-doc-{number:04d}",
        title=f"Runner Document {number:04d}",
        source_type="policy",
        source_path=f"runner/policy-{number:04d}.md",
        format="markdown",
        department="Engineering",
        filed_department="Engineering",
        policy_id=f"runner-policy-{number:04d}",
        region="global",
        tenant_id="runner-tenant",
        acl_groups=["employees"],
        document_version=DocumentVersion(
            version_id=f"runner-version-{number:04d}",
            version="1",
            status="active",
            effective_from=date(2026, 1, 1),
            authority_level=80,
        ),
        authority_level=80,
        checksum=text_sha256,
        normalized_text_hash=text_sha256,
        ingested_at=NOW,
        parser_name="fixture-markdown",
        parser_version="1",
        text=text,
        fact_ids=[f"runner-fact-{number:04d}"],
        variant="canonical",
    )


def test_cold_and_warm_arms_use_the_same_production_target_path(
    tmp_path: Path,
) -> None:
    bundle = generate_performance_bundle(
        [_document(number) for number in range(1, 13)],
        (tmp_path / "bundle").absolute(),
        content_update_count=3,
        acl_only_count=2,
        delete_count=1,
    )
    template_root = (tmp_path / "template").absolute()
    prepare_arm_workspace(
        bundle=bundle,
        workspace_root=template_root,
    )
    with pytest.raises(
        PerformanceRunnerError,
        match="disjoint sibling trees",
    ):
        clone_arm_workspace(
            bundle=bundle,
            template_root=template_root,
            workspace_root=template_root,
        )
    with pytest.raises(
        PerformanceRunnerError,
        match="disjoint sibling trees",
    ):
        clone_arm_workspace(
            bundle=bundle,
            template_root=template_root,
            workspace_root=template_root / "nested-arm",
        )
    baseline_root = (tmp_path / "baseline").absolute()
    intervention_root = (tmp_path / "intervention").absolute()
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
    assert baseline_prestate.base_index_prestate_sha256 == (
        intervention_prestate.base_index_prestate_sha256
    )
    assert baseline_prestate.base_cache_prestate_sha256 == (
        intervention_prestate.base_cache_prestate_sha256
    )
    host_sha256 = host_identity_sha256()
    configuration_sha256 = runner_configuration_sha256(bundle)
    coordinator_pid = os.getpid() + 1_000_000

    baseline = measure_performance_arm(
        bundle_root=bundle.root,
        expected_bundle_manifest_sha256=bundle.manifest_sha256,
        workspace_root=baseline_root,
        experiment_id="exp-g10-runner-test",
        pair_number=1,
        arm="baseline",
        execution_order=1,
        coordinator_process_id=coordinator_pid,
        expected_host_identity_sha256=host_sha256,
        expected_configuration_sha256=configuration_sha256,
    )
    intervention = measure_performance_arm(
        bundle_root=bundle.root,
        expected_bundle_manifest_sha256=bundle.manifest_sha256,
        workspace_root=intervention_root,
        experiment_id="exp-g10-runner-test",
        pair_number=1,
        arm="intervention",
        execution_order=2,
        coordinator_process_id=coordinator_pid,
        expected_host_identity_sha256=host_sha256,
        expected_configuration_sha256=configuration_sha256,
    )

    assert baseline.cache_statistics.parsed_misses == 11
    assert baseline.cache_statistics.embedding_misses == 11
    assert intervention.cache_statistics.parsed_misses == 3
    assert intervention.cache_statistics.parsed_hits == 8
    assert intervention.cache_statistics.embedding_misses == 3
    assert intervention.cache_statistics.embedding_hits == 8
    assert baseline.target_fingerprint == intervention.target_fingerprint
    assert (
        baseline.target_fingerprint.active_index_deleted_residual_count
        == 0
    )
    assert baseline.total_wall_seconds > 0
    assert intervention.total_wall_seconds > 0
