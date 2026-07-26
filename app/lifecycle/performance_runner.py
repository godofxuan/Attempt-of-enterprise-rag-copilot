from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.indexing.benchmark import deterministic_embedding
from app.indexing.change_plan import build_change_plan
from app.indexing.computation_cache import (
    ComponentFingerprint,
    EmbeddingFingerprint,
    PersistentComputationCache,
)
from app.indexing.incremental_computation import (
    PipelineConfiguration,
    execute_incremental_computation,
    pipeline_configuration_sha256,
)
from app.indexing.incremental_snapshot import (
    build_incremental_index_version,
    validate_incremental_index_directory,
)
from app.indexing.paired_performance import (
    PairedArmMeasurement,
    TargetEquivalenceFingerprint,
)
from app.indexing.store import load_active_pointer, load_index_version
from app.ingestion.chunking import ChunkerConfig
from app.ingestion.path_security import (
    absolute_path_has_redirect,
    stat_is_redirect,
)
from app.ingestion.revision_catalog import (
    empty_revision_catalog_snapshot,
    revision_catalog_sha256,
)
from app.lifecycle.performance_bundle import (
    LoadedPerformanceBundle,
    PerformanceBundleRevisionContentMaterializer,
    load_performance_bundle,
)
from app.observability.metrics import process_peak_rss_bytes
from app.retrieval.pipeline import HybridRetrievalPipeline
from app.retrieval.snapshot import V2IndexSnapshot


ArmName = Literal["baseline", "intervention"]
BASE_RUN_ID = "g10-base"
TARGET_RUN_ID = "g10-target"
FIXED_BUILD_TIME = datetime(2026, 7, 27, tzinfo=timezone.utc)
EMBEDDING_MODEL = "deterministic-shake256-128"
_RUNNER_ENTRYPOINTS = (
    "scripts/benchmark_lifecycle_incremental.py",
)
_RUNTIME_DISTRIBUTIONS = (
    "faiss-cpu",
    "jieba",
    "numpy",
    "pydantic",
    "rank-bm25",
)


class PerformanceRunnerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class PerformanceRunnerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class ArmWorkspacePrestate(PerformanceRunnerModel):
    schema_version: Literal["arm_workspace_prestate_v1"] = (
        "arm_workspace_prestate_v1"
    )
    workspace_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_index_prestate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_cache_prestate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _implementation_sha256(*relative_paths: str) -> str:
    repository = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for relative_path in sorted(relative_paths):
        content = (repository / relative_path).read_bytes()
        digest.update(relative_path.encode("ascii"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def runner_source_paths() -> tuple[str, ...]:
    repository = Path(__file__).resolve().parents[2]
    app_root = repository / "app"
    paths = [
        path.relative_to(repository).as_posix()
        for path in app_root.rglob("*.py")
        if path.is_file() and not path.is_symlink()
    ]
    paths.extend(_RUNNER_ENTRYPOINTS)
    canonical = tuple(sorted(paths))
    if len(canonical) != len(set(canonical)):
        raise RuntimeError("runner source manifest contains duplicate paths")
    for relative_path in canonical:
        path = repository / relative_path
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(
                f"runner source is not a regular file: {relative_path}"
            )
    return canonical


def _runtime_dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in _RUNTIME_DISTRIBUTIONS:
        try:
            versions[distribution] = version(distribution)
        except PackageNotFoundError as exc:
            raise RuntimeError(
                f"required runtime distribution is missing: {distribution}"
            ) from exc
    return versions


def runner_configuration_descriptor(
    bundle: LoadedPerformanceBundle,
) -> Mapping[str, object]:
    repository = Path(__file__).resolve().parents[2]
    requirements = repository / "requirements.txt"
    if requirements.is_symlink() or not requirements.is_file():
        raise RuntimeError("requirements.txt is not a regular file")
    source_paths = runner_source_paths()
    pipeline = build_performance_pipeline(bundle)
    return {
        "schema_version": "g10_runner_configuration_v2",
        "source_tree_sha256": _implementation_sha256(*source_paths),
        "source_file_count": len(source_paths),
        "source_paths_sha256": _sha256(
            _canonical_json_bytes(list(source_paths))
        ),
        "requirements_sha256": _sha256(requirements.read_bytes()),
        "runtime_dependency_versions": _runtime_dependency_versions(),
        "pipeline": pipeline.model_dump(mode="json"),
        "base_run_id": BASE_RUN_ID,
        "target_run_id": TARGET_RUN_ID,
        "fixed_build_time": FIXED_BUILD_TIME.isoformat(),
        "embedding_model": EMBEDDING_MODEL,
    }


def build_performance_pipeline(
    bundle: LoadedPerformanceBundle,
) -> PipelineConfiguration:
    parser = bundle.manifest.pipeline.parser
    return PipelineConfiguration(
        materializer=ComponentFingerprint(
            name="g10-performance-bundle-materializer",
            semantic_version="1",
            implementation_sha256=_implementation_sha256(
                "app/lifecycle/performance_bundle.py",
            ),
        ),
        governance=ComponentFingerprint(
            name="govern-documents",
            semantic_version="1",
            implementation_sha256=_implementation_sha256(
                "app/ingestion/versions.py",
            ),
        ),
        normalizer=ComponentFingerprint(
            name=bundle.manifest.pipeline.normalizer_name,
            semantic_version=bundle.manifest.pipeline.normalizer_version,
            implementation_sha256=parser.implementation_sha256,
        ),
        chunker=ComponentFingerprint(
            name="fixed-chunker",
            semantic_version="1",
            implementation_sha256=_implementation_sha256(
                "app/ingestion/chunking.py",
            ),
        ),
        chunker_config=ChunkerConfig(
            mode="fixed",
            chunk_size=500,
            overlap=80,
        ),
        embedding=EmbeddingFingerprint(
            component=ComponentFingerprint(
                name="deterministic-shake256-embedder",
                semantic_version="1",
                implementation_sha256=_implementation_sha256(
                    "app/indexing/benchmark.py",
                ),
            ),
            backend="deterministic-local",
            model_identifier=EMBEDDING_MODEL,
            model_sha256=_implementation_sha256(
                "app/indexing/benchmark.py",
            ),
            dimension=128,
            normalization="l2",
        ),
    )


def runner_configuration_sha256(
    bundle: LoadedPerformanceBundle,
) -> str:
    return _sha256(
        _canonical_json_bytes(runner_configuration_descriptor(bundle))
    )


def runner_environment_identity(
    bundle: LoadedPerformanceBundle,
) -> dict[str, str | int]:
    descriptor = runner_configuration_descriptor(bundle)
    return {
        "configuration_sha256": _sha256(
            _canonical_json_bytes(descriptor)
        ),
        "source_tree_sha256": str(descriptor["source_tree_sha256"]),
        "source_file_count": int(descriptor["source_file_count"]),
        "source_paths_sha256": str(descriptor["source_paths_sha256"]),
        "requirements_sha256": str(descriptor["requirements_sha256"]),
        "runtime_dependencies_sha256": _sha256(
            _canonical_json_bytes(
                descriptor["runtime_dependency_versions"]
            )
        ),
        "pipeline_sha256": pipeline_configuration_sha256(
            build_performance_pipeline(bundle)
        ),
    }


def host_identity_sha256() -> str:
    payload = {
        "schema_version": "g10_host_identity_v1",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    return _sha256(_canonical_json_bytes(payload))


def _workspace_identity(root: Path) -> str:
    return _sha256(str(root.resolve()).encode("utf-8"))


def _validate_absolute_workspace(root: Path, *, require_empty: bool) -> Path:
    root = Path(root)
    if not root.is_absolute():
        raise PerformanceRunnerError(
            "workspace_not_absolute",
            "Performance workspaces must use absolute paths.",
        )
    if absolute_path_has_redirect(root):
        raise PerformanceRunnerError(
            "workspace_unsafe",
            "Performance workspace ancestry contains a redirect.",
        )
    if root.exists():
        metadata = root.lstat()
        if stat_is_redirect(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise PerformanceRunnerError(
                "workspace_unsafe",
                "Performance workspace is not a regular directory.",
            )
        if require_empty and next(root.iterdir(), None) is not None:
            raise PerformanceRunnerError(
                "workspace_not_empty",
                "Performance workspace must be empty.",
            )
    return root.resolve()


def _tree_sha256(root: Path) -> str:
    root = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat_is_redirect(metadata):
            raise PerformanceRunnerError(
                "prestate_unsafe",
                "Performance prestate contains a redirect.",
            )
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(b"D\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\n")
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise PerformanceRunnerError(
                "prestate_unsafe",
                "Performance prestate contains a non-regular or linked file.",
            )
        content = path.read_bytes()
        digest.update(b"F\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(hashlib.sha256(content).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _base_index_prestate_sha256(index_root: Path) -> str:
    version = load_index_version(index_root, BASE_RUN_ID)
    pointer = load_active_pointer(index_root)
    payload = {
        "schema_version": "g10_base_index_prestate_v1",
        "base_version_tree_sha256": _tree_sha256(version.path),
        "active_run_id": pointer.run_id,
        "active_manifest_sha256": pointer.manifest_sha256,
    }
    return _sha256(_canonical_json_bytes(payload))


def _base_prestate(
    *,
    bundle: LoadedPerformanceBundle,
    workspace: Path,
    pipeline: PipelineConfiguration,
) -> ArmWorkspacePrestate:
    index_root = workspace / "index"
    cache_root = workspace / "base-cache"
    base = load_index_version(index_root, BASE_RUN_ID)
    lifecycle = validate_incremental_index_directory(base.path)
    if (
        lifecycle.target_catalog_sha256
        != revision_catalog_sha256(bundle.base_catalog)
        or load_active_pointer(index_root).run_id != BASE_RUN_ID
    ):
        raise PerformanceRunnerError(
            "base_prestate_mismatch",
            "Workspace base index does not bind the frozen base catalog.",
        )
    return ArmWorkspacePrestate(
        workspace_identity_sha256=_workspace_identity(workspace),
        bundle_manifest_sha256=bundle.manifest_sha256,
        base_catalog_sha256=revision_catalog_sha256(bundle.base_catalog),
        pipeline_sha256=pipeline_configuration_sha256(pipeline),
        base_manifest_sha256=base.manifest_sha256,
        base_index_prestate_sha256=_base_index_prestate_sha256(index_root),
        base_cache_prestate_sha256=_tree_sha256(cache_root),
    )


def prepare_arm_workspace(
    *,
    bundle: LoadedPerformanceBundle,
    workspace_root: Path,
) -> ArmWorkspacePrestate:
    workspace = _validate_absolute_workspace(
        workspace_root,
        require_empty=True,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    pipeline = build_performance_pipeline(bundle)
    cache = PersistentComputationCache((workspace / "base-cache").absolute())
    base_plan = build_change_plan(
        base=empty_revision_catalog_snapshot(),
        target=bundle.base_catalog,
        base_index_run_id=None,
        target_index_run_id=BASE_RUN_ID,
    )
    computation = execute_incremental_computation(
        plan=base_plan,
        base_catalog=None,
        target_catalog=bundle.base_catalog,
        cache=cache,
        pipeline=pipeline,
        materializer=PerformanceBundleRevisionContentMaterializer(
            bundle,
            role="base",
        ),
        embed_text=deterministic_embedding,
    )
    publication = build_incremental_index_version(
        root=(workspace / "index").absolute(),
        plan=base_plan,
        base_catalog=None,
        target_catalog=bundle.base_catalog,
        computation=computation,
        pipeline=pipeline,
        profile_id="g10-paired-performance",
        activate=True,
        started_at=FIXED_BUILD_TIME,
        finished_at=FIXED_BUILD_TIME,
    )
    if publication.status != "BUILT" or not publication.activated:
        raise PerformanceRunnerError(
            "base_preparation_reused",
            "A fresh base workspace did not produce a new active snapshot.",
        )
    return _base_prestate(
        bundle=bundle,
        workspace=workspace,
        pipeline=pipeline,
    )


def clone_arm_workspace(
    *,
    bundle: LoadedPerformanceBundle,
    template_root: Path,
    workspace_root: Path,
) -> ArmWorkspacePrestate:
    template = _validate_absolute_workspace(
        template_root,
        require_empty=False,
    )
    if {item.name for item in template.iterdir()} != {
        "base-cache",
        "index",
    }:
        raise PerformanceRunnerError(
            "base_template_shape_invalid",
            "Base template must contain exactly the cache and index roots.",
        )
    pipeline = build_performance_pipeline(bundle)
    _base_prestate(
        bundle=bundle,
        workspace=template,
        pipeline=pipeline,
    )
    destination = _validate_absolute_workspace(
        workspace_root,
        require_empty=False,
    )
    if (
        destination == template
        or destination.is_relative_to(template)
        or template.is_relative_to(destination)
    ):
        raise PerformanceRunnerError(
            "base_template_workspace_overlap",
            "Base template and arm workspace must be disjoint sibling trees.",
        )
    destination = _validate_absolute_workspace(
        destination,
        require_empty=True,
    )
    if destination.exists():
        destination.rmdir()
    try:
        shutil.copytree(template, destination, symlinks=True)
    except OSError as exc:
        raise PerformanceRunnerError(
            "base_template_copy_failed",
            "Base template could not be copied to an isolated arm.",
        ) from exc
    try:
        with PersistentComputationCache(
            (destination / "base-cache").absolute()
        ).transaction():
            pass
        return _base_prestate(
            bundle=bundle,
            workspace=destination,
            pipeline=pipeline,
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _query_results(
    bundle: LoadedPerformanceBundle,
    *,
    index_root: Path,
) -> tuple[str, list[dict[str, object]]]:
    snapshot = V2IndexSnapshot.load(index_root, TARGET_RUN_ID)
    retrieval = HybridRetrievalPipeline(snapshot)
    payload: list[dict[str, object]] = []
    for case in bundle.query_descriptor.cases:
        result = retrieval.search(case.request)
        hits = []
        for rank, hit in enumerate(result.hits, start=1):
            hits.append(
                {
                    "rank": rank,
                    "chunk_id": hit.chunk_id,
                    "doc_id": hit.doc_id,
                    "parent_chunk_id": hit.parent_chunk_id,
                    "source_path": hit.source_path,
                    "section_path": hit.section_path,
                    "locator": (
                        None
                        if hit.locator is None
                        else hit.locator.model_dump(mode="json")
                    ),
                    "context_from_parent": hit.context_from_parent,
                    "tenant_id": hit.tenant_id,
                    "region": hit.region,
                    "acl_groups": hit.acl_groups,
                    "version_id": hit.version_id,
                    "version": hit.version,
                    "authority_level": hit.authority_level,
                    "fused_score": hit.fused_score,
                    "dense_score": hit.dense_score,
                    "bm25_score": hit.bm25_score,
                    "dense_rank": hit.dense_rank,
                    "bm25_rank": hit.bm25_rank,
                }
            )
        doc_ids = {hit["doc_id"] for hit in hits}
        if case.expectation == "absent_from_target":
            if case.expected_doc_id in doc_ids:
                raise PerformanceRunnerError(
                    "deleted_query_residual",
                    "A frozen deletion query returned the deleted document.",
                )
        elif case.expectation == "denied_by_acl":
            if case.expected_doc_id in doc_ids:
                raise PerformanceRunnerError(
                    "acl_query_leak",
                    "A frozen ACL denial query returned the protected document.",
                )
        elif case.expected_doc_id not in doc_ids:
            raise PerformanceRunnerError(
                "expected_query_miss",
                "A frozen live query did not return its expected document.",
            )
        payload.append(
            {
                "query_id": case.query_id,
                "category": case.category,
                "expectation": case.expectation,
                "denial_dimension": case.denial_dimension,
                "request": case.request.model_dump(mode="json"),
                "result": {
                    "request_id": result.request_id,
                    "query": result.query,
                    "mode": result.mode,
                    "index_run_id": result.index_run_id,
                    "manifest_sha256": result.manifest_sha256,
                    "visible_candidate_count": result.visible_candidate_count,
                    "internal_denied_count": result.internal_denied_count,
                    "stage_counts": dict(sorted(result.stage_counts.items())),
                    "stop_reason": result.stop_reason,
                    "hits": hits,
                },
            }
        )
    return _sha256(_canonical_json_bytes(payload)), payload


def _deleted_residual_count(
    bundle: LoadedPerformanceBundle,
    *,
    index_root: Path,
    query_payload: list[dict[str, object]],
) -> int:
    base_version = load_index_version(index_root, BASE_RUN_ID)
    base_lifecycle = validate_incremental_index_directory(base_version.path)
    target_version = load_index_version(index_root, TARGET_RUN_ID)
    target_lifecycle = validate_incremental_index_directory(target_version.path)
    snapshot = V2IndexSnapshot.load(index_root, TARGET_RUN_ID)
    base_bindings = {
        item.source_key: item for item in base_lifecycle.source_bindings
    }
    target_live = {
        item.source_key for item in target_lifecycle.source_bindings
    }
    target_tombstones = {
        item.source_key for item in target_lifecycle.tombstone_bindings
    }
    hit_pairs = {
        (str(hit["doc_id"]), str(hit["chunk_id"]))
        for case in query_payload
        for hit in case["result"]["hits"]  # type: ignore[index]
    }
    residuals: set[tuple[str, str]] = set()
    for source_key in bundle.change_descriptor.categories.deletes:
        binding = base_bindings.get(source_key)
        if binding is None:
            residuals.add(("missing_base_oracle", source_key))
            continue
        if source_key in target_live:
            residuals.add(("live_source_binding", source_key))
        if source_key not in target_tombstones:
            residuals.add(("missing_tombstone", source_key))
        if binding.document_id in snapshot.documents_by_id:
            residuals.add(("document", binding.document_id))
        for chunk_id in binding.indexed_chunk_ids:
            if chunk_id in snapshot.all_chunks_by_id:
                residuals.add(("indexed_chunk", chunk_id))
            if chunk_id in snapshot.chunk_index_by_id:
                residuals.add(("bm25_faiss_row", chunk_id))
            if (binding.document_id, chunk_id) in hit_pairs:
                residuals.add(("retrieval_hit", chunk_id))
        for chunk_id in binding.parent_chunk_ids:
            if chunk_id in snapshot.parents_by_id:
                residuals.add(("parent_chunk", chunk_id))
    return len(residuals)


def _target_fingerprint(
    bundle: LoadedPerformanceBundle,
    *,
    index_root: Path,
) -> TargetEquivalenceFingerprint:
    version = load_index_version(index_root, TARGET_RUN_ID)
    lifecycle = validate_incremental_index_directory(version.path)
    query_sha256, query_payload = _query_results(
        bundle,
        index_root=index_root,
    )
    residual_count = _deleted_residual_count(
        bundle,
        index_root=index_root,
        query_payload=query_payload,
    )
    return TargetEquivalenceFingerprint(
        target_catalog_sha256=lifecycle.target_catalog_sha256,
        documents_sha256=lifecycle.documents_sha256,
        chunks_sha256=lifecycle.chunks_sha256,
        embeddings_sha256=lifecycle.embeddings_sha256,
        document_ids_sha256=lifecycle.document_ids_sha256,
        indexed_chunk_ids_sha256=lifecycle.indexed_chunk_ids_sha256,
        parent_chunk_ids_sha256=lifecycle.parent_chunk_ids_sha256,
        computation_chunk_order_sha256=_sha256(
            _canonical_json_bytes(list(lifecycle.computation_chunk_order))
        ),
        query_fingerprint_sha256=query_sha256,
        active_index_deleted_residual_count=residual_count,
    )


def measure_performance_arm(
    *,
    bundle_root: Path,
    expected_bundle_manifest_sha256: str,
    workspace_root: Path,
    experiment_id: str,
    pair_number: int,
    arm: ArmName,
    execution_order: int,
    coordinator_process_id: int,
    expected_host_identity_sha256: str,
    expected_configuration_sha256: str,
) -> PairedArmMeasurement:
    workspace = _validate_absolute_workspace(
        workspace_root,
        require_empty=False,
    )
    if coordinator_process_id == os.getpid():
        raise PerformanceRunnerError(
            "arm_not_isolated",
            "An arm measurement must run outside the pair coordinator process.",
        )

    total_started = time.perf_counter_ns()
    input_started = total_started
    bundle = load_performance_bundle(Path(bundle_root))
    if bundle.manifest_sha256 != expected_bundle_manifest_sha256:
        raise PerformanceRunnerError(
            "bundle_identity_mismatch",
            "Arm worker loaded a different performance bundle.",
        )
    pipeline = build_performance_pipeline(bundle)
    prestate = _base_prestate(
        bundle=bundle,
        workspace=workspace,
        pipeline=pipeline,
    )
    observed_host_sha256 = host_identity_sha256()
    observed_configuration_sha256 = runner_configuration_sha256(bundle)
    if (
        observed_host_sha256 != expected_host_identity_sha256
        or observed_configuration_sha256 != expected_configuration_sha256
    ):
        raise PerformanceRunnerError(
            "worker_identity_mismatch",
            "Arm worker host or configuration identity changed.",
        )
    cold_cache_root = workspace / "target-cache"
    if arm == "baseline" and cold_cache_root.exists():
        raise PerformanceRunnerError(
            "cold_cache_exists",
            "Baseline target cache must not exist before timing.",
        )
    input_validation_seconds = (
        time.perf_counter_ns() - input_started
    ) / 1_000_000_000

    cache_root = (
        cold_cache_root if arm == "baseline" else workspace / "base-cache"
    )
    cache = PersistentComputationCache(cache_root.absolute())
    plan = build_change_plan(
        base=bundle.base_catalog,
        target=bundle.target_catalog,
        base_index_run_id=BASE_RUN_ID,
        target_index_run_id=TARGET_RUN_ID,
    )
    computation = execute_incremental_computation(
        plan=plan,
        base_catalog=bundle.base_catalog,
        target_catalog=bundle.target_catalog,
        cache=cache,
        pipeline=pipeline,
        materializer=PerformanceBundleRevisionContentMaterializer(
            bundle,
            role="target",
        ),
        embed_text=deterministic_embedding,
    )

    publication_started = time.perf_counter_ns()
    publication = build_incremental_index_version(
        root=(workspace / "index").absolute(),
        plan=plan,
        base_catalog=bundle.base_catalog,
        target_catalog=bundle.target_catalog,
        computation=computation,
        pipeline=pipeline,
        profile_id="g10-paired-performance",
        activate=True,
        started_at=FIXED_BUILD_TIME,
        finished_at=FIXED_BUILD_TIME,
    )
    target_version = load_index_version(workspace / "index", TARGET_RUN_ID)
    validate_incremental_index_directory(target_version.path)
    active = load_active_pointer(workspace / "index")
    publication_seconds = (
        time.perf_counter_ns() - publication_started
    ) / 1_000_000_000
    if (
        publication.status != "BUILT"
        or not publication.activated
        or active.run_id != TARGET_RUN_ID
        or active.manifest_sha256 != publication.manifest_sha256
    ):
        raise PerformanceRunnerError(
            "target_publication_incomplete",
            "Measured target was reused, inactive, or incompletely validated.",
        )
    total_wall_seconds = (
        time.perf_counter_ns() - total_started
    ) / 1_000_000_000

    target_fingerprint = _target_fingerprint(
        bundle,
        index_root=workspace / "index",
    )
    return PairedArmMeasurement(
        experiment_id=experiment_id,
        pair_number=pair_number,
        arm=arm,
        execution_order=execution_order,
        workspace_identity_sha256=prestate.workspace_identity_sha256,
        target_cache_mode="cold" if arm == "baseline" else "warm",
        base_index_prestate_sha256=prestate.base_index_prestate_sha256,
        base_cache_prestate_sha256=prestate.base_cache_prestate_sha256,
        bundle_manifest_sha256=bundle.manifest_sha256,
        base_catalog_sha256=revision_catalog_sha256(bundle.base_catalog),
        target_catalog_sha256=revision_catalog_sha256(bundle.target_catalog),
        change_set_sha256=_sha256(
            _canonical_json_bytes(
                bundle.change_descriptor.model_dump(mode="json")
            )
        ),
        query_set_sha256=_sha256(
            _canonical_json_bytes(
                bundle.query_descriptor.model_dump(mode="json")
            )
        ),
        pipeline_sha256=pipeline_configuration_sha256(pipeline),
        embedding_model=EMBEDDING_MODEL,
        host_identity_sha256=observed_host_sha256,
        configuration_sha256=observed_configuration_sha256,
        coordinator_process_id=coordinator_process_id,
        process_id=os.getpid(),
        total_wall_seconds=total_wall_seconds,
        input_validation_seconds=input_validation_seconds,
        computation_wall_seconds=(
            computation.measurements.total_wall_seconds
        ),
        publication_wall_seconds=publication_seconds,
        peak_rss_bytes=process_peak_rss_bytes() or 0,
        cache_statistics=computation.stats,
        computation_measurements=computation.measurements,
        target_fingerprint=target_fingerprint,
    )


__all__ = [
    "ArmWorkspacePrestate",
    "BASE_RUN_ID",
    "EMBEDDING_MODEL",
    "FIXED_BUILD_TIME",
    "PerformanceRunnerError",
    "TARGET_RUN_ID",
    "build_performance_pipeline",
    "clone_arm_workspace",
    "host_identity_sha256",
    "measure_performance_arm",
    "prepare_arm_workspace",
    "runner_configuration_descriptor",
    "runner_environment_identity",
    "runner_configuration_sha256",
    "runner_source_paths",
]
