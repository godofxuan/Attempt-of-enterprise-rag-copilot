from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REQUIRED_ATTACK_FAMILIES = (
    "semantic_paraphrase",
    "cross_chunk_composition",
    "encoded_unicode",
    "tool_inducement",
    "long_context",
    "metadata_surface",
    "open_surface",
    "find_surface",
)
REQUIRED_SOURCE_SURFACES = ("body", "metadata", "parent", "open", "find")
REQUIRED_RUBRIC_DIMENSIONS = (
    "semantic_instruction_following",
    "sensitive_information_disclosure",
    "unauthorized_action_attempt",
    "legitimate_task_completion",
)
RUBRIC_LABELS = ("pass", "fail", "uncertain", "not_applicable")

AttackFamily = Literal[
    "semantic_paraphrase",
    "cross_chunk_composition",
    "encoded_unicode",
    "tool_inducement",
    "long_context",
    "metadata_surface",
    "open_surface",
    "find_surface",
    "benign_hard_negative",
]
SourceSurface = Literal["body", "metadata", "parent", "open", "find"]
HoldoutLabel = Literal["attack", "benign"]

_DRAFT_FILE_NAMES = frozenset(
    {"case_catalog.json", "payload.json", "rubric.json"}
)
_FROZEN_FILE_NAMES = _DRAFT_FILE_NAMES | {"freeze_manifest.json"}
HOLDOUT_BASELINE_PATHS = (
    "app/security/retrieved_content.py",
    "app/evaluation/indirect_injection_live_runner.py",
    "app/evaluation/indirect_injection_holdout.py",
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=False,
    )


class HoldoutCaseCatalogEntry(_StrictFrozenModel):
    case_id: str = Field(pattern=r"^r2s2-holdout-[a-z0-9][a-z0-9-]{2,120}$")
    label: HoldoutLabel
    families: tuple[AttackFamily, ...] = Field(min_length=1)
    source_surfaces: tuple[SourceSurface, ...] = Field(min_length=1)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    payload_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,120}$")

    @model_validator(mode="after")
    def validate_case_metadata(self) -> HoldoutCaseCatalogEntry:
        if len(self.families) != len(set(self.families)):
            raise ValueError("holdout case families must be unique")
        if len(self.source_surfaces) != len(set(self.source_surfaces)):
            raise ValueError("holdout source surfaces must be unique")
        benign_family = "benign_hard_negative"
        if self.label == "benign" and self.families != (benign_family,):
            raise ValueError("benign holdout cases require only benign_hard_negative")
        if self.label == "attack" and benign_family in self.families:
            raise ValueError("attack holdout cases cannot use benign_hard_negative")
        return self


class HoldoutCaseCatalog(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_holdout_catalog_v1"]
    holdout_id: str = Field(pattern=r"^r2-s2-holdout-[a-z0-9][a-z0-9-]{2,120}$")
    cases: tuple[HoldoutCaseCatalogEntry, ...] = Field(min_length=36)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> HoldoutCaseCatalog:
        case_ids = tuple(case.case_id for case in self.cases)
        payload_keys = tuple(case.payload_key for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("holdout case IDs must be unique")
        if len(payload_keys) != len(set(payload_keys)):
            raise ValueError("holdout payload keys must be unique")
        return self


class HoldoutPayloadEntry(_StrictFrozenModel):
    case_id: str = Field(pattern=r"^r2s2-holdout-[a-z0-9][a-z0-9-]{2,120}$")
    payload_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,120}$")
    payload: dict[str, Any] = Field(min_length=1)


class HoldoutPayloadEnvelope(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_holdout_payload_v1"]
    holdout_id: str = Field(pattern=r"^r2-s2-holdout-[a-z0-9][a-z0-9-]{2,120}$")
    cases: tuple[HoldoutPayloadEntry, ...] = Field(min_length=36)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> HoldoutPayloadEnvelope:
        identities = tuple((case.case_id, case.payload_key) for case in self.cases)
        if len(identities) != len(set(identities)):
            raise ValueError("holdout payload identities must be unique")
        return self


class HoldoutRubricDimension(_StrictFrozenModel):
    name: Literal[
        "semantic_instruction_following",
        "sensitive_information_disclosure",
        "unauthorized_action_attempt",
        "legitimate_task_completion",
    ]
    labels: tuple[
        Literal["pass", "fail", "uncertain", "not_applicable"], ...
    ]
    decision_guidance: str = Field(min_length=40, max_length=2_000)

    @model_validator(mode="after")
    def validate_labels(self) -> HoldoutRubricDimension:
        if self.labels != RUBRIC_LABELS:
            raise ValueError("holdout rubric labels must use the frozen order")
        return self


class HoldoutRubric(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_holdout_rubric_v1"]
    holdout_id: str = Field(pattern=r"^r2-s2-holdout-[a-z0-9][a-z0-9-]{2,120}$")
    primary_reviewer_id: str = Field(pattern=r"^reviewer-[a-z0-9][a-z0-9-]{2,80}$")
    secondary_reviewer_id: str = Field(pattern=r"^reviewer-[a-z0-9][a-z0-9-]{2,80}$")
    dimensions: tuple[HoldoutRubricDimension, ...]

    @model_validator(mode="after")
    def validate_review_protocol(self) -> HoldoutRubric:
        if self.primary_reviewer_id == self.secondary_reviewer_id:
            raise ValueError("holdout reviewers must be distinct")
        if tuple(item.name for item in self.dimensions) != (
            REQUIRED_RUBRIC_DIMENSIONS
        ):
            raise ValueError("holdout rubric dimensions must use the frozen order")
        return self


class HoldoutCoverageSummary(_StrictFrozenModel):
    case_count: int = Field(ge=36)
    attack_case_count: int = Field(ge=24)
    benign_case_count: int = Field(ge=12)
    attack_family_counts: dict[str, int]
    source_surface_counts: dict[str, int]
    language_counts: dict[str, int]
    case_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HoldoutFileEvidence(_StrictFrozenModel):
    path: Literal["case_catalog.json", "payload.json", "rubric.json"]
    bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HoldoutCodeArtifactEvidence(_StrictFrozenModel):
    path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HoldoutCodeBaseline(_StrictFrozenModel):
    git_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    branch: str = Field(min_length=1, max_length=200)
    tracked_worktree_clean: Literal[True]
    artifacts: dict[str, HoldoutCodeArtifactEvidence]

    @model_validator(mode="after")
    def validate_artifacts(self) -> HoldoutCodeBaseline:
        if set(self.artifacts) != set(HOLDOUT_BASELINE_PATHS):
            raise ValueError("holdout code baseline artifact set is incomplete")
        if any(key != value.path for key, value in self.artifacts.items()):
            raise ValueError("holdout code baseline artifact paths contradict keys")
        return self


class HoldoutSeparationAttestation(_StrictFrozenModel):
    author_is_independent_of_guard_implementation: Literal[True]
    raw_payload_not_shared_before_freeze: Literal[True]
    labels_not_changed_after_model_observation: Literal[True]
    single_evaluation_per_code_baseline: Literal[True]


class HoldoutFreezeManifest(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_holdout_freeze_manifest_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    submission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,120}$")
    holdout_id: str = Field(pattern=r"^r2-s2-holdout-[a-z0-9][a-z0-9-]{2,120}$")
    state: Literal["FROZEN"]
    frozen_at_utc: datetime
    primary_reviewer_id: str = Field(pattern=r"^reviewer-[a-z0-9][a-z0-9-]{2,80}$")
    secondary_reviewer_id: str = Field(pattern=r"^reviewer-[a-z0-9][a-z0-9-]{2,80}$")
    files: dict[str, HoldoutFileEvidence]
    coverage: HoldoutCoverageSummary
    code_baseline: HoldoutCodeBaseline
    separation_attestation: HoldoutSeparationAttestation

    @field_validator("frozen_at_utc")
    @classmethod
    def validate_frozen_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("holdout freeze time must be UTC")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> HoldoutFreezeManifest:
        if set(self.files) != _DRAFT_FILE_NAMES:
            raise ValueError("holdout freeze manifest input file set is incomplete")
        if any(key != value.path for key, value in self.files.items()):
            raise ValueError("holdout freeze input paths contradict keys")
        if self.primary_reviewer_id == self.secondary_reviewer_id:
            raise ValueError("holdout freeze reviewers must be distinct")
        return self


@dataclass(frozen=True)
class HoldoutInputs:
    submission_dir: Path
    catalog: HoldoutCaseCatalog
    payload: HoldoutPayloadEnvelope
    rubric: HoldoutRubric
    coverage: HoldoutCoverageSummary


def load_holdout_inputs(submission_dir: Path) -> HoldoutInputs:
    return _load_holdout_inputs(submission_dir, frozen=False)


def _load_holdout_inputs(
    submission_dir: Path,
    *,
    frozen: bool,
) -> HoldoutInputs:
    submission_dir = Path(submission_dir).resolve()
    if not submission_dir.is_dir():
        raise FileNotFoundError(f"holdout submission directory not found: {submission_dir}")
    file_names = frozenset(
        path.name for path in submission_dir.iterdir() if path.is_file()
    )
    expected_names = _FROZEN_FILE_NAMES if frozen else _DRAFT_FILE_NAMES
    if file_names != expected_names:
        expected_count = "four frozen files" if frozen else "exactly three input files"
        raise ValueError(f"holdout package must contain {expected_count}")

    catalog = HoldoutCaseCatalog.model_validate_json(
        (submission_dir / "case_catalog.json").read_bytes()
    )
    payload = HoldoutPayloadEnvelope.model_validate_json(
        (submission_dir / "payload.json").read_bytes()
    )
    rubric = HoldoutRubric.model_validate_json(
        (submission_dir / "rubric.json").read_bytes()
    )
    if len({catalog.holdout_id, payload.holdout_id, rubric.holdout_id}) != 1:
        raise ValueError("holdout input IDs must match")
    catalog_identities = tuple(
        sorted((case.case_id, case.payload_key) for case in catalog.cases)
    )
    payload_identities = tuple(
        sorted((case.case_id, case.payload_key) for case in payload.cases)
    )
    if catalog_identities != payload_identities:
        raise ValueError("holdout catalog and payload identities must match exactly")

    coverage = _coverage(catalog, catalog_identities)
    return HoldoutInputs(
        submission_dir=submission_dir,
        catalog=catalog,
        payload=payload,
        rubric=rubric,
        coverage=coverage,
    )


def freeze_holdout_submission(
    submission_dir: Path,
    *,
    baseline: HoldoutCodeBaseline,
    attestation: HoldoutSeparationAttestation,
    frozen_at_utc: datetime,
) -> Path:
    submission_dir = Path(submission_dir).resolve()
    manifest_path = submission_dir / "freeze_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"holdout submission is already frozen: {manifest_path}")
    inputs = load_holdout_inputs(submission_dir)
    manifest = _build_freeze_manifest(
        inputs,
        baseline=baseline,
        attestation=attestation,
        frozen_at_utc=frozen_at_utc,
    )
    payload = _json_bytes(manifest.model_dump(mode="json"))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".freeze_manifest.",
        suffix=".tmp",
        dir=submission_dir,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        temporary.replace(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    verify_holdout_submission(submission_dir, baseline=baseline)
    return manifest_path


def verify_holdout_submission(
    submission_dir: Path,
    *,
    baseline: HoldoutCodeBaseline,
) -> HoldoutFreezeManifest:
    submission_dir = Path(submission_dir).resolve()
    manifest_path = submission_dir / "freeze_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"holdout freeze manifest not found: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = HoldoutFreezeManifest.model_validate_json(manifest_bytes)
    if manifest_bytes != _json_bytes(manifest.model_dump(mode="json")):
        raise ValueError("holdout freeze manifest is not canonical JSON")
    if submission_dir.name != manifest.submission_id:
        raise ValueError("holdout submission directory contradicts manifest")
    if baseline != manifest.code_baseline:
        raise ValueError("holdout code baseline does not match frozen manifest")
    inputs = _load_holdout_inputs(submission_dir, frozen=True)
    expected = _build_freeze_manifest(
        inputs,
        baseline=baseline,
        attestation=manifest.separation_attestation,
        frozen_at_utc=manifest.frozen_at_utc,
    )
    if expected != manifest:
        raise ValueError("holdout freeze manifest contradicts current package bytes")
    return manifest


def current_holdout_code_baseline(repo_root: Path) -> HoldoutCodeBaseline:
    repo_root = Path(repo_root).resolve()
    git_head = _git(repo_root, "rev-parse", "HEAD")
    branch = _git(repo_root, "branch", "--show-current")
    tracked_status = _git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    if tracked_status:
        raise ValueError("holdout freeze requires a clean tracked worktree")
    artifacts: dict[str, HoldoutCodeArtifactEvidence] = {}
    for relative in HOLDOUT_BASELINE_PATHS:
        path = repo_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"holdout baseline artifact not found: {relative}")
        artifacts[relative] = HoldoutCodeArtifactEvidence(
            path=relative,
            sha256=_sha256_file(path),
        )
    return HoldoutCodeBaseline(
        git_head=git_head,
        branch=branch,
        tracked_worktree_clean=True,
        artifacts=artifacts,
    )


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _build_freeze_manifest(
    inputs: HoldoutInputs,
    *,
    baseline: HoldoutCodeBaseline,
    attestation: HoldoutSeparationAttestation,
    frozen_at_utc: datetime,
) -> HoldoutFreezeManifest:
    return HoldoutFreezeManifest(
        schema_version="indirect_injection_holdout_freeze_manifest_v1",
        producer="enterprise_agentic_rag_v2",
        submission_id=inputs.submission_dir.name,
        holdout_id=inputs.catalog.holdout_id,
        state="FROZEN",
        frozen_at_utc=frozen_at_utc,
        primary_reviewer_id=inputs.rubric.primary_reviewer_id,
        secondary_reviewer_id=inputs.rubric.secondary_reviewer_id,
        files={
            name: HoldoutFileEvidence(
                path=name,
                bytes=(inputs.submission_dir / name).stat().st_size,
                sha256=_sha256_file(inputs.submission_dir / name),
            )
            for name in sorted(_DRAFT_FILE_NAMES)
        },
        coverage=inputs.coverage,
        code_baseline=baseline,
        separation_attestation=attestation,
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _coverage(
    catalog: HoldoutCaseCatalog,
    identities: tuple[tuple[str, str], ...],
) -> HoldoutCoverageSummary:
    attack = tuple(case for case in catalog.cases if case.label == "attack")
    benign = tuple(case for case in catalog.cases if case.label == "benign")
    if len(attack) < 24 or len(benign) < 12:
        raise ValueError("holdout requires at least 24 attack and 12 benign cases")
    family_counts = {
        family: sum(family in case.families for case in attack)
        for family in REQUIRED_ATTACK_FAMILIES
    }
    if any(count < 2 for count in family_counts.values()):
        raise ValueError("every required holdout attack family needs two cases")
    surface_counts = {
        surface: sum(surface in case.source_surfaces for case in catalog.cases)
        for surface in REQUIRED_SOURCE_SURFACES
    }
    if any(count < 2 for count in surface_counts.values()):
        raise ValueError("every required holdout source surface needs two cases")
    language_counts = {
        language: sum(case.language == language for case in catalog.cases)
        for language in sorted({case.language for case in catalog.cases})
    }
    if language_counts.get("en", 0) < 1 or language_counts.get("zh", 0) < 1:
        raise ValueError("holdout requires both English and Chinese cases")
    identity_payload = "\n".join(
        f"{case_id}\0{payload_key}" for case_id, payload_key in identities
    ).encode("utf-8")
    return HoldoutCoverageSummary(
        case_count=len(catalog.cases),
        attack_case_count=len(attack),
        benign_case_count=len(benign),
        attack_family_counts=family_counts,
        source_surface_counts=surface_counts,
        language_counts=language_counts,
        case_identity_sha256=hashlib.sha256(identity_payload).hexdigest(),
    )


__all__ = [
    "HoldoutCaseCatalog",
    "HoldoutCoverageSummary",
    "HoldoutCodeBaseline",
    "HoldoutFreezeManifest",
    "HoldoutInputs",
    "HoldoutPayloadEnvelope",
    "HoldoutRubric",
    "HoldoutSeparationAttestation",
    "HOLDOUT_BASELINE_PATHS",
    "REQUIRED_ATTACK_FAMILIES",
    "REQUIRED_RUBRIC_DIMENSIONS",
    "REQUIRED_SOURCE_SURFACES",
    "freeze_holdout_submission",
    "current_holdout_code_baseline",
    "load_holdout_inputs",
    "verify_holdout_submission",
]
