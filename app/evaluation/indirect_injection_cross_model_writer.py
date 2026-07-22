from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.retrieved_security import (
    DETECTOR_VERSION,
    MAX_DECODED_VIEWS,
    MAX_NORMALIZED_CHARS,
    MAX_SCAN_CHARS,
)
from app.evaluation.indirect_injection_cross_model import (
    CLEAN_GIT_STATE_SHA256,
    COMPARISON_METRIC_IDS,
    CrossModelCaseRow,
    CrossModelComparisonResult,
    CrossModelDecision,
    CrossModelMetricDelta,
    CrossModelModelSummary,
    _comparison_decision,
    _metric_delta,
    _summarize_model,
    compare_verified_runs,
    load_cross_model_plan,
)
from app.evaluation.indirect_injection_dataset import (
    LoadedSecurityBundle,
    load_security_bundle,
)
from app.evaluation.indirect_injection_live_writer import (
    LiveSecurityRunManifestV3,
    load_verified_live_security_run_snapshot,
)
from app.evaluation.indirect_injection_writer import (
    GitSecurityProvenance,
    _assert_content_free,
    validate_security_run_id,
)
from app.evaluation.publication_paths import (
    _atomic_publish_no_replace,
    _validated_publication_root,
)


PRIVATE_CROSS_MODEL_ARTIFACT_FILES = frozenset(
    {
        "manifest.json",
        "summary.json",
        "per_case_redacted.jsonl",
        "checksums.sha256",
        "commands.txt",
        "verification_witness.json",
    }
)
_CHECKSUM_CONTENT_NAMES = tuple(
    sorted(
        PRIVATE_CROSS_MODEL_ARTIFACT_FILES
        - {"manifest.json", "checksums.sha256"}
    )
)
_CODE_BINDING_PATHS = tuple(sorted((
    "app/config.py",
    "app/agent/generation_v2.py",
    "app/agent/runner_v2.py",
    "app/agent/tools_v2.py",
    "app/evaluation/indirect_injection_arm_order.py",
    "app/evaluation/indirect_injection_contracts.py",
    "app/evaluation/indirect_injection_cross_model.py",
    "app/evaluation/indirect_injection_cross_model_writer.py",
    "app/evaluation/indirect_injection_dataset.py",
    "app/evaluation/indirect_injection_live_index.py",
    "app/evaluation/indirect_injection_live_runner.py",
    "app/evaluation/indirect_injection_live_writer.py",
    "app/evaluation/indirect_injection_metric_semantics.py",
    "app/evaluation/indirect_injection_runner.py",
    "app/domain/retrieved_security.py",
    "app/indexing/store.py",
    "app/ollama_chat.py",
    "app/retriever.py",
    "app/retrieval/navigation.py",
    "app/retrieval/pipeline.py",
    "app/retrieval/snapshot.py",
    "app/security/retrieved_content.py",
    "app/runtime/model_transport.py",
    "scripts/eval_indirect_injection.py",
    "scripts/eval_indirect_injection_cross_model.py",
    "scripts/eval_indirect_injection_live.py",
    "scripts/verify_indirect_injection_cross_model.py",
)))
_LIMITATIONS = (
    "This matrix is one local two-model observation, not a release PASS.",
    "The visible dev set is regression evidence, not unseen production traffic.",
    "Only chat-model identity is intentionally varied; latency is host-specific.",
    "model_specific_pair_input_fingerprint is opaque model/run-local evidence; standalone verification neither recomputes it nor compares it across model roles.",
    "Exact clean Git provenance is the causal code binding; listed file hashes are selected audit witnesses, not a full repository closure.",
)
_REPARSE_POINT_ATTRIBUTE = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400,
)
_FileIdentity = tuple[int, int, int, int, int, int]
_DirectoryIdentity = tuple[int, int, int, int]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


def _safe_relative(value: str, label: str) -> str:
    if "\\" in value:
        raise ValueError(f"{label} must use repository-relative POSIX form")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
    ):
        raise ValueError(f"{label} must be a safe relative path")
    return value


class CrossModelArtifactEvidence(_StrictFrozenModel):
    path: str
    bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash_mode: Literal[
        "actual_sha256",
        "canonical_manifest_self_normalized_v1",
    ]

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _safe_relative(value, "matrix artifact path")


class CrossModelComponentEvidence(_StrictFrozenModel):
    model_role: Literal["baseline", "replication"]
    run_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    per_case_bytes: int = Field(ge=1)
    per_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_complete: bool


class CrossModelSummaryDocument(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_cross_model_summary_v1"]
    matrix_run_id: Literal["r2-s4-cross-model-dev-20260722-01"]
    experiment_id: Literal["r2-s4-cross-model-dev-v1"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_run_ids: dict[str, str]
    source_manifest_sha256: dict[str, str]
    row_count: Literal[72]
    summaries: dict[str, CrossModelModelSummary]
    deltas: dict[str, CrossModelMetricDelta]
    invariant_mismatches: tuple[str, ...]
    decision: CrossModelDecision
    decision_reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_document(self) -> CrossModelSummaryDocument:
        if set(self.source_run_ids) != {"baseline", "replication"}:
            raise ValueError("matrix summary source roles are incomplete")
        if set(self.source_manifest_sha256) != {"baseline", "replication"}:
            raise ValueError("matrix summary manifest roles are incomplete")
        if set(self.summaries) != {"baseline", "replication"}:
            raise ValueError("matrix summary model roles are incomplete")
        if set(self.deltas) != set(COMPARISON_METRIC_IDS):
            raise ValueError("matrix summary metric set is not frozen")
        return self


class CrossModelVerificationWitness(_StrictFrozenModel):
    schema_version: Literal[
        "indirect_injection_cross_model_verification_witness_v1"
    ]
    matrix_run_id: Literal["r2-s4-cross-model-dev-20260722-01"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    git: GitSecurityProvenance
    component_manifest_sha256: dict[str, str]
    component_per_case_sha256: dict[str, str]
    code_sha256: dict[str, str]
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_count: Literal[72]
    decision: CrossModelDecision


class CrossModelRunManifest(_StrictFrozenModel):
    schema_version: Literal[
        "indirect_injection_cross_model_run_manifest_v1"
    ]
    producer: Literal["enterprise_agentic_rag_v2"]
    matrix_run_id: Literal["r2-s4-cross-model-dev-20260722-01"]
    experiment_id: Literal["r2-s4-cross-model-dev-v1"]
    split: Literal["dev"]
    only_changed_variable: Literal["chat_model_identity"]
    plan_path: str
    plan_bytes: int = Field(ge=1)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    git: GitSecurityProvenance
    components: dict[str, CrossModelComponentEvidence]
    code_sha256: dict[str, str]
    row_count: Literal[72]
    decision: CrossModelDecision
    invariant_mismatches: tuple[str, ...]
    artifacts: dict[str, CrossModelArtifactEvidence]
    limitations: tuple[str, ...] = Field(min_length=1)

    @field_validator("matrix_run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return validate_security_run_id(value)

    @field_validator("plan_path")
    @classmethod
    def validate_plan_path(cls, value: str) -> str:
        return _safe_relative(value, "matrix plan path")

    @model_validator(mode="after")
    def validate_manifest(self) -> CrossModelRunManifest:
        if (
            self.git.dirty
            or self.git.status_entry_count != 0
            or self.git.dirty_state_sha256 != CLEAN_GIT_STATE_SHA256
        ):
            raise ValueError("matrix manifest requires exact clean Git provenance")
        if set(self.components) != {"baseline", "replication"}:
            raise ValueError("matrix component roles are incomplete")
        for role, component in self.components.items():
            if role != component.model_role:
                raise ValueError("matrix component role/key mismatch")
        if tuple(self.code_sha256) != _CODE_BINDING_PATHS:
            raise ValueError("matrix code binding paths are not exact")
        if set(self.artifacts) != set(PRIVATE_CROSS_MODEL_ARTIFACT_FILES):
            raise ValueError("matrix manifest requires all six artifacts")
        for name, evidence in self.artifacts.items():
            if name != evidence.path:
                raise ValueError("matrix artifact key/path mismatch")
            expected_mode = (
                "canonical_manifest_self_normalized_v1"
                if name == "manifest.json"
                else "actual_sha256"
            )
            if evidence.hash_mode != expected_mode:
                raise ValueError("matrix artifact hash mode is invalid")
        if self.limitations != _LIMITATIONS:
            raise ValueError("matrix limitations are not exact")
        return self


@dataclass(frozen=True)
class VerifiedCrossModelRunSnapshot:
    run_dir: Path
    manifest: CrossModelRunManifest
    summary: CrossModelSummaryDocument
    rows: tuple[CrossModelCaseRow, ...]
    manifest_sha256: str
    artifacts: Mapping[str, bytes]
    _identities: Mapping[str, _FileIdentity]
    _directory_identities: tuple[tuple[Path, _DirectoryIdentity], ...] = ()

    def assert_unchanged(self) -> None:
        try:
            for path, expected in self._directory_identities:
                observed = path.lstat()
                if (
                    _is_redirecting_path(observed)
                    or not stat.S_ISDIR(observed.st_mode)
                    or _directory_identity(observed) != expected
                ):
                    raise ValueError(
                        "cross-model directory identity changed after verification"
                    )
            names = {item.name for item in self.run_dir.iterdir()}
            if names != set(PRIVATE_CROSS_MODEL_ARTIFACT_FILES):
                raise ValueError("cross-model package changed after verification")
            for name, identity in self._identities.items():
                observed = (self.run_dir / name).lstat()
                if (
                    _is_redirecting_path(observed)
                    or not stat.S_ISREG(observed.st_mode)
                    or _file_identity(observed) != identity
                ):
                    raise ValueError(
                        f"cross-model artifact changed after verification: {name}"
                    )
        except OSError as exc:
            raise ValueError("cross-model package changed after verification") from exc


def publish_cross_model_run(
    root: Path,
    comparison: CrossModelComparisonResult,
    *,
    plan_path: Path,
    component_runs: Mapping[str, Path],
    commands: str,
    forbidden_texts: tuple[str, ...],
    code_root: Path | None = None,
    current_git: Mapping[str, object] | GitSecurityProvenance | None = None,
    current_effective_static: Mapping[str, object] | None = None,
) -> Path:
    """Publish or exactly reuse one immutable private cross-model matrix."""

    if not forbidden_texts or any(not value for value in forbidden_texts):
        raise ValueError("a non-empty forbidden text policy is required")
    if set(component_runs) != {"baseline", "replication"}:
        raise ValueError("exactly one baseline and replication component is required")
    repository = _validated_code_root(
        Path(code_root) if code_root is not None else Path(__file__).resolve().parents[2]
    )
    plan_file = _validated_repository_file(repository, Path(plan_path), "matrix plan")
    plan, plan_sha256 = load_cross_model_plan(plan_file)
    plan_payload, _ = _read_regular_file_snapshot(plan_file, "matrix plan")
    if _sha256_bytes(plan_payload) != plan_sha256:
        raise ValueError("matrix plan changed during publication")

    bundle = load_security_bundle(repository / "data" / "v2" / "security", plan.split)
    recomputed = compare_verified_runs(
        Path(component_runs["baseline"]),
        Path(component_runs["replication"]),
        plan=plan,
        plan_sha256=plan_sha256,
        dataset=bundle.dataset,
    )
    if recomputed != comparison:
        raise ValueError("provided comparison does not recompute from components")

    components = _component_evidence(component_runs, comparison)
    component_git = _component_git_from_paths(component_runs)
    controller_git = (
        component_git
        if current_git is None
        else _coerce_git(current_git)
    )
    _require_clean_git(controller_git, "controller")
    if controller_git != component_git:
        raise ValueError("component Git binding contradicts current Git")
    _validate_components_against_current_data_guard(
        component_runs,
        repository=repository,
        bundle=bundle,
    )
    if current_effective_static is not None:
        _validate_current_effective_static(
            component_runs,
            current_effective_static,
        )
    code_sha256 = _code_bindings(repository)
    plan_relative = plan_file.relative_to(repository).as_posix()
    expected_files, expected_manifest = _build_package_bytes(
        comparison,
        plan_path=plan_relative,
        plan_bytes=len(plan_payload),
        components=components,
        git=controller_git,
        code_sha256=code_sha256,
        commands=_canonical_text(commands, "matrix commands"),
    )
    for name, payload in expected_files.items():
        _assert_content_free(payload, forbidden_texts)

    output_root = _validated_cross_model_publication_root(
        Path(root),
        "matrix output root",
    )
    target = output_root / plan.matrix_run_id
    if target.parent != output_root:
        raise ValueError("matrix run ID resolves outside output root")
    existing = _lexical_target_kind(target)
    if existing == "redirect":
        raise ValueError("matrix target cannot be a symlink or redirect")
    if existing == "other":
        raise FileExistsError(f"matrix target is not a directory: {target}")
    if existing == "directory":
        snapshot = load_verified_cross_model_run_snapshot(target)
        snapshot.assert_unchanged()
        for name, payload in expected_files.items():
            if snapshot.artifacts[name] != payload:
                raise ValueError("existing matrix does not match exact bindings")
        if snapshot.manifest != expected_manifest:
            raise ValueError("existing matrix manifest does not match exact bindings")
        return target.resolve()

    stage = Path(
        tempfile.mkdtemp(prefix=f".{plan.matrix_run_id}.staging-", dir=output_root)
    ).resolve()
    try:
        for name, payload in expected_files.items():
            (stage / name).write_bytes(payload)
        _validate_package(stage, require_directory_identity=False)
        _atomic_publish_no_replace(stage, target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def load_verified_cross_model_run_snapshot(
    run_dir: Path,
) -> VerifiedCrossModelRunSnapshot:
    trusted, directory_identities = _validated_trusted_directory_snapshot(
        Path(run_dir),
        "cross-model run directory",
    )
    snapshot = _validate_package(
        trusted,
        require_directory_identity=True,
        directory_identities=directory_identities,
    )
    snapshot.assert_unchanged()
    return snapshot


def verify_cross_model_run(run_dir: Path) -> CrossModelRunManifest:
    return load_verified_cross_model_run_snapshot(run_dir).manifest


def validate_current_cross_model_bindings(
    run_dir: Path,
    *,
    plan_path: Path,
    component_runs: Mapping[str, Path],
    code_root: Path | None = None,
    current_git: Mapping[str, object] | GitSecurityProvenance,
    current_effective_static: Mapping[str, object] | None = None,
) -> CrossModelRunManifest:
    """Admit an existing matrix only against current plan/components/code."""

    repository = _validated_code_root(
        Path(code_root) if code_root is not None else Path(__file__).resolve().parents[2]
    )
    snapshot = load_verified_cross_model_run_snapshot(run_dir)
    manifest = snapshot.manifest
    controller_git = _coerce_git(current_git)
    _require_clean_git(controller_git, "current")
    if manifest.git != controller_git:
        raise ValueError("existing matrix contradicts current Git binding")
    plan_file = _validated_repository_file(repository, Path(plan_path), "matrix plan")
    plan_payload, _ = _read_regular_file_snapshot(plan_file, "matrix plan")
    plan, plan_sha256 = load_cross_model_plan(plan_file)
    if (
        manifest.matrix_run_id != plan.matrix_run_id
        or manifest.experiment_id != plan.experiment_id
        or manifest.plan_sha256 != plan_sha256
        or manifest.plan_bytes != len(plan_payload)
        or manifest.plan_path != plan_file.relative_to(repository).as_posix()
    ):
        raise ValueError("existing matrix contradicts the current plan")
    if manifest.code_sha256 != _code_bindings(repository):
        raise ValueError("existing matrix contradicts current code bytes")
    expected_components = _component_evidence_from_paths(component_runs)
    if manifest.components != expected_components:
        raise ValueError("existing matrix contradicts current component packages")
    if _component_git_from_paths(component_runs) != controller_git:
        raise ValueError("existing components contradict current Git binding")
    for role in ("baseline", "replication"):
        if expected_components[role].run_id != plan.model_for_role(role).run_id:
            raise ValueError("existing matrix component run ID contradicts plan")
    bundle = load_security_bundle(
        repository / "data" / "v2" / "security",
        plan.split,
    )
    _validate_components_against_current_data_guard(
        component_runs,
        repository=repository,
        bundle=bundle,
    )
    if current_effective_static is not None:
        _validate_current_effective_static(
            component_runs,
            current_effective_static,
        )
    recomputed = compare_verified_runs(
        Path(component_runs["baseline"]),
        Path(component_runs["replication"]),
        plan=plan,
        plan_sha256=plan_sha256,
        dataset=bundle.dataset,
    )
    if snapshot.rows != recomputed.rows or snapshot.summary != _summary_document(
        recomputed
    ):
        raise ValueError("existing matrix does not recompute from current components")
    snapshot.assert_unchanged()
    return manifest


def _component_evidence(
    component_runs: Mapping[str, Path],
    comparison: CrossModelComparisonResult,
) -> dict[str, CrossModelComponentEvidence]:
    evidence = _component_evidence_from_paths(component_runs)
    for role in ("baseline", "replication"):
        if (
            evidence[role].run_id != comparison.source_run_ids[role]
            or evidence[role].manifest_sha256
            != comparison.source_manifest_sha256[role]
            or evidence[role].model_digest
            != comparison.summaries[role].model_digest
        ):
            raise ValueError("comparison/component evidence binding differs")
    return evidence


def _component_evidence_from_paths(
    component_runs: Mapping[str, Path],
) -> dict[str, CrossModelComponentEvidence]:
    if set(component_runs) != {"baseline", "replication"}:
        raise ValueError("matrix component paths are incomplete")
    result: dict[str, CrossModelComponentEvidence] = {}
    for role in ("baseline", "replication"):
        snapshot = load_verified_live_security_run_snapshot(Path(component_runs[role]))
        manifest = snapshot.manifest
        if not isinstance(manifest, LiveSecurityRunManifestV3):
            raise ValueError("matrix component is not a verified V3 run")
        artifact = manifest.artifacts["per_case.jsonl"]
        result[role] = CrossModelComponentEvidence(
            model_role=role,
            run_id=manifest.run_id,
            manifest_sha256=snapshot.manifest_sha256,
            per_case_bytes=artifact.bytes,
            per_case_sha256=artifact.sha256,
            model_digest=manifest.models.chat.digest,
            protocol_complete=bool(
                manifest.status == "COMPLETED WITH OBSERVATIONS"
                and manifest.observation.protocol_complete
            ),
        )
        snapshot.assert_manifest_unchanged()
    return result


def _component_git_from_paths(
    component_runs: Mapping[str, Path],
) -> GitSecurityProvenance:
    if set(component_runs) != {"baseline", "replication"}:
        raise ValueError("matrix component paths are incomplete")
    observed: dict[str, GitSecurityProvenance] = {}
    for role in ("baseline", "replication"):
        snapshot = load_verified_live_security_run_snapshot(Path(component_runs[role]))
        if not isinstance(snapshot.manifest, LiveSecurityRunManifestV3):
            raise ValueError("matrix component is not a verified V3 run")
        observed[role] = snapshot.manifest.git
        _require_clean_git(observed[role], role)
        snapshot.assert_manifest_unchanged()
    if observed["baseline"] != observed["replication"]:
        raise ValueError("matrix components do not share exact Git provenance")
    return observed["baseline"]


def _validate_components_against_current_data_guard(
    component_runs: Mapping[str, Path],
    *,
    repository: Path,
    bundle: LoadedSecurityBundle,
) -> None:
    dataset_path = bundle.dataset_path.resolve().relative_to(repository).as_posix()
    fixture_path = (
        bundle.fixture_manifest_path.resolve().relative_to(repository).as_posix()
    )
    guard_relative = "app/security/retrieved_content.py"
    guard_path = _validated_fixed_regular_path(
        repository,
        Path(*PurePosixPath(guard_relative).parts),
        "current Guard ruleset",
    )
    guard_payload, _ = _read_regular_file_snapshot(guard_path, "current Guard ruleset")
    guard_sha256 = _sha256_bytes(guard_payload)
    for role in ("baseline", "replication"):
        snapshot = load_verified_live_security_run_snapshot(Path(component_runs[role]))
        manifest = snapshot.manifest
        if not isinstance(manifest, LiveSecurityRunManifestV3):
            raise ValueError("matrix component is not a verified V3 run")
        data = manifest.data
        if (
            data.dataset_path != dataset_path
            or data.dataset_sha256 != bundle.dataset_sha256
            or data.fixture_manifest_path != fixture_path
            or data.fixture_manifest_sha256 != bundle.fixture_manifest_sha256
            or data.dataset_case_count != bundle.dataset.case_count
            or data.attack_case_count != bundle.dataset.attack_case_count
            or data.benign_case_count != bundle.dataset.benign_case_count
        ):
            raise ValueError(f"{role} component contradicts current dataset/fixture")
        for relative, pair in data.r1_frozen_hashes.items():
            frozen_path = _validated_fixed_regular_path(
                repository,
                Path(*PurePosixPath(relative).parts),
                f"current R1 binding {relative}",
            )
            payload, _ = _read_regular_file_snapshot(
                frozen_path,
                f"current R1 binding {relative}",
            )
            if pair.actual != _sha256_bytes(payload) or pair.expected != pair.actual:
                raise ValueError(f"{role} component contradicts current R1 data")
        guard = manifest.guard
        if (
            guard.detector_version != DETECTOR_VERSION
            or guard.ruleset_path != guard_relative
            or guard.ruleset_sha256 != guard_sha256
            or guard.max_scan_chars != MAX_SCAN_CHARS
            or guard.max_normalized_chars != MAX_NORMALIZED_CHARS
            or guard.max_decoded_views != MAX_DECODED_VIEWS
        ):
            raise ValueError(f"{role} component contradicts current Guard binding")
        snapshot.assert_manifest_unchanged()


def _validate_current_effective_static(
    component_runs: Mapping[str, Path],
    current: Mapping[str, object],
) -> None:
    expected = _normalize_json_value(dict(current))
    for role in ("baseline", "replication"):
        snapshot = load_verified_live_security_run_snapshot(Path(component_runs[role]))
        manifest = snapshot.manifest
        if not isinstance(manifest, LiveSecurityRunManifestV3):
            raise ValueError("matrix component is not a verified V3 run")
        if _manifest_effective_static(manifest) != expected:
            raise ValueError(
                f"{role} component contradicts current effective static binding"
            )
        snapshot.assert_manifest_unchanged()


def _manifest_effective_static(manifest: LiveSecurityRunManifestV3) -> object:
    return _normalize_json_value(
        {
            "environment": {
                "ollama_endpoint": manifest.environment.ollama_endpoint,
                "python_version": manifest.environment.python_version,
                "platform": manifest.environment.platform,
                "dependency_snapshot_path": (
                    manifest.environment.dependency_snapshot_path
                ),
                "dependency_snapshot_sha256": (
                    manifest.environment.dependency_snapshot_sha256
                ),
                "installed_snapshot_sha256": (
                    manifest.environment.installed_snapshot_sha256
                ),
                "installed_package_count": (
                    manifest.environment.installed_package_count
                ),
            },
            "embedding": {
                "requested_name": manifest.models.embedding.requested_name,
                "resolved_name": manifest.models.embedding.resolved_name,
                "digest": manifest.models.embedding.digest,
            },
            "model_protocol": {
                "evidence_model": manifest.models.evidence_model,
                "temperature": manifest.models.temperature,
                "structured_output_variant": (
                    manifest.models.structured_output_variant
                ),
                "think": manifest.models.think,
                "max_attempts": manifest.models.max_attempts,
            },
            "transport": manifest.transport.model_dump(mode="json"),
            "retrieval": {
                "production_active_index": (
                    manifest.retrieval.production_active_index.model_dump(mode="json")
                ),
                "chunking": manifest.retrieval.chunking,
                "top_k": manifest.retrieval.top_k,
                "candidate_k": manifest.retrieval.candidate_k,
                "max_search_calls": manifest.retrieval.max_search_calls,
                "max_open_calls": manifest.retrieval.max_open_calls,
                "max_steps": manifest.retrieval.max_steps,
                "max_context_chars": manifest.retrieval.max_context_chars,
            },
            "evaluator": {
                "path": manifest.evaluator.path,
                "sha256": manifest.evaluator.sha256,
                "argv": manifest.evaluator.argv,
            },
        }
    )


def _normalize_json_value(value: object) -> object:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _require_clean_git(git: GitSecurityProvenance, label: str) -> None:
    if (
        git.dirty
        or git.status_entry_count != 0
        or git.dirty_state_sha256 != CLEAN_GIT_STATE_SHA256
    ):
        raise ValueError(f"{label} requires exact clean Git provenance")


def _coerce_git(
    value: Mapping[str, object] | GitSecurityProvenance,
) -> GitSecurityProvenance:
    if isinstance(value, GitSecurityProvenance):
        return value
    return GitSecurityProvenance.model_validate(dict(value))


def _build_package_bytes(
    comparison: CrossModelComparisonResult,
    *,
    plan_path: str,
    plan_bytes: int,
    components: Mapping[str, CrossModelComponentEvidence],
    git: GitSecurityProvenance,
    code_sha256: Mapping[str, str],
    commands: str,
) -> tuple[dict[str, bytes], CrossModelRunManifest]:
    summary = _summary_document(comparison)
    summary_bytes = _json_bytes(summary.model_dump(mode="json"))
    rows_bytes = b"".join(
        _json_bytes(row.model_dump(mode="json"), compact=True)
        for row in comparison.rows
    )
    commands_bytes = commands.encode("utf-8")
    witness = CrossModelVerificationWitness(
        schema_version="indirect_injection_cross_model_verification_witness_v1",
        matrix_run_id=comparison.matrix_run_id,
        plan_sha256=comparison.plan_sha256,
        git=git,
        component_manifest_sha256={
            role: components[role].manifest_sha256
            for role in ("baseline", "replication")
        },
        component_per_case_sha256={
            role: components[role].per_case_sha256
            for role in ("baseline", "replication")
        },
        code_sha256=dict(code_sha256),
        summary_sha256=_sha256_bytes(summary_bytes),
        rows_sha256=_sha256_bytes(rows_bytes),
        row_count=72,
        decision=comparison.decision,
    )
    witness_bytes = _json_bytes(witness.model_dump(mode="json"))
    files = {
        "commands.txt": commands_bytes,
        "per_case_redacted.jsonl": rows_bytes,
        "summary.json": summary_bytes,
        "verification_witness.json": witness_bytes,
    }
    checksum_bytes = _checksum_bytes(files)
    files["checksums.sha256"] = checksum_bytes
    artifacts = {
        name: CrossModelArtifactEvidence(
            path=name,
            bytes=len(payload),
            sha256=_sha256_bytes(payload),
            hash_mode="actual_sha256",
        )
        for name, payload in files.items()
    }
    artifacts["manifest.json"] = CrossModelArtifactEvidence(
        path="manifest.json",
        bytes=1,
        sha256="0" * 64,
        hash_mode="canonical_manifest_self_normalized_v1",
    )
    draft = CrossModelRunManifest(
        schema_version="indirect_injection_cross_model_run_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        matrix_run_id=comparison.matrix_run_id,
        experiment_id=comparison.experiment_id,
        split="dev",
        only_changed_variable="chat_model_identity",
        plan_path=plan_path,
        plan_bytes=plan_bytes,
        plan_sha256=comparison.plan_sha256,
        git=git,
        components=dict(components),
        code_sha256=dict(code_sha256),
        row_count=72,
        decision=comparison.decision,
        invariant_mismatches=comparison.invariant_mismatches,
        artifacts=artifacts,
        limitations=_LIMITATIONS,
    )
    manifest, manifest_bytes = _finalize_manifest(draft)
    files["manifest.json"] = manifest_bytes
    return files, manifest


def _summary_document(
    comparison: CrossModelComparisonResult,
) -> CrossModelSummaryDocument:
    return CrossModelSummaryDocument(
        schema_version="indirect_injection_cross_model_summary_v1",
        matrix_run_id=comparison.matrix_run_id,
        experiment_id=comparison.experiment_id,
        plan_sha256=comparison.plan_sha256,
        source_run_ids=comparison.source_run_ids,
        source_manifest_sha256=comparison.source_manifest_sha256,
        row_count=72,
        summaries=comparison.summaries,
        deltas=comparison.deltas,
        invariant_mismatches=comparison.invariant_mismatches,
        decision=comparison.decision,
        decision_reasons=comparison.decision_reasons,
    )


def _finalize_manifest(
    draft: CrossModelRunManifest,
) -> tuple[CrossModelRunManifest, bytes]:
    payload = draft.model_dump(mode="json")
    self_evidence = payload["artifacts"]["manifest.json"]
    self_evidence["sha256"] = "0" * 64
    for _ in range(10):
        normalized = _json_bytes(payload)
        observed_bytes = len(normalized)
        if self_evidence["bytes"] != observed_bytes:
            self_evidence["bytes"] = observed_bytes
            continue
        self_evidence["sha256"] = _sha256_bytes(normalized)
        final_bytes = _json_bytes(payload)
        if len(final_bytes) != observed_bytes:
            self_evidence["sha256"] = "0" * 64
            self_evidence["bytes"] = len(final_bytes)
            continue
        manifest = CrossModelRunManifest.model_validate_json(final_bytes)
        return manifest, final_bytes
    raise RuntimeError("matrix manifest self-evidence did not converge")


def _validate_package(
    run_dir: Path,
    *,
    require_directory_identity: bool,
    directory_identities: tuple[tuple[Path, _DirectoryIdentity], ...] = (),
) -> VerifiedCrossModelRunSnapshot:
    names = {item.name for item in run_dir.iterdir()}
    if names != set(PRIVATE_CROSS_MODEL_ARTIFACT_FILES):
        raise ValueError("cross-model run has an unexpected artifact set")
    artifacts: dict[str, bytes] = {}
    identities: dict[str, _FileIdentity] = {}
    for name in sorted(PRIVATE_CROSS_MODEL_ARTIFACT_FILES):
        path = _validated_fixed_regular_path(
            run_dir,
            Path(name),
            f"cross-model artifact {name}",
        )
        raw, identity = _read_regular_file_snapshot(
            path,
            f"cross-model artifact {name}",
        )
        artifacts[name] = raw
        identities[name] = identity

    _load_canonical_object(artifacts["manifest.json"], "manifest")
    manifest = CrossModelRunManifest.model_validate_json(artifacts["manifest.json"])
    if require_directory_identity and run_dir.name != manifest.matrix_run_id:
        raise ValueError("cross-model directory name contradicts manifest")
    _validate_artifact_evidence(manifest, artifacts)
    if artifacts["checksums.sha256"] != _checksum_bytes(artifacts):
        raise ValueError("cross-model checksum file does not match artifacts")
    _load_canonical_object(artifacts["summary.json"], "summary")
    summary = CrossModelSummaryDocument.model_validate_json(artifacts["summary.json"])
    rows = _parse_rows(artifacts["per_case_redacted.jsonl"])
    _validate_recomputation(manifest, summary, rows, artifacts)
    command_text = _decode_utf8(artifacts["commands.txt"], "commands")
    if command_text != _canonical_text(command_text, "commands"):
        raise ValueError("matrix commands are not canonical LF-terminated text")
    _load_canonical_object(
        artifacts["verification_witness.json"],
        "verification witness",
    )
    witness = CrossModelVerificationWitness.model_validate_json(
        artifacts["verification_witness.json"]
    )
    expected_witness = CrossModelVerificationWitness(
        schema_version="indirect_injection_cross_model_verification_witness_v1",
        matrix_run_id=manifest.matrix_run_id,
        plan_sha256=manifest.plan_sha256,
        git=manifest.git,
        component_manifest_sha256={
            role: manifest.components[role].manifest_sha256
            for role in ("baseline", "replication")
        },
        component_per_case_sha256={
            role: manifest.components[role].per_case_sha256
            for role in ("baseline", "replication")
        },
        code_sha256=manifest.code_sha256,
        summary_sha256=_sha256_bytes(artifacts["summary.json"]),
        rows_sha256=_sha256_bytes(artifacts["per_case_redacted.jsonl"]),
        row_count=72,
        decision=manifest.decision,
    )
    if witness != expected_witness:
        raise ValueError("matrix verification witness does not recompute")
    return VerifiedCrossModelRunSnapshot(
        run_dir=run_dir,
        manifest=manifest,
        summary=summary,
        rows=rows,
        manifest_sha256=_sha256_bytes(artifacts["manifest.json"]),
        artifacts=artifacts,
        _identities=identities,
        _directory_identities=directory_identities,
    )


def _validate_recomputation(
    manifest: CrossModelRunManifest,
    summary: CrossModelSummaryDocument,
    rows: tuple[CrossModelCaseRow, ...],
    artifacts: Mapping[str, bytes],
) -> None:
    if (
        summary.matrix_run_id != manifest.matrix_run_id
        or summary.experiment_id != manifest.experiment_id
        or summary.plan_sha256 != manifest.plan_sha256
        or summary.source_run_ids
        != {role: manifest.components[role].run_id for role in ("baseline", "replication")}
        or summary.source_manifest_sha256
        != {
            role: manifest.components[role].manifest_sha256
            for role in ("baseline", "replication")
        }
        or summary.invariant_mismatches != manifest.invariant_mismatches
    ):
        raise ValueError("matrix summary contradicts manifest bindings")
    _validate_rows_against_manifest(manifest, rows)
    expected_summaries = {
        role: _summarize_model(
            role,
            manifest.components[role].model_digest,
            tuple(row for row in rows if row.model_role == role),
            manifest.components[role].protocol_complete,
        )
        for role in ("baseline", "replication")
    }
    expected_deltas = {
        metric_id: _metric_delta(
            expected_summaries["baseline"].metrics[metric_id],
            expected_summaries["replication"].metrics[metric_id],
        )
        for metric_id in COMPARISON_METRIC_IDS
    }
    expected_decision, expected_reasons = _comparison_decision(
        expected_summaries,
        rows,
        manifest.invariant_mismatches,
    )
    if (
        summary.summaries != expected_summaries
        or summary.deltas != expected_deltas
        or summary.decision != expected_decision
        or summary.decision_reasons != expected_reasons
        or manifest.decision != expected_decision
    ):
        raise ValueError("matrix summary/decision does not recompute from rows")


def _validate_rows_against_manifest(
    manifest: CrossModelRunManifest,
    rows: tuple[CrossModelCaseRow, ...],
) -> None:
    for role, offset in (("baseline", 0), ("replication", 36)):
        digest = manifest.components[role].model_digest
        role_rows = rows[offset : offset + 36]
        if any(
            row.model_role != role or row.model_digest != digest
            for row in role_rows
        ):
            raise ValueError(f"{role} row digest/role binding contradicts component")
    for index in range(36):
        baseline = rows[index]
        replication = rows[index + 36]
        if _model_neutral_cross_role_binding(
            baseline
        ) != _model_neutral_cross_role_binding(replication):
            raise ValueError(
                f"cross-model row binding differs at case ordinal {index + 1}"
            )


def _model_neutral_cross_role_binding(row: CrossModelCaseRow) -> object:
    """Return only row evidence that is expected to be equal across chat models."""

    def arm(value: object) -> tuple[object, ...]:
        return (
            value.guard_mode,
            value.retrieval_completed,
            value.candidate_count,
            value.attack_unit_count,
            value.attack_unit_reached_guard_count,
            value.attack_unit_quarantined_count,
            value.benign_unit_count,
            value.benign_unit_quarantined_count,
        )

    return (
        row.case_ordinal,
        row.case_class,
        row.arm_order,
        row.input_fingerprint,
        row.nonce_fingerprint,
        row.candidate_order_sha256,
        arm(row.off),
        arm(row.on),
    )


def _validate_artifact_evidence(
    manifest: CrossModelRunManifest,
    artifacts: Mapping[str, bytes],
) -> None:
    for name, evidence in manifest.artifacts.items():
        raw = artifacts[name]
        if len(raw) != evidence.bytes:
            raise ValueError(f"cross-model artifact byte count mismatch: {name}")
        if name == "manifest.json":
            payload = json.loads(raw.decode("utf-8"))
            payload["artifacts"]["manifest.json"]["sha256"] = "0" * 64
            digest = _sha256_bytes(_json_bytes(payload))
        else:
            digest = _sha256_bytes(raw)
        if digest != evidence.sha256:
            raise ValueError(f"cross-model artifact SHA-256 mismatch: {name}")


def _parse_rows(raw: bytes) -> tuple[CrossModelCaseRow, ...]:
    text = _decode_utf8(raw, "cross-model rows")
    if not text.endswith("\n") or "\r" in text:
        raise ValueError("cross-model rows are not canonical JSONL")
    rows: list[CrossModelCaseRow] = []
    for line in text.splitlines():
        payload = json.loads(line, object_pairs_hook=_unique_object)
        if line.encode("utf-8") + b"\n" != _json_bytes(payload, compact=True):
            raise ValueError("cross-model row is not canonical JSON")
        rows.append(CrossModelCaseRow.model_validate_json(line))
    if len(rows) != 72:
        raise ValueError("cross-model row count is not exactly 72")
    if tuple(row.row_ordinal for row in rows) != tuple(range(1, 73)):
        raise ValueError("cross-model row ordinals are not exact")
    expected_case_ordinals = tuple(range(1, 37)) * 2
    if tuple(row.case_ordinal for row in rows) != expected_case_ordinals:
        raise ValueError("cross-model case ordinals are not exact")
    expected_roles = ("baseline",) * 36 + ("replication",) * 36
    if tuple(row.model_role for row in rows) != expected_roles:
        raise ValueError("cross-model rows are not in exact 36 baseline/36 replication role order")
    return tuple(rows)


def _code_bindings(repository: Path) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for relative in _CODE_BINDING_PATHS:
        path = _validated_fixed_regular_path(
            repository,
            Path(*PurePosixPath(relative).parts),
            f"code binding {relative}",
        )
        payload, _ = _read_regular_file_snapshot(path, f"code binding {relative}")
        bindings[relative] = _sha256_bytes(payload)
    return bindings


def _validated_code_root(path: Path) -> Path:
    return _validated_trusted_directory(path, "repository root")


def _validated_cross_model_publication_root(path: Path, label: str) -> Path:
    lexical = Path(os.path.abspath(path))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current = current / part
        try:
            observed = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ValueError(f"{label} cannot be inspected") from exc
        if _is_redirecting_path(observed):
            raise ValueError(
                f"{label} has a redirecting symlink/junction/reparse component"
            )
        if not stat.S_ISDIR(observed.st_mode):
            raise ValueError(f"{label} has a non-directory path component")
    _validated_publication_root(lexical, label)
    return _validated_trusted_directory(lexical, label)


def _validated_repository_file(repository: Path, path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else repository / path
    absolute = candidate.absolute()
    try:
        relative = absolute.relative_to(repository)
    except ValueError as exc:
        raise ValueError(f"{label} resolves outside repository") from exc
    return _validated_fixed_regular_path(repository, relative, label)


def _validated_trusted_directory(path: Path, label: str) -> Path:
    lexical, _ = _validated_trusted_directory_snapshot(path, label)
    return lexical


def _validated_trusted_directory_snapshot(
    path: Path,
    label: str,
) -> tuple[Path, tuple[tuple[Path, _DirectoryIdentity], ...]]:
    lexical = Path(os.path.abspath(path))
    chain = tuple(reversed((lexical, *lexical.parents)))
    identities: list[tuple[Path, _DirectoryIdentity]] = []
    try:
        for current in chain:
            observed = current.lstat()
            if _is_redirecting_path(observed):
                raise ValueError(
                    f"{label} has a redirecting symlink/junction/reparse component"
                )
            if not stat.S_ISDIR(observed.st_mode):
                raise FileNotFoundError(f"{label} not found: {path}")
            identities.append((current, _directory_identity(observed)))
    except ValueError:
        raise
    except OSError as exc:
        raise FileNotFoundError(f"{label} not found: {path}") from exc
    return lexical, tuple(identities)


def _validated_fixed_regular_path(root: Path, relative: Path, label: str) -> Path:
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            observed = current.lstat()
        except OSError as exc:
            raise ValueError(f"{label} is missing or unreadable") from exc
        final = index == len(relative.parts) - 1
        if _is_redirecting_path(observed):
            raise ValueError(f"{label} has a redirecting path component")
        if final:
            if not stat.S_ISREG(observed.st_mode):
                raise ValueError(f"{label} must be a regular file")
        elif not stat.S_ISDIR(observed.st_mode):
            raise ValueError(f"{label} path component must be a directory")
    return current


def _read_regular_file_snapshot(
    path: Path,
    label: str,
) -> tuple[bytes, _FileIdentity]:
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        path_before = path.lstat()
        if _is_redirecting_path(path_before) or not stat.S_ISREG(path_before.st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        descriptor = os.open(path, flags)
        descriptor_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(descriptor_before.st_mode)
            or _file_identity(descriptor_before) != _file_identity(path_before)
        ):
            raise ValueError(f"{label} identity changed before descriptor read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        descriptor_after = os.fstat(descriptor)
        path_after = path.lstat()
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"{label} must be a regular non-symlink file") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identity = _file_identity(path_before)
    payload = b"".join(chunks)
    if (
        _is_redirecting_path(path_after)
        or not stat.S_ISREG(path_after.st_mode)
        or _file_identity(descriptor_before) != identity
        or _file_identity(descriptor_after) != identity
        or _file_identity(path_after) != identity
        or len(payload) != path_before.st_size
    ):
        raise ValueError(f"{label} identity changed during descriptor read")
    return payload, identity


def _lexical_target_kind(path: Path) -> str:
    try:
        observed = path.lstat()
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        raise ValueError("matrix target could not be inspected") from exc
    if _is_redirecting_path(observed):
        return "redirect"
    if stat.S_ISDIR(observed.st_mode):
        return "directory"
    return "other"


def _is_redirecting_path(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(
        getattr(value, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    )


def _file_identity(value: os.stat_result) -> _FileIdentity:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> _DirectoryIdentity:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        getattr(value, "st_file_attributes", 0),
    )


def _load_canonical_object(raw: bytes, label: str) -> dict[str, object]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cross-model {label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"cross-model {label} must be a JSON object")
    if raw != _json_bytes(payload):
        raise ValueError(f"cross-model {label} is not canonical JSON")
    return payload


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _checksum_bytes(artifacts: Mapping[str, bytes]) -> bytes:
    return "".join(
        f"{_sha256_bytes(artifacts[name])}  {name}\n"
        for name in _CHECKSUM_CONTENT_NAMES
    ).encode("utf-8")


def _canonical_text(value: str, label: str) -> str:
    if not value or "\x00" in value:
        raise ValueError(f"{label} must be non-empty text")
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def _decode_utf8(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc


def _json_bytes(value: object, *, compact: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "CrossModelRunManifest",
    "CrossModelSummaryDocument",
    "PRIVATE_CROSS_MODEL_ARTIFACT_FILES",
    "VerifiedCrossModelRunSnapshot",
    "load_verified_cross_model_run_snapshot",
    "publish_cross_model_run",
    "validate_current_cross_model_bindings",
    "verify_cross_model_run",
]
