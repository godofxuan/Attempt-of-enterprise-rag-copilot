from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


@dataclass(frozen=True)
class HoldoutInputs:
    submission_dir: Path
    catalog: HoldoutCaseCatalog
    payload: HoldoutPayloadEnvelope
    rubric: HoldoutRubric
    coverage: HoldoutCoverageSummary


def load_holdout_inputs(submission_dir: Path) -> HoldoutInputs:
    submission_dir = Path(submission_dir).resolve()
    if not submission_dir.is_dir():
        raise FileNotFoundError(f"holdout submission directory not found: {submission_dir}")
    file_names = frozenset(
        path.name for path in submission_dir.iterdir() if path.is_file()
    )
    if file_names != _DRAFT_FILE_NAMES:
        raise ValueError("draft holdout package must contain exactly three input files")

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
    "HoldoutInputs",
    "HoldoutPayloadEnvelope",
    "HoldoutRubric",
    "REQUIRED_ATTACK_FAMILIES",
    "REQUIRED_RUBRIC_DIMENSIONS",
    "REQUIRED_SOURCE_SURFACES",
    "load_holdout_inputs",
]
