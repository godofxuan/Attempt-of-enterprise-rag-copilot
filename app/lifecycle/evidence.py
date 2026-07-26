from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


MAX_JSONL_BYTES = 32 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 1024 * 1024
MAX_EVIDENCE_ARTIFACT_BYTES = 256 * 1024 * 1024
SHA256_PATTERN = r"^[0-9a-f]{64}$"
EXPERIMENT_ID_PATTERN = r"^EXP-LC-[0-9]{3,}$"
FAILURE_ID_PATTERN = r"^FAIL-LC-[0-9]{3,}$"
RESEARCH_REQUEST_ID_PATTERN = r"^RR-LC-[0-9]{3,}$"
REQUIREMENT_ID_PATTERN = r"^REQ-LC-[0-9]{3,}$"

JsonScalar = str | int | float | bool | None


class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExperimentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ExperimentFinalStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    NO_MEASURABLE_BENEFIT = "NO_MEASURABLE_BENEFIT"
    REGRESSION = "REGRESSION"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value


def validate_repository_relative_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("evidence path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("evidence path must remain repository-relative")
    if ":" in path.parts[0]:
        raise ValueError("evidence path must not contain a drive or URI scheme")
    return value


def _require_unique(values: list[str], field_name: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be unique")
    return values


class ExperimentRecord(StrictEvidenceModel):
    schema_version: Literal[1, 2] = 1
    experiment_id: str = Field(pattern=EXPERIMENT_ID_PATTERN)
    registered_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: ExperimentStatus
    hypothesis: str = Field(min_length=1, max_length=4000)
    baseline: str = Field(min_length=1, max_length=4000)
    intervention: str = Field(min_length=1, max_length=4000)
    controlled_variables: list[str] = Field(min_length=1, max_length=100)
    dataset_id: str = Field(min_length=1, max_length=200)
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    sample_size: int = Field(ge=1)
    repetitions: int = Field(ge=1)
    metrics: list[str] = Field(min_length=1, max_length=100)
    success_thresholds: dict[str, JsonScalar] = Field(min_length=1, max_length=100)
    failure_thresholds: dict[str, JsonScalar] = Field(min_length=1, max_length=100)
    environment: dict[str, JsonScalar] = Field(min_length=1, max_length=100)
    commands: list[str] = Field(min_length=1, max_length=100)
    raw_artifact_paths: list[str] = Field(default_factory=list, max_length=1000)
    raw_artifact_hashes: list[str] = Field(default_factory=list, max_length=1000)
    result_summary: dict[str, JsonScalar] = Field(default_factory=dict, max_length=200)
    uncertainty: dict[str, JsonScalar] = Field(default_factory=dict, max_length=100)
    final_status: ExperimentFinalStatus | None = None
    decision: str = Field(default="", max_length=4000)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    revision_of: str | None = Field(default=None, pattern=EXPERIMENT_ID_PATTERN)
    revision_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("registered_at")
    @classmethod
    def validate_registered_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "registered_at")

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_transition_timestamp(
        cls,
        value: datetime | None,
        info: Any,
    ) -> datetime | None:
        return None if value is None else _require_aware(value, info.field_name)

    @field_validator(
        "controlled_variables",
        "metrics",
        "commands",
        "raw_artifact_paths",
        "raw_artifact_hashes",
        "limitations",
    )
    @classmethod
    def validate_unique_lists(
        cls, values: list[str], info: Any
    ) -> list[str]:
        return _require_unique(values, info.field_name)

    @field_validator("raw_artifact_paths")
    @classmethod
    def validate_artifact_paths(cls, values: list[str]) -> list[str]:
        return [validate_repository_relative_path(value) for value in values]

    @field_validator("raw_artifact_hashes")
    @classmethod
    def validate_artifact_hashes(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("raw artifact hashes must be lowercase SHA-256")
        return values

    @model_validator(mode="after")
    def validate_state(self) -> ExperimentRecord:
        if len(self.raw_artifact_paths) != len(self.raw_artifact_hashes):
            raise ValueError("raw artifact paths and hashes must have equal length")
        if self.revision_of == self.experiment_id:
            raise ValueError("experiment revision cannot reference itself")
        if self.revision_of is None and self.revision_reason is not None:
            raise ValueError("revision_reason requires revision_of")
        if self.revision_of is not None and self.revision_reason is None:
            raise ValueError("experiment revision requires revision_reason")

        if self.schema_version == 1:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError(
                    "transition timestamps require experiment schema_version 2"
                )
        elif self.status is ExperimentStatus.REGISTERED:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError(
                    "REGISTERED v2 experiment has registered_at only"
                )
        elif self.status is ExperimentStatus.RUNNING:
            if self.started_at is None:
                raise ValueError("RUNNING v2 experiment requires started_at")
            if self.completed_at is not None:
                raise ValueError("RUNNING v2 experiment cannot contain completed_at")
        elif self.status is ExperimentStatus.COMPLETED:
            if self.started_at is None:
                raise ValueError("COMPLETED v2 experiment requires started_at")
            if self.completed_at is None:
                raise ValueError("COMPLETED v2 experiment requires completed_at")

        if (
            self.started_at is not None
            and self.registered_at >= self.started_at
        ):
            raise ValueError("registered_at must be earlier than started_at")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.started_at >= self.completed_at
        ):
            raise ValueError("started_at must be earlier than completed_at")

        has_result = bool(
            self.raw_artifact_paths
            or self.result_summary
            or self.uncertainty
            or self.final_status is not None
            or self.decision
        )
        if self.status is ExperimentStatus.REGISTERED:
            if self.revision_of is not None or has_result:
                raise ValueError(
                    "REGISTERED experiment must be an immutable preregistration "
                    "without revision or result fields"
                )
        elif self.status is ExperimentStatus.RUNNING:
            if self.revision_of is None:
                raise ValueError("RUNNING experiment must revise a preregistration")
            if has_result:
                raise ValueError("RUNNING experiment cannot contain final result fields")
        elif self.status is ExperimentStatus.COMPLETED:
            if self.revision_of is None:
                raise ValueError("COMPLETED experiment must revise a preregistration")
            if self.final_status is None:
                raise ValueError("COMPLETED experiment requires final_status")
            if not self.result_summary:
                raise ValueError("COMPLETED experiment requires result_summary")
            if not self.decision:
                raise ValueError("COMPLETED experiment requires decision")
        return self


EXPERIMENT_PREREGISTRATION_FIELDS = (
    "registered_at",
    "hypothesis",
    "baseline",
    "intervention",
    "controlled_variables",
    "dataset_id",
    "dataset_sha256",
    "sample_size",
    "repetitions",
    "metrics",
    "success_thresholds",
    "failure_thresholds",
    "environment",
    "commands",
)


def validate_experiment_history(records: list[ExperimentRecord]) -> None:
    by_id: dict[str, ExperimentRecord] = {}
    for record in records:
        if record.experiment_id in by_id:
            raise ValueError(f"duplicate experiment_id: {record.experiment_id}")
        if record.revision_of is not None:
            parent = by_id.get(record.revision_of)
            if parent is None:
                raise ValueError(
                    f"experiment revision parent is missing or out of order: "
                    f"{record.revision_of}"
                )
            for field_name in EXPERIMENT_PREREGISTRATION_FIELDS:
                if getattr(record, field_name) != getattr(parent, field_name):
                    raise ValueError(
                        f"preregistered field {field_name} changed in "
                        f"{record.experiment_id}"
                    )
            if record.schema_version != parent.schema_version:
                raise ValueError("experiment schema_version changed in revision")
            if record.schema_version == 2:
                expected_parent_status = (
                    ExperimentStatus.REGISTERED
                    if record.status is ExperimentStatus.RUNNING
                    else ExperimentStatus.RUNNING
                    if record.status is ExperimentStatus.COMPLETED
                    else ExperimentStatus.COMPLETED
                )
                if parent.status is not expected_parent_status:
                    raise ValueError(
                        "v2 experiment transition has invalid parent status"
                    )
                if (
                    record.status is ExperimentStatus.COMPLETED
                    and record.started_at != parent.started_at
                ):
                    raise ValueError(
                        "v2 completed experiment changed started_at"
                    )
            if (
                parent.status is ExperimentStatus.COMPLETED
                and record.status is not ExperimentStatus.COMPLETED
            ):
                raise ValueError("completed experiment can only receive a correction")
        by_id[record.experiment_id] = record


class FailureRecord(StrictEvidenceModel):
    failure_id: str = Field(pattern=FAILURE_ID_PATTERN)
    first_seen_at: datetime
    gate: str = Field(pattern=r"^G[0-9]+$", max_length=20)
    related_requirements: list[str] = Field(max_length=100)
    input_fixture_ids: list[str] = Field(max_length=100)
    expected_behavior: str = Field(min_length=1, max_length=4000)
    actual_behavior: str = Field(min_length=1, max_length=4000)
    error_taxonomy: str = Field(min_length=1, max_length=200)
    security_impact: str = Field(min_length=1, max_length=2000)
    reproduction_commands: list[str] = Field(min_length=1, max_length=100)
    root_cause: str = Field(min_length=1, max_length=4000)
    attempted_fixes: list[str] = Field(max_length=100)
    fix_commit: str = Field(default="", max_length=64)
    regression_test_ids: list[str] = Field(max_length=100)
    status: str = Field(pattern=r"^(OPEN|RESOLVED|SUPERSEDED)$")
    resolved_at: datetime | None = None
    superseded_by: str = Field(default="", max_length=100)

    @field_validator("first_seen_at")
    @classmethod
    def validate_first_seen_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "first_seen_at")

    @field_validator("resolved_at")
    @classmethod
    def validate_resolved_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware(value, "resolved_at")

    @field_validator("related_requirements")
    @classmethod
    def validate_requirement_ids(cls, values: list[str]) -> list[str]:
        _require_unique(values, "related_requirements")
        for value in values:
            if not value.startswith("REQ-LC-"):
                raise ValueError("related requirements must use REQ-LC identifiers")
        return values

    @model_validator(mode="after")
    def validate_resolution(self) -> FailureRecord:
        if self.status == "RESOLVED" and self.resolved_at is None:
            raise ValueError("resolved failure requires resolved_at")
        if self.status == "OPEN" and self.resolved_at is not None:
            raise ValueError("open failure cannot contain resolved_at")
        if self.status == "SUPERSEDED" and not self.superseded_by:
            raise ValueError("superseded failure requires superseded_by")
        return self


class ResearchRequestRecord(StrictEvidenceModel):
    request_id: str = Field(pattern=RESEARCH_REQUEST_ID_PATTERN)
    created_at: datetime
    blocking: bool
    question: str = Field(min_length=1, max_length=4000)
    current_evidence: list[str] = Field(max_length=100)
    decision_needed: str = Field(min_length=1, max_length=4000)
    safe_default: str = Field(min_length=1, max_length=4000)
    affected_requirements: list[str] = Field(min_length=1, max_length=100)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "created_at")

    @field_validator("affected_requirements")
    @classmethod
    def validate_affected_requirements(cls, values: list[str]) -> list[str]:
        _require_unique(values, "affected_requirements")
        for value in values:
            if not value.startswith("REQ-LC-"):
                raise ValueError("affected requirements must use REQ-LC identifiers")
        return values


class EvidencePrefixAnchor(StrictEvidenceModel):
    path: str
    accepted_bytes: int = Field(ge=0)
    record_count: int = Field(ge=0)
    prefix_sha256: str = Field(pattern=SHA256_PATTERN)
    accepted_at_gate: str = Field(pattern=r"^G[0-9]+$", max_length=20)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_repository_relative_path(value)


class EvidenceArtifactHash(StrictEvidenceModel):
    path: str
    byte_count: int = Field(ge=0)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_repository_relative_path(value)


RecordT = TypeVar("RecordT", bound=BaseModel)


def load_jsonl_records(path: Path, model: type[RecordT]) -> list[RecordT]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"JSONL evidence must be a regular file: {path.name}")
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise ValueError(f"JSONL evidence exceeds {MAX_JSONL_BYTES} bytes: {path.name}")

    records: list[RecordT] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            raise ValueError(f"blank JSONL line at {path.name}:{line_number}")
        if len(raw_line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
            raise ValueError(f"JSONL line exceeds limit at {path.name}:{line_number}")
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSON at {path.name}:{line_number}: {exc.msg}"
            ) from exc
        records.append(model.model_validate(payload))
    return records


def _canonical_json_line(record: BaseModel) -> bytes:
    payload = record.model_dump(mode="json")
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_JSONL_LINE_BYTES:
        raise ValueError("canonical JSONL record exceeds the line-size limit")
    return encoded


def append_jsonl_record(
    path: Path,
    *,
    record: RecordT,
    model: type[RecordT],
    id_field: str,
) -> None:
    if not path.parent.is_dir():
        raise ValueError(f"JSONL evidence parent directory does not exist: {path.parent}")
    if path.exists() and path.is_symlink():
        raise ValueError("JSONL evidence destination cannot be a symlink")

    lock_path = path.with_name(f".{path.name}.lock")
    lock_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    lock_fd = os.open(lock_path, lock_flags, 0o600)
    try:
        existing = load_jsonl_records(path, model)
        seen_ids: set[str] = set()
        for existing_record in existing:
            record_id = getattr(existing_record, id_field, None)
            if not isinstance(record_id, str):
                raise ValueError(f"record model has no string field {id_field}")
            if record_id in seen_ids:
                raise ValueError(f"duplicate {id_field}: {record_id}")
            seen_ids.add(record_id)

        new_id = getattr(record, id_field, None)
        if not isinstance(new_id, str):
            raise ValueError(f"record model has no string field {id_field}")
        if new_id in seen_ids:
            raise ValueError(f"duplicate {id_field}: {new_id}")

        validated = model.model_validate(record.model_dump(mode="json"))
        encoded = _canonical_json_line(validated)
        append_flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            append_flags |= os.O_BINARY
        destination_fd = os.open(path, append_flags, 0o600)
        try:
            written = os.write(destination_fd, encoded)
            if written != len(encoded):
                raise OSError("incomplete JSONL append")
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def resolve_bounded_file(root: Path, relative_path: str) -> Path:
    normalized = validate_repository_relative_path(relative_path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence root must be a regular directory")
    root_resolved = root.resolve(strict=True)
    candidate = root_resolved
    for part in PurePosixPath(normalized).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"evidence artifact path contains a symlink: {normalized}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"evidence artifact must exist below its root: {normalized}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"evidence artifact must be a regular file: {normalized}")
    size = resolved.stat().st_size
    if size > MAX_EVIDENCE_ARTIFACT_BYTES:
        raise ValueError(
            f"evidence artifact exceeds {MAX_EVIDENCE_ARTIFACT_BYTES} bytes: "
            f"{normalized}"
        )
    return resolved


def _record_count(relative_path: str, content: bytes) -> int:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"accepted evidence must be UTF-8: {relative_path}") from exc
    lines = text.splitlines()
    if relative_path.endswith(".jsonl"):
        if any(not line.strip() for line in lines):
            raise ValueError(f"accepted JSONL cannot contain blank lines: {relative_path}")
        return len(lines)
    return sum(1 for line in lines if line.startswith("## "))


def create_prefix_anchor(
    root: Path,
    relative_path: str,
    *,
    accepted_at_gate: str,
) -> EvidencePrefixAnchor:
    path = resolve_bounded_file(root, relative_path)
    content = path.read_bytes()
    return EvidencePrefixAnchor(
        path=relative_path,
        accepted_bytes=len(content),
        record_count=_record_count(relative_path, content),
        prefix_sha256=sha256_bytes(content),
        accepted_at_gate=accepted_at_gate,
    )


def validate_prefix_anchor(root: Path, anchor: EvidencePrefixAnchor) -> None:
    path = resolve_bounded_file(root, anchor.path)
    if path.stat().st_size < anchor.accepted_bytes:
        raise ValueError(f"{anchor.path} is shorter than accepted prefix")
    with path.open("rb") as stream:
        prefix = stream.read(anchor.accepted_bytes)
    if len(prefix) != anchor.accepted_bytes:
        raise ValueError(f"{anchor.path} is shorter than accepted prefix")
    if sha256_bytes(prefix) != anchor.prefix_sha256:
        raise ValueError(f"accepted prefix hash mismatch: {anchor.path}")
    if _record_count(anchor.path, prefix) != anchor.record_count:
        raise ValueError(f"accepted prefix record count mismatch: {anchor.path}")


def hash_evidence_artifacts(
    root: Path,
    relative_paths: list[str],
) -> list[EvidenceArtifactHash]:
    normalized_paths = [
        validate_repository_relative_path(value) for value in relative_paths
    ]
    if len(normalized_paths) != len(set(normalized_paths)):
        raise ValueError("duplicate evidence artifact path")

    manifest: list[EvidenceArtifactHash] = []
    for relative_path in sorted(normalized_paths):
        path = resolve_bounded_file(root, relative_path)
        content = path.read_bytes()
        manifest.append(
            EvidenceArtifactHash(
                path=relative_path,
                byte_count=len(content),
                sha256=sha256_bytes(content),
            )
        )
    return manifest


__all__ = [
    "EXPERIMENT_PREREGISTRATION_FIELDS",
    "EvidenceArtifactHash",
    "EvidencePrefixAnchor",
    "ExperimentFinalStatus",
    "ExperimentRecord",
    "ExperimentStatus",
    "FailureRecord",
    "ResearchRequestRecord",
    "StrictEvidenceModel",
    "append_jsonl_record",
    "create_prefix_anchor",
    "hash_evidence_artifacts",
    "load_jsonl_records",
    "resolve_bounded_file",
    "sha256_bytes",
    "validate_experiment_history",
    "validate_prefix_anchor",
    "validate_repository_relative_path",
]
