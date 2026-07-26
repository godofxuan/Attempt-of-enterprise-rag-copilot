from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.indexing.paired_performance import (
    PairedArmMeasurement,
    PairedBenchmarkSummary,
    PairedDecisionProtocol,
    PairedMeasurement,
    RatioDistribution,
    decision_protocol_from_experiment_thresholds,
    frozen_decision_protocol,
    summarize_paired_measurements,
)
from app.ingestion.path_security import (
    absolute_path_has_redirect,
    stat_is_redirect,
)
from app.lifecycle.evidence import (
    EvidenceArtifactHash,
    ExperimentRecord,
    ExperimentStatus,
    resolve_bounded_file,
    validate_experiment_history,
    validate_repository_relative_path,
)


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"""(?ix)(?:^|[\s"'=])(?:[a-z]:[\\/]|\\\\[^\\\s]+[\\/]|//[^/\s]+/)"""
)
_POSIX_ABSOLUTE_PATH = re.compile(r"""(?:^|[\s"'=])/(?!/)[^\s]+""")
_SHELL_CONTROL = re.compile(r"(?:&&|\|\||[;&|<>`]|\$\()")
_PATH_TRAVERSAL = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
_MACHINE_PATH_EXPANSION = re.compile(
    r"(?i)(?:%[a-z_][a-z0-9_]*%|\$env:|"
    r"\$\{?(?:home|userprofile|temp|tmp)\}?|(?:^|\s)~[\\/])"
)
_PAIR_NUMBER = re.compile(r"(?:^|\s)--pair-number\s+([0-9]+)(?:\s|$)")
_EXPERIMENT_ID = re.compile(
    r"(?:^|\s)--experiment-id\s+(EXP-LC-[0-9]+)(?:\s|$)"
)
_BUNDLE_SHA256 = re.compile(
    r"(?:^|\s)--bundle-sha256\s+([0-9a-f]{64})(?:\s|$)"
)
_ARM = re.compile(r"(?:^|\s)--arm\s+(baseline|intervention)(?:\s|$)")
_EXECUTION_ORDER = re.compile(
    r"(?:^|\s)--execution-order\s+([12])(?:\s|$)"
)
_CONFIGURATION_SHA256 = re.compile(
    r"(?:^|\s)--configuration-sha256\s+([0-9a-f]{64})(?:\s|$)"
)
_HOST_SHA256 = re.compile(
    r"(?:^|\s)--host-sha256\s+([0-9a-f]{64})(?:\s|$)"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class G10EnvironmentArtifact(_FrozenModel):
    schema_version: Literal["g10_environment_v1", "g10_environment_v2"]
    bundle_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    host_identity_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_corpus_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    experiment_id: str | None = Field(
        default=None,
        pattern=r"^EXP-LC-[0-9]{3,}$",
    )
    source_commit_sha: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    source_tree_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    source_paths_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    requirements_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    runtime_dependencies_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    pipeline_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    source_file_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_version_shape(self) -> G10EnvironmentArtifact:
        common = {
            "schema_version",
            "bundle_manifest_sha256",
            "configuration_sha256",
            "host_identity_sha256",
            "source_corpus_manifest_sha256",
        }
        v2 = common | {
            "run_id",
            "experiment_id",
            "source_commit_sha",
            "source_tree_sha256",
            "source_paths_sha256",
            "requirements_sha256",
            "runtime_dependencies_sha256",
            "pipeline_sha256",
            "source_file_count",
        }
        expected = (
            common if self.schema_version == "g10_environment_v1" else v2
        )
        if self.model_fields_set != expected:
            raise ValueError(
                f"{self.schema_version} fields do not match its strict schema"
            )
        return self


class G10RunStatusArtifact(_FrozenModel):
    schema_version: Literal["g10_run_status_v1", "g10_run_status_v2"]
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    experiment_id: str | None = Field(
        default=None,
        pattern=r"^EXP-LC-[0-9]{3,}$",
    )
    bundle_manifest_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    configuration_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: Literal["COMPLETED"]
    requested_pairs: int = Field(ge=1)
    completed_pairs: int = Field(ge=1)
    worker_exit_code: Literal[0]

    @model_validator(mode="after")
    def validate_version_shape(self) -> G10RunStatusArtifact:
        common = {
            "schema_version",
            "run_id",
            "status",
            "requested_pairs",
            "completed_pairs",
            "worker_exit_code",
        }
        v2 = common | {
            "experiment_id",
            "bundle_manifest_sha256",
            "configuration_sha256",
            "started_at",
            "completed_at",
        }
        expected = common if self.schema_version == "g10_run_status_v1" else v2
        if self.model_fields_set != expected:
            raise ValueError(
                f"{self.schema_version} fields do not match its strict schema"
            )
        if self.schema_version == "g10_run_status_v2":
            if (
                self.started_at is None
                or self.started_at.tzinfo is None
                or self.started_at.utcoffset() is None
                or self.completed_at is None
                or self.completed_at.tzinfo is None
                or self.completed_at.utcoffset() is None
            ):
                raise ValueError("v2 run timestamps must be timezone-aware")
            if self.started_at >= self.completed_at:
                raise ValueError("v2 run timestamps are not ordered")
        return self


class LifecyclePerformancePublicSummary(_FrozenModel):
    schema_version: Literal["lifecycle_performance_public_summary_v1"] = (
        "lifecycle_performance_public_summary_v1"
    )
    synthetic: Literal[True] = True
    claim_scope: Literal["local deterministic lifecycle pipeline overhead"] = (
        "local deterministic lifecycle pipeline overhead"
    )
    artifact_schema_version: Literal[2] | None = None
    registered_experiment_id: str = Field(pattern=r"^EXP-LC-[0-9]{3,}$")
    completed_experiment_id: str = Field(pattern=r"^EXP-LC-[0-9]{3,}$")
    final_status: Literal[
        "SUPPORTED",
        "NO_MEASURABLE_BENEFIT",
        "REGRESSION",
    ]
    dataset_id: str = Field(min_length=1, max_length=200)
    dataset_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    pipeline_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_commit_sha: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    source_tree_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    sample_size: int = Field(ge=1)
    pair_count: int = Field(ge=1)
    correctness_equivalent_pair_count: int = Field(ge=0)
    active_index_deleted_residual_count: int = Field(ge=0)
    faster_pair_count: int = Field(ge=0)
    total_time_ratio: RatioDistribution
    baseline_first_median_ratio: float = Field(gt=0.0)
    intervention_first_median_ratio: float = Field(gt=0.0)
    baseline_embedding_calls: int = Field(ge=1)
    intervention_embedding_calls: int = Field(ge=0)
    intervention_embedding_call_ratio: float = Field(ge=0.0)
    baseline_peak_rss_bytes: int = Field(ge=0)
    intervention_peak_rss_bytes: int = Field(ge=0)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=20)
    raw_artifacts: tuple[EvidenceArtifactHash, ...] = Field(
        min_length=1,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_claim_shape(self) -> LifecyclePerformancePublicSummary:
        if (
            self.correctness_equivalent_pair_count > self.pair_count
            or self.faster_pair_count > self.pair_count
        ):
            raise ValueError("public performance counts exceed pair count")
        if self.final_status == "SUPPORTED" and (
            self.correctness_equivalent_pair_count != self.pair_count
            or self.active_index_deleted_residual_count != 0
        ):
            raise ValueError(
                "supported public claim requires exact correctness and deletion"
            )
        if (self.source_commit_sha is None) != (
            self.source_tree_sha256 is None
        ):
            raise ValueError(
                "source commit and source tree identities must appear together"
            )
        if self.artifact_schema_version == 2 and (
            self.source_commit_sha is None
            or self.source_tree_sha256 is None
        ):
            raise ValueError(
                "v2 public summary requires source commit and source tree"
            )
        if self.artifact_schema_version is None and (
            self.source_commit_sha is not None
            or self.source_tree_sha256 is not None
        ):
            raise ValueError(
                "legacy public summary cannot claim v2 source provenance"
            )
        return self


class LifecyclePerformanceExperimentIdentity(_FrozenModel):
    artifact_schema_version: Literal[1, 2] = 1
    registered_experiment_id: str = Field(pattern=r"^EXP-LC-[0-9]{3,}$")
    completed_experiment_id: str = Field(pattern=r"^EXP-LC-[0-9]{3,}$")
    dataset_id: str = Field(min_length=1, max_length=200)
    dataset_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=_SHA256_PATTERN)
    pipeline_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_commit_sha: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    source_tree_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    source_paths_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    requirements_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    runtime_dependencies_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    source_file_count: int | None = Field(default=None, ge=1)
    host_identity_sha256: str = Field(pattern=_SHA256_PATTERN)
    base_catalog_sha256: str = Field(pattern=_SHA256_PATTERN)
    target_catalog_sha256: str = Field(pattern=_SHA256_PATTERN)
    change_set_sha256: str = Field(pattern=_SHA256_PATTERN)
    query_set_sha256: str = Field(pattern=_SHA256_PATTERN)
    embedding_model: str = Field(min_length=1, max_length=256)
    sample_size: int = Field(ge=1)
    repetitions: int = Field(ge=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    decision_protocol: PairedDecisionProtocol

    @model_validator(mode="after")
    def validate_version_identity(
        self,
    ) -> LifecyclePerformanceExperimentIdentity:
        v2_values = (
            self.source_commit_sha,
            self.source_tree_sha256,
            self.source_paths_sha256,
            self.requirements_sha256,
            self.runtime_dependencies_sha256,
            self.source_file_count,
            self.started_at,
            self.completed_at,
        )
        if self.artifact_schema_version == 2 and any(
            value is None for value in v2_values
        ):
            raise ValueError(
                "v2 package identity requires complete source provenance"
            )
        if self.artifact_schema_version == 1 and any(
            value is not None for value in v2_values
        ):
            raise ValueError(
                "v1 package identity cannot contain v2 source provenance"
            )
        if self.started_at is not None and (
            self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
            or self.completed_at is None
            or self.completed_at.tzinfo is None
            or self.completed_at.utcoffset() is None
            or self.started_at >= self.completed_at
        ):
            raise ValueError("package transition timestamps are invalid")
        if self.decision_protocol != frozen_decision_protocol(
            self.repetitions
        ):
            raise ValueError(
                "package decision protocol differs from frozen G10 protocol"
            )
        return self


class PackagedRawArtifact(_FrozenModel):
    source_path: str
    package_file: EvidenceArtifactHash

    @model_validator(mode="after")
    def validate_paths(self) -> PackagedRawArtifact:
        validate_repository_relative_path(self.source_path)
        if not self.package_file.path.startswith("raw/"):
            raise ValueError("raw experiment artifacts must remain below raw/")
        return self


class LifecyclePerformanceEvidencePackageManifest(_FrozenModel):
    schema_version: Literal[
        "lifecycle_performance_evidence_package_v1"
    ] = "lifecycle_performance_evidence_package_v1"
    experiment: LifecyclePerformanceExperimentIdentity
    summary: EvidenceArtifactHash
    raw_artifacts: tuple[PackagedRawArtifact, ...] = Field(
        min_length=1,
        max_length=1000,
    )
    dataset_metadata: tuple[EvidenceArtifactHash, ...] = Field(
        default=(),
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_package_layout(
        self,
    ) -> LifecyclePerformanceEvidencePackageManifest:
        if self.summary.path != "summary.json":
            raise ValueError("package summary must be summary.json")
        source_paths = [item.source_path for item in self.raw_artifacts]
        package_paths = [
            item.package_file.path for item in self.raw_artifacts
        ]
        metadata_paths = [item.path for item in self.dataset_metadata]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("package contains duplicate raw source paths")
        all_payload_paths = package_paths + metadata_paths
        if len(all_payload_paths) != len(set(all_payload_paths)):
            raise ValueError("package contains duplicate payload paths")
        if any(not path.startswith("dataset/") for path in metadata_paths):
            raise ValueError("dataset metadata must remain below dataset/")
        return self


@dataclass(frozen=True)
class _ExpectedEvidenceIdentity:
    artifact_schema_version: int
    registered_experiment_id: str
    completed_experiment_id: str
    dataset_id: str
    dataset_sha256: str
    source_manifest_sha256: str
    configuration_sha256: str
    pipeline_sha256: str
    source_commit_sha: str | None
    source_tree_sha256: str | None
    source_paths_sha256: str | None
    requirements_sha256: str | None
    runtime_dependencies_sha256: str | None
    source_file_count: int | None
    host_identity_sha256: str
    base_catalog_sha256: str
    target_catalog_sha256: str
    change_set_sha256: str
    query_set_sha256: str
    embedding_model: str
    sample_size: int
    repetitions: int
    decision_protocol: PairedDecisionProtocol
    started_at: datetime | None
    completed_at: datetime | None

    def package_model(self) -> LifecyclePerformanceExperimentIdentity:
        return LifecyclePerformanceExperimentIdentity(**self.__dict__)


@dataclass(frozen=True)
class _ValidatedRawEvidence:
    benchmark: PairedBenchmarkSummary
    pairs: tuple[PairedMeasurement, ...]
    environment: G10EnvironmentArtifact
    status: G10RunStatusArtifact


def _canonical_model_bytes(model: BaseModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json", exclude_none=True),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_public_performance_summary_bytes(
    summary: LifecyclePerformancePublicSummary,
) -> bytes:
    return _canonical_model_bytes(summary)


def canonical_performance_package_manifest_bytes(
    manifest: LifecyclePerformanceEvidencePackageManifest,
) -> bytes:
    return _canonical_model_bytes(manifest)


def canonical_performance_package_checksums(
    artifacts: Sequence[EvidenceArtifactHash],
) -> bytes:
    paths = [artifact.path for artifact in artifacts]
    if len(paths) != len(set(paths)):
        raise ValueError("checksum manifest contains duplicate paths")
    return "".join(
        f"{artifact.sha256}  {artifact.path}\n"
        for artifact in sorted(artifacts, key=lambda item: item.path)
    ).encode("ascii")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _binding(path: str, content: bytes) -> EvidenceArtifactHash:
    return EvidenceArtifactHash(
        path=path,
        byte_count=len(content),
        sha256=_sha256(content),
    )


def _bound_artifacts(
    root: Path,
    record: ExperimentRecord,
) -> tuple[dict[str, bytes], tuple[EvidenceArtifactHash, ...]]:
    content_by_path: dict[str, bytes] = {}
    bindings: list[EvidenceArtifactHash] = []
    for relative_path, expected_sha256 in zip(
        record.raw_artifact_paths,
        record.raw_artifact_hashes,
        strict=True,
    ):
        path = resolve_bounded_file(root, relative_path)
        content = path.read_bytes()
        observed_sha256 = _sha256(content)
        if observed_sha256 != expected_sha256:
            raise ValueError(
                f"experiment artifact hash mismatch: {relative_path}"
            )
        content_by_path[relative_path] = content
        bindings.append(_binding(relative_path, content))
    return content_by_path, tuple(bindings)


def _aggregate_artifacts(
    content_by_path: Mapping[str, bytes],
) -> tuple[PurePosixPath, dict[str, bytes]]:
    required_names = {
        "summary.json",
        "pairs.jsonl",
        "environment.json",
        "commands.txt",
        "status.json",
    }
    selected_paths: dict[str, PurePosixPath] = {}
    for name in required_names:
        candidates = [
            PurePosixPath(path)
            for path in content_by_path
            if PurePosixPath(path).name == name
        ]
        if not candidates:
            raise ValueError(f"experiment does not bind aggregate {name}")
        minimum_depth = min(len(path.parts) for path in candidates)
        shallow = [
            path for path in candidates if len(path.parts) == minimum_depth
        ]
        if len(shallow) != 1:
            raise ValueError(
                f"experiment has ambiguous shallow aggregate {name}"
            )
        selected_paths[name] = shallow[0]
    parents = {path.parent for path in selected_paths.values()}
    if len(parents) != 1:
        raise ValueError("aggregate experiment artifacts use mixed roots")
    root = parents.pop()
    for name, path in selected_paths.items():
        if path != root / name:
            raise ValueError(f"aggregate {name} is not at the run root")
    return root, {
        name: content_by_path[path.as_posix()]
        for name, path in selected_paths.items()
    }


def _required_hash(environment: Mapping[str, object], key: str) -> str:
    value = environment.get(key)
    if (
        not isinstance(value, str)
        or re.fullmatch(_SHA256_PATTERN, value) is None
    ):
        raise ValueError(f"experiment environment requires SHA-256 {key}")
    return value


def _required_text(environment: Mapping[str, object], key: str) -> str:
    value = environment.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"experiment environment requires text {key}")
    return value


def _registered_experiment_id(
    record: ExperimentRecord,
    history: Sequence[ExperimentRecord] | None,
) -> str:
    if record.schema_version == 1:
        if record.revision_of is None:
            raise ValueError(
                "legacy completed experiment requires a revision parent"
            )
        return record.revision_of

    registered_id = _required_text(
        record.environment,
        "registered_experiment_id",
    )
    if re.fullmatch(r"EXP-LC-[0-9]{3,}", registered_id) is None:
        raise ValueError("v2 registered experiment identity is invalid")
    if history is None:
        raise ValueError(
            "v2 performance evidence requires the full experiment history"
        )
    records = list(history)
    validate_experiment_history(records)
    by_id = {item.experiment_id: item for item in records}
    if by_id.get(record.experiment_id) != record:
        raise ValueError("completed experiment is not bound to supplied history")
    running = (
        None
        if record.revision_of is None
        else by_id.get(record.revision_of)
    )
    registered = by_id.get(registered_id)
    if (
        running is None
        or running.status is not ExperimentStatus.RUNNING
        or running.schema_version != 2
        or running.revision_of != registered_id
        or registered is None
        or registered.status is not ExperimentStatus.REGISTERED
        or registered.schema_version != 2
    ):
        raise ValueError(
            "v2 experiment history is not REGISTERED -> RUNNING -> COMPLETED"
        )
    return registered_id


def _expected_from_record(
    record: ExperimentRecord,
    *,
    history: Sequence[ExperimentRecord] | None = None,
) -> _ExpectedEvidenceIdentity:
    registered_id = _registered_experiment_id(record, history)
    decision_protocol = decision_protocol_from_experiment_thresholds(
        success_thresholds=record.success_thresholds,
        failure_thresholds=record.failure_thresholds,
        expected_pair_count=record.repetitions,
    )
    is_v2 = record.schema_version == 2
    return _ExpectedEvidenceIdentity(
        artifact_schema_version=record.schema_version,
        registered_experiment_id=registered_id,
        completed_experiment_id=record.experiment_id,
        dataset_id=record.dataset_id,
        dataset_sha256=record.dataset_sha256,
        source_manifest_sha256=_required_hash(
            record.environment,
            "source_manifest_sha256",
        ),
        configuration_sha256=_required_hash(
            record.environment,
            "configuration_sha256",
        ),
        pipeline_sha256=_required_hash(
            record.environment,
            "pipeline_sha256",
        ),
        source_commit_sha=(
            _required_text(record.environment, "source_commit_sha")
            if is_v2
            else None
        ),
        source_tree_sha256=(
            _required_hash(record.environment, "source_tree_sha256")
            if is_v2
            else None
        ),
        source_paths_sha256=(
            _required_hash(record.environment, "source_paths_sha256")
            if is_v2
            else None
        ),
        requirements_sha256=(
            _required_hash(record.environment, "requirements_sha256")
            if is_v2
            else None
        ),
        runtime_dependencies_sha256=(
            _required_hash(
                record.environment,
                "runtime_dependencies_sha256",
            )
            if is_v2
            else None
        ),
        source_file_count=(
            record.environment.get("source_file_count")
            if is_v2
            else None
        ),
        host_identity_sha256=_required_hash(
            record.environment,
            "host_identity_sha256",
        ),
        base_catalog_sha256=_required_hash(
            record.environment,
            "bundle_base_catalog_sha256",
        ),
        target_catalog_sha256=_required_hash(
            record.environment,
            "bundle_target_catalog_sha256",
        ),
        change_set_sha256=_required_hash(
            record.environment,
            "bundle_change_descriptor_sha256",
        ),
        query_set_sha256=_required_hash(
            record.environment,
            "bundle_query_descriptor_sha256",
        ),
        embedding_model=_required_text(
            record.environment,
            "embedding_model",
        ),
        sample_size=record.sample_size,
        repetitions=record.repetitions,
        decision_protocol=decision_protocol,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def _safe_command_lines(
    content: bytes,
    *,
    expected_count: int,
) -> tuple[str, ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("commands artifact must be UTF-8") from exc
    if not text or not text.strip():
        raise ValueError("commands artifact cannot be empty")
    if "\x00" in text or any(
        ord(character) < 32 and character not in {"\r", "\n"}
        for character in text
    ):
        raise ValueError("commands artifact contains control characters")
    lines = text.splitlines()
    if len(lines) != expected_count or any(
        not line or line != line.strip() or len(line) > 16_384
        for line in lines
    ):
        raise ValueError("commands artifact has an invalid command count")
    for line in lines:
        if (
            _WINDOWS_ABSOLUTE_PATH.search(line)
            or _POSIX_ABSOLUTE_PATH.search(line)
            or _SHELL_CONTROL.search(line)
            or _PATH_TRAVERSAL.search(line)
            or _MACHINE_PATH_EXPANSION.search(line)
        ):
            raise ValueError(
                "commands artifact contains an unsafe command or machine path"
            )
    return tuple(lines)


def _command_identity(
    line: str,
) -> tuple[int, str, str]:
    pair_match = _PAIR_NUMBER.search(line)
    experiment_match = _EXPERIMENT_ID.search(line)
    bundle_match = _BUNDLE_SHA256.search(line)
    if (
        pair_match is None
        or experiment_match is None
        or bundle_match is None
    ):
        raise ValueError(
            "commands artifact omits a required paired-run identity"
        )
    return (
        int(pair_match.group(1)),
        experiment_match.group(1),
        bundle_match.group(1),
    )


def _validate_aggregate_commands(
    content: bytes,
    expected: _ExpectedEvidenceIdentity,
) -> tuple[str, ...]:
    lines = _safe_command_lines(
        content,
        expected_count=expected.repetitions,
    )
    pair_numbers: list[int] = []
    for line in lines:
        if re.search(r"(?:^|\s)pair-worker(?:\s|$)", line) is None:
            raise ValueError("aggregate command is not a pair worker command")
        pair_number, experiment_id, bundle_sha256 = _command_identity(line)
        if experiment_id != expected.registered_experiment_id:
            raise ValueError("commands artifact uses a mixed experiment ID")
        if bundle_sha256 != expected.dataset_sha256:
            raise ValueError("commands artifact uses a mixed bundle identity")
        pair_numbers.append(pair_number)
    if sorted(pair_numbers) != list(range(1, expected.repetitions + 1)):
        raise ValueError("commands artifact pair IDs are not contiguous")
    return lines


def _validate_pair_commands(
    content: bytes,
    *,
    pair: PairedMeasurement,
    expected: _ExpectedEvidenceIdentity,
) -> None:
    lines = _safe_command_lines(content, expected_count=2)
    observed_arms: set[str] = set()
    for line in lines:
        if re.search(r"(?:^|\s)arm-worker(?:\s|$)", line) is None:
            raise ValueError("pair command is not an arm worker command")
        pair_number, experiment_id, bundle_sha256 = _command_identity(line)
        arm_match = _ARM.search(line)
        order_match = _EXECUTION_ORDER.search(line)
        configuration_match = _CONFIGURATION_SHA256.search(line)
        host_match = _HOST_SHA256.search(line)
        if (
            arm_match is None
            or order_match is None
            or configuration_match is None
            or host_match is None
        ):
            raise ValueError("pair command omits an arm execution identity")
        arm = arm_match.group(1)
        measurement = getattr(pair, arm)
        if (
            pair_number != pair.baseline.pair_number
            or experiment_id != expected.registered_experiment_id
            or bundle_sha256 != expected.dataset_sha256
            or int(order_match.group(1)) != measurement.execution_order
            or configuration_match.group(1)
            != expected.configuration_sha256
            or host_match.group(1) != expected.host_identity_sha256
        ):
            raise ValueError("pair command uses a mixed execution identity")
        observed_arms.add(arm)
    if observed_arms != {"baseline", "intervention"}:
        raise ValueError("pair commands do not bind both execution arms")


def _validate_child_artifacts(
    *,
    content_by_path: Mapping[str, bytes],
    aggregate_root: PurePosixPath,
    pairs: Sequence[PairedMeasurement],
    expected: _ExpectedEvidenceIdentity,
) -> None:
    pair_root = aggregate_root / "pairs"
    actual_paths = {
        PurePosixPath(path)
        for path in content_by_path
        if PurePosixPath(path).is_relative_to(pair_root)
    }
    if expected.artifact_schema_version == 1:
        if actual_paths:
            raise ValueError(
                "legacy experiment cannot partially bind v2 pair artifacts"
            )
        return

    expected_paths = {
        pair_root / f"{pair_number:03d}" / name
        for pair_number in range(1, expected.repetitions + 1)
        for name in (
            "baseline.json",
            "intervention.json",
            "pair.json",
            "commands.txt",
        )
    }
    if actual_paths != expected_paths:
        raise ValueError(
            "v2 experiment must bind exactly four artifacts per pair"
        )
    for pair in pairs:
        pair_number = pair.baseline.pair_number
        root = pair_root / f"{pair_number:03d}"
        child_pair = PairedMeasurement.model_validate_json(
            content_by_path[(root / "pair.json").as_posix()]
        )
        baseline = PairedArmMeasurement.model_validate_json(
            content_by_path[(root / "baseline.json").as_posix()]
        )
        intervention = PairedArmMeasurement.model_validate_json(
            content_by_path[(root / "intervention.json").as_posix()]
        )
        if child_pair != pair:
            raise ValueError(
                f"pair {pair_number:03d} child does not match pairs.jsonl"
            )
        if baseline != pair.baseline or intervention != pair.intervention:
            raise ValueError(
                f"pair {pair_number:03d} arm child does not match pair.json"
            )
        _validate_pair_commands(
            content_by_path[(root / "commands.txt").as_posix()],
            pair=pair,
            expected=expected,
        )


def _validate_raw_evidence(
    content_by_path: Mapping[str, bytes],
    expected: _ExpectedEvidenceIdentity,
) -> _ValidatedRawEvidence:
    aggregate_root, aggregates = _aggregate_artifacts(content_by_path)
    environment = G10EnvironmentArtifact.model_validate_json(
        aggregates["environment.json"]
    )
    status = G10RunStatusArtifact.model_validate_json(
        aggregates["status.json"]
    )
    _validate_aggregate_commands(
        aggregates["commands.txt"],
        expected,
    )
    if (
        status.requested_pairs != expected.repetitions
        or status.completed_pairs != expected.repetitions
    ):
        raise ValueError(
            "run status pair counts do not match experiment repetitions"
        )
    expected_environment_version = (
        "g10_environment_v2"
        if expected.artifact_schema_version == 2
        else "g10_environment_v1"
    )
    expected_status_version = (
        "g10_run_status_v2"
        if expected.artifact_schema_version == 2
        else "g10_run_status_v1"
    )
    if (
        environment.schema_version != expected_environment_version
        or status.schema_version != expected_status_version
    ):
        raise ValueError(
            "experiment record and raw artifact schema versions differ"
        )

    environment_checks = {
        "bundle manifest": (
            environment.bundle_manifest_sha256,
            expected.dataset_sha256,
        ),
        "configuration": (
            environment.configuration_sha256,
            expected.configuration_sha256,
        ),
        "host": (
            environment.host_identity_sha256,
            expected.host_identity_sha256,
        ),
        "source manifest": (
            environment.source_corpus_manifest_sha256,
            expected.source_manifest_sha256,
        ),
    }
    if expected.artifact_schema_version == 2:
        environment_checks.update(
            {
                "pipeline": (
                    environment.pipeline_sha256,
                    expected.pipeline_sha256,
                ),
                "source commit": (
                    environment.source_commit_sha,
                    expected.source_commit_sha,
                ),
                "source tree": (
                    environment.source_tree_sha256,
                    expected.source_tree_sha256,
                ),
                "source paths": (
                    environment.source_paths_sha256,
                    expected.source_paths_sha256,
                ),
                "requirements": (
                    environment.requirements_sha256,
                    expected.requirements_sha256,
                ),
                "runtime dependencies": (
                    environment.runtime_dependencies_sha256,
                    expected.runtime_dependencies_sha256,
                ),
                "source file count": (
                    environment.source_file_count,
                    expected.source_file_count,
                ),
            }
        )
    for label, (observed, wanted) in environment_checks.items():
        if observed != wanted:
            raise ValueError(
                f"environment artifact uses a mixed {label} identity"
            )
    if expected.artifact_schema_version == 2 and (
        environment.run_id != status.run_id
        or environment.experiment_id
        != expected.registered_experiment_id
        or status.experiment_id != expected.registered_experiment_id
        or status.bundle_manifest_sha256 != expected.dataset_sha256
        or status.configuration_sha256 != expected.configuration_sha256
        or status.started_at != expected.started_at
        or status.completed_at != expected.completed_at
    ):
        raise ValueError(
            "v2 environment, status, and experiment transition identities differ"
        )

    pair_lines = aggregates["pairs.jsonl"].splitlines()
    if not pair_lines or any(not line.strip() for line in pair_lines):
        raise ValueError("paired measurement artifact cannot contain blank lines")
    pairs = tuple(
        PairedMeasurement.model_validate_json(line)
        for line in pair_lines
    )
    if len(pairs) != expected.repetitions:
        raise ValueError("paired measurement count does not match repetitions")
    observed_pair_ids = [pair.baseline.pair_number for pair in pairs]
    if observed_pair_ids != list(range(1, expected.repetitions + 1)):
        raise ValueError(
            "paired measurement IDs must be ordered and contiguous"
        )

    arm_identity = {
        "experiment_id": expected.registered_experiment_id,
        "bundle_manifest_sha256": expected.dataset_sha256,
        "base_catalog_sha256": expected.base_catalog_sha256,
        "target_catalog_sha256": expected.target_catalog_sha256,
        "change_set_sha256": expected.change_set_sha256,
        "query_set_sha256": expected.query_set_sha256,
        "pipeline_sha256": expected.pipeline_sha256,
        "embedding_model": expected.embedding_model,
        "host_identity_sha256": expected.host_identity_sha256,
        "configuration_sha256": expected.configuration_sha256,
    }
    for pair in pairs:
        for field_name, wanted in arm_identity.items():
            observed = getattr(pair.baseline, field_name)
            if observed != wanted:
                raise ValueError(
                    f"paired measurement uses a mixed {field_name} identity"
                )

    benchmark = PairedBenchmarkSummary.model_validate_json(
        aggregates["summary.json"]
    )
    recomputed = summarize_paired_measurements(
        pairs,
        expected_pair_count=expected.repetitions,
        decision_protocol=expected.decision_protocol,
    )
    if recomputed != benchmark:
        raise ValueError("stored paired summary does not recompute exactly")
    if benchmark.experiment_id != expected.registered_experiment_id:
        raise ValueError("paired summary uses a mixed experiment ID")
    _validate_child_artifacts(
        content_by_path=content_by_path,
        aggregate_root=aggregate_root,
        pairs=pairs,
        expected=expected,
    )
    return _ValidatedRawEvidence(
        benchmark=benchmark,
        pairs=pairs,
        environment=environment,
        status=status,
    )


def _public_summary(
    *,
    expected: _ExpectedEvidenceIdentity,
    validated: _ValidatedRawEvidence,
    final_status: str,
    limitations: Sequence[str],
    artifact_bindings: Sequence[EvidenceArtifactHash],
) -> LifecyclePerformancePublicSummary:
    benchmark = validated.benchmark
    if benchmark.decision != final_status:
        raise ValueError("experiment final status does not match measurements")
    residual_count = max(
        pair.baseline.target_fingerprint.active_index_deleted_residual_count
        for pair in validated.pairs
    )
    return LifecyclePerformancePublicSummary(
        artifact_schema_version=(
            2 if expected.artifact_schema_version == 2 else None
        ),
        registered_experiment_id=expected.registered_experiment_id,
        completed_experiment_id=expected.completed_experiment_id,
        final_status=benchmark.decision,
        dataset_id=expected.dataset_id,
        dataset_sha256=expected.dataset_sha256,
        source_manifest_sha256=expected.source_manifest_sha256,
        configuration_sha256=expected.configuration_sha256,
        pipeline_sha256=expected.pipeline_sha256,
        source_commit_sha=expected.source_commit_sha,
        source_tree_sha256=expected.source_tree_sha256,
        sample_size=expected.sample_size,
        pair_count=benchmark.pair_count,
        correctness_equivalent_pair_count=(
            benchmark.correctness_equivalent_pair_count
        ),
        active_index_deleted_residual_count=residual_count,
        faster_pair_count=benchmark.faster_pair_count,
        total_time_ratio=benchmark.total_time_ratio,
        baseline_first_median_ratio=(
            benchmark.baseline_first_total_time_ratio.p50
        ),
        intervention_first_median_ratio=(
            benchmark.intervention_first_total_time_ratio.p50
        ),
        baseline_embedding_calls=benchmark.baseline_embedding_calls,
        intervention_embedding_calls=benchmark.intervention_embedding_calls,
        intervention_embedding_call_ratio=(
            benchmark.intervention_embedding_call_ratio
        ),
        baseline_peak_rss_bytes=benchmark.baseline_peak_rss_bytes,
        intervention_peak_rss_bytes=benchmark.intervention_peak_rss_bytes,
        limitations=tuple(limitations),
        raw_artifacts=tuple(artifact_bindings),
    )


def build_public_performance_summary(
    root: Path,
    record: ExperimentRecord,
    *,
    history: Sequence[ExperimentRecord] | None = None,
) -> LifecyclePerformancePublicSummary:
    root = Path(root).resolve(strict=True)
    if (
        record.status is not ExperimentStatus.COMPLETED
        or record.final_status is None
        or record.revision_of is None
    ):
        raise ValueError("public performance evidence requires a completed run")
    expected = _expected_from_record(record, history=history)
    content_by_path, artifact_bindings = _bound_artifacts(root, record)
    validated = _validate_raw_evidence(content_by_path, expected)
    result_summary = record.result_summary
    benchmark = validated.benchmark
    if (
        result_summary.get("pair_count") != benchmark.pair_count
        or result_summary.get("median_total_time_ratio")
        != benchmark.total_time_ratio.p50
        or result_summary.get("p95_total_time_ratio")
        != benchmark.total_time_ratio.p95
        or result_summary.get("faster_pair_count")
        != benchmark.faster_pair_count
        or result_summary.get("embedding_call_ratio")
        != benchmark.intervention_embedding_call_ratio
    ):
        raise ValueError(
            "completed experiment result projection does not match summary"
        )
    return _public_summary(
        expected=expected,
        validated=validated,
        final_status=record.final_status.value,
        limitations=record.limitations,
        artifact_bindings=artifact_bindings,
    )


def experiment_identity_from_record(
    record: ExperimentRecord,
    *,
    history: Sequence[ExperimentRecord] | None = None,
) -> LifecyclePerformanceExperimentIdentity:
    return _expected_from_record(record, history=history).package_model()


def package_path_for_raw_artifact(source_path: str) -> str:
    normalized = validate_repository_relative_path(source_path)
    return str(PurePosixPath("raw") / PurePosixPath(normalized))


def package_path_for_dataset_metadata(source_path: str) -> str:
    normalized = validate_repository_relative_path(source_path)
    return str(PurePosixPath("dataset") / PurePosixPath(normalized))


def _package_regular_files(root: Path) -> set[str]:
    files: set[str] = set()
    for current, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current)
        for name in directory_names:
            path = current_path / name
            if stat_is_redirect(path.lstat()):
                raise ValueError("evidence package cannot contain symlinks")
        for name in file_names:
            path = current_path / name
            if stat_is_redirect(path.lstat()) or not path.is_file():
                raise ValueError(
                    "evidence package payloads must be regular files"
                )
            files.add(path.relative_to(root).as_posix())
    return files


def verify_public_performance_evidence_package(
    package_root: Path,
) -> LifecyclePerformancePublicSummary:
    package_root = Path(package_root).absolute()
    if absolute_path_has_redirect(package_root) or not package_root.is_dir():
        raise ValueError("performance evidence package must be a directory")
    root = package_root.resolve(strict=True)
    manifest_content = resolve_bounded_file(
        root,
        "manifest.json",
    ).read_bytes()
    manifest = LifecyclePerformanceEvidencePackageManifest.model_validate_json(
        manifest_content
    )
    if (
        manifest_content
        != canonical_performance_package_manifest_bytes(manifest)
    ):
        raise ValueError("package manifest is not canonical JSON")

    declared_payloads = (
        [manifest.summary]
        + [item.package_file for item in manifest.raw_artifacts]
        + list(manifest.dataset_metadata)
    )
    manifest_binding = _binding("manifest.json", manifest_content)
    expected_checksum_content = canonical_performance_package_checksums(
        [manifest_binding, *declared_payloads]
    )
    checksum_content = resolve_bounded_file(
        root,
        "checksums.sha256",
    ).read_bytes()
    if checksum_content != expected_checksum_content:
        raise ValueError("package checksum manifest is not canonical")

    expected_files = {
        "manifest.json",
        "checksums.sha256",
        *(artifact.path for artifact in declared_payloads),
    }
    if _package_regular_files(root) != expected_files:
        raise ValueError("package contains missing or undeclared files")

    for artifact in declared_payloads:
        content = resolve_bounded_file(root, artifact.path).read_bytes()
        if (
            len(content) != artifact.byte_count
            or _sha256(content) != artifact.sha256
        ):
            raise ValueError(f"package artifact hash mismatch: {artifact.path}")

    summary_content = resolve_bounded_file(
        root,
        manifest.summary.path,
    ).read_bytes()
    observed_summary = LifecyclePerformancePublicSummary.model_validate_json(
        summary_content
    )
    if (
        summary_content
        != canonical_public_performance_summary_bytes(observed_summary)
    ):
        raise ValueError("public performance summary is not canonical JSON")

    raw_by_source = {
        artifact.source_path: resolve_bounded_file(
            root,
            artifact.package_file.path,
        ).read_bytes()
        for artifact in manifest.raw_artifacts
    }
    source_bindings = tuple(
        _binding(artifact.source_path, raw_by_source[artifact.source_path])
        for artifact in manifest.raw_artifacts
    )
    if source_bindings != observed_summary.raw_artifacts:
        raise ValueError("public summary does not bind packaged raw artifacts")

    identity = manifest.experiment
    identity_payload = identity.model_dump()
    identity_payload["decision_protocol"] = identity.decision_protocol
    expected = _ExpectedEvidenceIdentity(**identity_payload)
    if (
        observed_summary.registered_experiment_id
        != identity.registered_experiment_id
        or observed_summary.completed_experiment_id
        != identity.completed_experiment_id
        or observed_summary.dataset_id != identity.dataset_id
        or observed_summary.dataset_sha256 != identity.dataset_sha256
        or observed_summary.source_manifest_sha256
        != identity.source_manifest_sha256
        or observed_summary.configuration_sha256
        != identity.configuration_sha256
        or observed_summary.pipeline_sha256 != identity.pipeline_sha256
        or observed_summary.source_commit_sha != identity.source_commit_sha
        or observed_summary.source_tree_sha256
        != identity.source_tree_sha256
        or observed_summary.sample_size != identity.sample_size
        or observed_summary.pair_count != identity.repetitions
        or observed_summary.artifact_schema_version
        != (
            2 if identity.artifact_schema_version == 2 else None
        )
    ):
        raise ValueError(
            "package experiment identity does not match public summary"
        )
    validated = _validate_raw_evidence(raw_by_source, expected)
    recomputed_summary = _public_summary(
        expected=expected,
        validated=validated,
        final_status=observed_summary.final_status,
        limitations=observed_summary.limitations,
        artifact_bindings=source_bindings,
    )
    if recomputed_summary != observed_summary:
        raise ValueError("packaged public summary does not recompute exactly")
    return observed_summary


__all__ = [
    "G10EnvironmentArtifact",
    "G10RunStatusArtifact",
    "LifecyclePerformanceEvidencePackageManifest",
    "LifecyclePerformanceExperimentIdentity",
    "LifecyclePerformancePublicSummary",
    "PackagedRawArtifact",
    "build_public_performance_summary",
    "canonical_performance_package_checksums",
    "canonical_performance_package_manifest_bytes",
    "canonical_public_performance_summary_bytes",
    "experiment_identity_from_record",
    "package_path_for_dataset_metadata",
    "package_path_for_raw_artifact",
    "verify_public_performance_evidence_package",
]
