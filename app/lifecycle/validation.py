from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.lifecycle.evidence import (
    EXPERIMENT_ID_PATTERN,
    FAILURE_ID_PATTERN,
    RESEARCH_REQUEST_ID_PATTERN,
    REQUIREMENT_ID_PATTERN,
    EvidenceArtifactHash,
    EvidencePrefixAnchor,
    ExperimentRecord,
    FailureRecord,
    ResearchRequestRecord,
    StrictEvidenceModel,
    hash_evidence_artifacts,
    load_jsonl_records,
    resolve_bounded_file,
    validate_experiment_history,
    validate_prefix_anchor,
    validate_repository_relative_path,
)


LIFECYCLE_DIRECTORY = "docs/lifecycle"
REQUIRED_LIFECYCLE_FILES = (
    "00_STAGE_CONTRACT.md",
    "01_ENGINEERING_JOURNAL.md",
    "02_DECISIONS.md",
    "03_RESULTS.md",
    "04_LEARNING_GUIDE.md",
    "TRACEABILITY.csv",
    "EXPERIMENTS.jsonl",
    "FAILURES.jsonl",
    "RESEARCH_REQUESTS.jsonl",
    "CODEX_HANDOFF.json",
)
APPEND_ONLY_PATHS = frozenset(
    {
        "docs/lifecycle/01_ENGINEERING_JOURNAL.md",
        "docs/lifecycle/02_DECISIONS.md",
        "docs/lifecycle/03_RESULTS.md",
        "docs/lifecycle/EXPERIMENTS.jsonl",
        "docs/lifecycle/FAILURES.jsonl",
        "docs/lifecycle/RESEARCH_REQUESTS.jsonl",
    }
)
TRACEABILITY_FIELDS = (
    "requirement_id",
    "description",
    "design_id",
    "implementation_paths",
    "test_ids",
    "experiment_ids",
    "evidence_ids",
    "status",
    "notes",
)
GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"


def _split_references(value: str) -> list[str]:
    if not value:
        return []
    references = [item.strip() for item in value.split(";")]
    if any(not item for item in references):
        raise ValueError("semicolon-delimited references cannot contain empty values")
    if len(references) != len(set(references)):
        raise ValueError("semicolon-delimited references must be unique")
    return references


def _validate_reference_list(
    value: str,
    *,
    pattern: str,
    field_name: str,
) -> str:
    for reference in _split_references(value):
        if re.fullmatch(pattern, reference) is None:
            raise ValueError(f"{field_name} contains invalid identifier {reference}")
    return value


class TraceabilityRow(StrictEvidenceModel):
    requirement_id: str = Field(pattern=REQUIREMENT_ID_PATTERN)
    description: str = Field(min_length=1, max_length=1000)
    design_id: str = Field(default="", max_length=1000)
    implementation_paths: str = Field(default="", max_length=4000)
    test_ids: str = Field(default="", max_length=4000)
    experiment_ids: str = Field(default="", max_length=4000)
    evidence_ids: str = Field(default="", max_length=4000)
    status: str = Field(pattern=r"^[A-Z0-9_]+$", max_length=100)
    notes: str = Field(default="", max_length=4000)

    @field_validator("design_id")
    @classmethod
    def validate_design_ids(cls, value: str) -> str:
        return _validate_reference_list(
            value,
            pattern=r"ADR-LC-[0-9]{3,}",
            field_name="design_id",
        )

    @field_validator("implementation_paths")
    @classmethod
    def validate_implementation_paths(cls, value: str) -> str:
        for path in _split_references(value):
            validate_repository_relative_path(path)
        return value

    @field_validator("test_ids")
    @classmethod
    def validate_test_ids(cls, value: str) -> str:
        return _validate_reference_list(
            value,
            pattern=r"T-LC-[0-9]{3,}",
            field_name="test_ids",
        )

    @field_validator("experiment_ids")
    @classmethod
    def validate_experiment_ids(cls, value: str) -> str:
        return _validate_reference_list(
            value,
            pattern=r"EXP-LC-[0-9]{3,}",
            field_name="experiment_ids",
        )

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: str) -> str:
        return _validate_reference_list(
            value,
            pattern=r"EVID-LC-[0-9]{3,}",
            field_name="evidence_ids",
        )

    @property
    def design_ids(self) -> list[str]:
        return _split_references(self.design_id)

    @property
    def implementation_path_list(self) -> list[str]:
        return _split_references(self.implementation_paths)

    @property
    def test_id_list(self) -> list[str]:
        return _split_references(self.test_ids)

    @property
    def experiment_id_list(self) -> list[str]:
        return _split_references(self.experiment_ids)

    @property
    def evidence_id_list(self) -> list[str]:
        return _split_references(self.evidence_ids)


class CommandRunEvidence(StrictEvidenceModel):
    command_id: str = Field(pattern=r"^CMD-LC-G[0-9]+-[0-9]{3,}$")
    kind: Literal["pytest", "benchmark", "validation", "audit"]
    artifact_path: str
    scope: str = Field(min_length=1, max_length=1000)
    exit_code: int
    duration_seconds: float = Field(ge=0.0)
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    warnings: int | None = Field(default=None, ge=0)
    pytest_duration_seconds: float | None = Field(default=None, ge=0.0)
    embedding_backend: str | None = Field(default=None, max_length=200)
    profile: str | None = Field(default=None, max_length=200)
    repetitions: int | None = Field(default=None, ge=1)
    summary_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    candidate_files: int | None = Field(default=None, ge=0)
    findings: int | None = Field(default=None, ge=0)

    @field_validator("artifact_path")
    @classmethod
    def validate_artifact_path(cls, value: str) -> str:
        return validate_repository_relative_path(value)

    @model_validator(mode="after")
    def validate_kind_fields(self) -> CommandRunEvidence:
        if self.kind == "pytest" and (self.passed is None or self.failed is None):
            raise ValueError("pytest command evidence requires passed and failed counts")
        if self.kind == "benchmark" and (
            self.embedding_backend is None
            or self.profile is None
            or self.repetitions is None
            or self.summary_sha256 is None
        ):
            raise ValueError("benchmark evidence is missing benchmark provenance")
        if self.kind == "audit" and (
            self.candidate_files is None or self.findings is None
        ):
            raise ValueError("audit command evidence requires candidate counts")
        return self


class LifecycleHandoff(StrictEvidenceModel):
    schema_version: Literal[1]
    baseline_sha: str = Field(pattern=GIT_SHA_PATTERN)
    current_sha: str = Field(pattern=GIT_SHA_PATTERN)
    dirty: bool
    current_gate: str = Field(pattern=r"^G[0-9]+[A-Z0-9_]*$", max_length=100)
    completed_gates: list[str] = Field(max_length=100)
    completed_requirements: list[str] = Field(max_length=100)
    accepted_decisions: list[str] = Field(max_length=100)
    open_failures: list[str] = Field(max_length=1000)
    blocking_research_requests: list[str] = Field(max_length=1000)
    last_test_runs: list[CommandRunEvidence] = Field(max_length=100)
    append_only_anchors: list[EvidencePrefixAnchor] = Field(min_length=1)
    evidence_artifacts: list[EvidenceArtifactHash] = Field(min_length=1)
    next_actions: list[str] = Field(min_length=1, max_length=100)
    files_to_read_next: list[str] = Field(min_length=1, max_length=100)

    @field_validator("completed_gates")
    @classmethod
    def validate_completed_gates(cls, values: list[str]) -> list[str]:
        for value in values:
            if re.fullmatch(r"G[0-9]+", value) is None:
                raise ValueError(f"invalid completed Gate identifier {value}")
        return _unique(values, "completed_gates")

    @field_validator("completed_requirements")
    @classmethod
    def validate_completed_requirements(cls, values: list[str]) -> list[str]:
        for value in values:
            if re.fullmatch(REQUIREMENT_ID_PATTERN, value) is None:
                raise ValueError(f"invalid completed requirement {value}")
        return _unique(values, "completed_requirements")

    @field_validator("accepted_decisions")
    @classmethod
    def validate_accepted_decisions(cls, values: list[str]) -> list[str]:
        for value in values:
            if re.fullmatch(r"ADR-LC-[0-9]{3,}", value) is None:
                raise ValueError(f"invalid accepted decision {value}")
        return _unique(values, "accepted_decisions")

    @field_validator("open_failures")
    @classmethod
    def validate_open_failures(cls, values: list[str]) -> list[str]:
        for value in values:
            if re.fullmatch(FAILURE_ID_PATTERN, value) is None:
                raise ValueError(f"invalid open failure {value}")
        return _unique(values, "open_failures")

    @field_validator("blocking_research_requests")
    @classmethod
    def validate_blocking_requests(cls, values: list[str]) -> list[str]:
        for value in values:
            if re.fullmatch(RESEARCH_REQUEST_ID_PATTERN, value) is None:
                raise ValueError(f"invalid blocking research request {value}")
        return _unique(values, "blocking_research_requests")

    @field_validator("files_to_read_next")
    @classmethod
    def validate_read_paths(cls, values: list[str]) -> list[str]:
        return _unique(
            [validate_repository_relative_path(value) for value in values],
            "files_to_read_next",
        )

    @model_validator(mode="after")
    def validate_unique_structured_paths(self) -> LifecycleHandoff:
        anchor_paths = [item.path for item in self.append_only_anchors]
        _unique(anchor_paths, "append_only_anchors")
        artifact_paths = [item.path for item in self.evidence_artifacts]
        _unique(artifact_paths, "evidence_artifacts")
        command_ids = [item.command_id for item in self.last_test_runs]
        _unique(command_ids, "last_test_runs")
        return self


def _unique(values: list[str], field_name: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be unique")
    return values


class LifecycleValidationReport(StrictEvidenceModel):
    schema_version: Literal["lifecycle_evidence_validation_v1"] = (
        "lifecycle_evidence_validation_v1"
    )
    required_files: int = Field(ge=0)
    experiments: int = Field(ge=0)
    failures: int = Field(ge=0)
    research_requests: int = Field(ge=0)
    traceability_rows: int = Field(ge=0)
    append_only_anchors: int = Field(ge=0)
    evidence_artifacts: int = Field(ge=0)
    public_audit_candidates: int = Field(ge=0)
    public_audit_findings: int = Field(ge=0)


def load_traceability(path: Path) -> list[TraceabilityRow]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("TRACEABILITY.csv must be a regular file")
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TRACEABILITY_FIELDS:
            raise ValueError("TRACEABILITY.csv header does not match the frozen schema")
        rows = [TraceabilityRow.model_validate(row) for row in reader]
    requirement_ids = [row.requirement_id for row in rows]
    _unique(requirement_ids, "traceability requirement_id")
    return rows


def _load_handoff(path: Path) -> LifecycleHandoff:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CODEX_HANDOFF.json must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("CODEX_HANDOFF.json is not valid JSON") from exc
    return LifecycleHandoff.model_validate(payload)


def _extract_ids(path: Path, pattern: str) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(pattern, text))


def _require_subset(
    observed: set[str],
    known: set[str],
    *,
    label: str,
) -> None:
    missing = sorted(observed - known)
    if missing:
        raise ValueError(f"{label} references unknown identifier {missing[0]}")


def _validate_traceability_references(
    root: Path,
    rows: list[TraceabilityRow],
    *,
    requirement_ids: set[str],
    decision_ids: set[str],
    test_ids: set[str],
    experiment_ids: set[str],
    evidence_ids: set[str],
) -> None:
    for row in rows:
        if row.requirement_id not in requirement_ids:
            raise ValueError(
                f"traceability references unknown requirement {row.requirement_id}"
            )
        for decision_id in row.design_ids:
            if decision_id not in decision_ids:
                raise ValueError(f"traceability references unknown decision {decision_id}")
        for test_id in row.test_id_list:
            if test_id not in test_ids:
                raise ValueError(f"traceability references unknown test {test_id}")
        for experiment_id in row.experiment_id_list:
            if experiment_id not in experiment_ids:
                raise ValueError(
                    f"traceability references unknown experiment {experiment_id}"
                )
        for evidence_id in row.evidence_id_list:
            if evidence_id not in evidence_ids:
                raise ValueError(
                    f"traceability references unknown evidence {evidence_id}"
                )
        for implementation_path in row.implementation_path_list:
            try:
                resolve_bounded_file(root, implementation_path)
            except ValueError as exc:
                raise ValueError(
                    f"traceability implementation path is unsafe or missing: "
                    f"{implementation_path}"
                ) from exc


def validate_lifecycle_repository(
    root: Path,
    *,
    run_public_audit: bool = True,
) -> LifecycleValidationReport:
    root = root.resolve(strict=True)
    lifecycle = root / LIFECYCLE_DIRECTORY
    if lifecycle.is_symlink() or not lifecycle.is_dir():
        raise ValueError("docs/lifecycle must be a regular directory")
    for filename in REQUIRED_LIFECYCLE_FILES:
        path = lifecycle / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"required lifecycle evidence file is missing: {filename}")

    experiments = load_jsonl_records(
        lifecycle / "EXPERIMENTS.jsonl",
        ExperimentRecord,
    )
    failures = load_jsonl_records(
        lifecycle / "FAILURES.jsonl",
        FailureRecord,
    )
    research_requests = load_jsonl_records(
        lifecycle / "RESEARCH_REQUESTS.jsonl",
        ResearchRequestRecord,
    )
    validate_experiment_history(experiments)
    _unique([record.failure_id for record in failures], "failure_id")
    _unique([record.request_id for record in research_requests], "request_id")

    traceability = load_traceability(lifecycle / "TRACEABILITY.csv")
    handoff = _load_handoff(lifecycle / "CODEX_HANDOFF.json")
    requirement_ids = _extract_ids(
        lifecycle / "00_STAGE_CONTRACT.md",
        r"REQ-LC-[0-9]{3,}",
    )
    decision_ids = _extract_ids(
        lifecycle / "02_DECISIONS.md",
        r"ADR-LC-[0-9]{3,}",
    )
    test_ids = _extract_ids(
        lifecycle / "00_STAGE_CONTRACT.md",
        r"T-LC-[0-9]{3,}",
    )
    evidence_ids = _extract_ids(
        lifecycle / "01_ENGINEERING_JOURNAL.md",
        r"EVID-LC-[0-9]{3,}",
    )
    experiment_ids = {record.experiment_id for record in experiments}
    _validate_traceability_references(
        root,
        traceability,
        requirement_ids=requirement_ids,
        decision_ids=decision_ids,
        test_ids=test_ids,
        experiment_ids=experiment_ids,
        evidence_ids=evidence_ids,
    )

    for record in failures:
        _require_subset(
            set(record.related_requirements),
            requirement_ids,
            label=record.failure_id,
        )
    for record in research_requests:
        _require_subset(
            set(record.affected_requirements),
            requirement_ids,
            label=record.request_id,
        )
    _require_subset(
        set(handoff.completed_requirements),
        requirement_ids,
        label="completed_requirements",
    )
    _require_subset(
        set(handoff.accepted_decisions),
        decision_ids,
        label="accepted_decisions",
    )

    expected_open_failures = {
        record.failure_id for record in failures if record.status == "OPEN"
    }
    if set(handoff.open_failures) != expected_open_failures:
        raise ValueError("handoff open_failures does not match failure records")
    expected_blocking_requests = {
        record.request_id for record in research_requests if record.blocking
    }
    if set(handoff.blocking_research_requests) != expected_blocking_requests:
        raise ValueError(
            "handoff blocking_research_requests does not match research records"
        )

    anchor_paths = {anchor.path for anchor in handoff.append_only_anchors}
    if anchor_paths != APPEND_ONLY_PATHS:
        raise ValueError("handoff append_only_anchors does not cover the frozen set")
    for anchor in handoff.append_only_anchors:
        validate_prefix_anchor(root, anchor)

    observed_hashes = hash_evidence_artifacts(
        root,
        [item.path for item in handoff.evidence_artifacts],
    )
    if observed_hashes != sorted(
        handoff.evidence_artifacts,
        key=lambda item: item.path,
    ):
        raise ValueError("handoff evidence_artifacts hashes do not match repository")

    candidate_count = 0
    finding_count = 0
    if run_public_audit:
        from scripts.audit_public_repo import audit_repository

        public_report = audit_repository(root)
        candidate_count = len(public_report.candidate_files)
        finding_count = len(public_report.findings)
        if finding_count:
            codes = ",".join(sorted({item.code for item in public_report.findings}))
            raise ValueError(
                f"public evidence audit failed with {finding_count} findings "
                f"of types {codes}"
            )

    return LifecycleValidationReport(
        required_files=len(REQUIRED_LIFECYCLE_FILES),
        experiments=len(experiments),
        failures=len(failures),
        research_requests=len(research_requests),
        traceability_rows=len(traceability),
        append_only_anchors=len(handoff.append_only_anchors),
        evidence_artifacts=len(handoff.evidence_artifacts),
        public_audit_candidates=candidate_count,
        public_audit_findings=finding_count,
    )


__all__ = [
    "APPEND_ONLY_PATHS",
    "CommandRunEvidence",
    "LIFECYCLE_DIRECTORY",
    "LifecycleHandoff",
    "LifecycleValidationReport",
    "REQUIRED_LIFECYCLE_FILES",
    "TRACEABILITY_FIELDS",
    "TraceabilityRow",
    "load_traceability",
    "validate_lifecycle_repository",
]
