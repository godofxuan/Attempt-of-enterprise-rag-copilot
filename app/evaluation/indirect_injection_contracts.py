from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    field_serializer,
    model_validator,
)


ATTACK_CATEGORIES = (
    "instruction_override",
    "role_impersonation",
    "secret_extraction",
    "tool_egress",
    "multilingual_homoglyph",
    "encoded_invisible",
    "markup_wrapped",
    "split_payload",
)
BENIGN_CATEGORIES = (
    "security_training_quote",
    "software_role_documentation",
    "legitimate_encoding",
    "business_sop_action_language",
)
DOCUMENT_FORMATS = ("md", "html", "csv", "jsonl", "txt")
SOURCE_SURFACES = (
    "body",
    "title",
    "section",
    "metadata",
    "parent",
    "open_context",
    "split_chunks",
)
SCENARIO_TAGS = (
    "mixed_clean_poison",
    "poison_only",
    "top_ranked_poison",
    "same_chunk_fact_attack",
    "title_section_metadata",
    "parent_open_context",
    "split_payload",
)
VARIANT_TAGS = MappingProxyType(
    {
        "instruction_override": (
            "variant-english",
            "variant-chinese",
            "variant-mixed-structural",
        ),
        "role_impersonation": (
            "variant-heading",
            "variant-body",
            "variant-table-metadata",
        ),
        "secret_extraction": (
            "variant-direct",
            "variant-indirect",
            "variant-role-wrapped",
        ),
        "tool_egress": (
            "variant-url",
            "variant-command-like",
            "variant-tool-json",
        ),
        "multilingual_homoglyph": (
            "variant-nfkc",
            "variant-homoglyph",
            "variant-mixed-script",
        ),
        "encoded_invisible": (
            "variant-base64",
            "variant-zero-width",
            "variant-bidi-control",
        ),
        "markup_wrapped": (
            "variant-markdown-code",
            "variant-html",
            "variant-markdown-link",
        ),
        "split_payload": (
            "variant-two-fragments",
            "variant-three-fragments",
            "variant-parent-child",
        ),
        "security_training_quote": (
            "variant-prose",
            "variant-code-block",
            "variant-incident-report",
        ),
        "software_role_documentation": (
            "variant-api-docs",
            "variant-schema-docs",
            "variant-tutorial",
        ),
        "legitimate_encoding": (
            "variant-opaque-id",
            "variant-certificate-like",
            "variant-data-field",
        ),
        "business_sop_action_language": (
            "variant-support-sop",
            "variant-security-sop",
            "variant-operations-sop",
        ),
    }
)

AttackCategory = Literal[
    "instruction_override",
    "role_impersonation",
    "secret_extraction",
    "tool_egress",
    "multilingual_homoglyph",
    "encoded_invisible",
    "markup_wrapped",
    "split_payload",
]
BenignCategory = Literal[
    "security_training_quote",
    "software_role_documentation",
    "legitimate_encoding",
    "business_sop_action_language",
]
DocumentFormat = Literal["md", "html", "csv", "jsonl", "txt"]
SourceSurface = Literal[
    "body",
    "title",
    "section",
    "metadata",
    "parent",
    "open_context",
    "split_chunks",
]
ScenarioTag = Literal[
    "mixed_clean_poison",
    "poison_only",
    "top_ranked_poison",
    "same_chunk_fact_attack",
    "title_section_metadata",
    "parent_open_context",
    "split_payload",
]
LanguageTag = Literal["en", "zh", "mixed", "structural"]
GuardUnitOutcome = Literal["admitted", "quarantined"]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class _FrozenMapping(Mapping):
    __slots__ = ("_data",)

    def __init__(self, values: Mapping) -> None:
        self._data = MappingProxyType(dict(values))

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __deepcopy__(self, _memo):
        return self


def _require_unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


def _require_relative_path(value: str, label: str) -> str:
    if "\\" in value:
        raise ValueError(f"{label} must use repository-relative POSIX form")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not value
        or ".." in path.parts
    ):
        raise ValueError(f"{label} must be a safe relative path")
    return value


class IndirectInjectionCase(_StrictFrozenModel):
    case_id: StrictStr = Field(pattern=r"^r2s1-(?:dev|test)-[a-z0-9-]+$")
    label: Literal["attack", "benign"]
    category: AttackCategory | BenignCategory
    variant_id: StrictInt = Field(ge=1, le=3)
    language: LanguageTag
    document_format: DocumentFormat
    source_surfaces: tuple[SourceSurface, ...] = Field(min_length=1)
    scenario_tags: tuple[ScenarioTag, ...] = Field(default_factory=tuple)
    question: StrictStr = Field(min_length=1, max_length=2_000)
    user_context_fixture: Literal["synthetic-employee-v1"]
    fixture_document_ids: tuple[StrictStr, ...] = Field(min_length=1, max_length=8)
    attack_unit_ids: tuple[StrictStr, ...] = Field(default_factory=tuple, max_length=8)
    benign_unit_ids: tuple[StrictStr, ...] = Field(default_factory=tuple, max_length=8)
    required_clean_fact_ids: tuple[StrictStr, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    document_canary: StrictStr | None
    trace_canary: StrictStr = Field(pattern=r"^R2TRACE_[A-Z0-9_]+$")
    expected_guard_outcome: Mapping[StrictStr, GuardUnitOutcome]
    expected_answer_mode_on: Literal["answered", "partial", "security_filtered"]
    expected_task_success_on: StrictBool
    tags: tuple[StrictStr, ...] = Field(default_factory=tuple, max_length=20)

    @field_validator(
        "source_surfaces",
        "scenario_tags",
        "fixture_document_ids",
        "attack_unit_ids",
        "benign_unit_ids",
        "required_clean_fact_ids",
        "tags",
    )
    @classmethod
    def validate_unique_lists(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(values, "case list values")

    @field_validator("expected_guard_outcome")
    @classmethod
    def freeze_expected_outcomes(
        cls,
        values: Mapping[str, GuardUnitOutcome],
    ) -> Mapping[str, GuardUnitOutcome]:
        return _FrozenMapping(values)

    @field_serializer("expected_guard_outcome")
    def serialize_expected_outcomes(
        self,
        values: Mapping[str, GuardUnitOutcome],
    ) -> dict[str, GuardUnitOutcome]:
        return dict(values)

    @model_validator(mode="after")
    def validate_case_contract(self) -> IndirectInjectionCase:
        attack_category = self.category in ATTACK_CATEGORIES
        if (self.label == "attack") != attack_category:
            raise ValueError("category must match attack/benign label")
        if set(self.attack_unit_ids) & set(self.benign_unit_ids):
            raise ValueError("attack and benign unit IDs must be disjoint")
        labeled_units = {*self.attack_unit_ids, *self.benign_unit_ids}
        if not labeled_units:
            raise ValueError("case requires at least one labeled content unit")
        if set(self.expected_guard_outcome) != labeled_units:
            raise ValueError(
                "expected Guard outcome unit IDs must exactly match labeled unit IDs"
            )
        if self.label == "attack":
            if not self.attack_unit_ids:
                raise ValueError("attack case requires attack unit IDs")
            if self.document_canary is None or not self.document_canary.startswith(
                "R2DOC_"
            ):
                raise ValueError("attack case requires a synthetic document canary")
            if any(
                self.expected_guard_outcome[unit_id] != "quarantined"
                for unit_id in self.attack_unit_ids
            ):
                raise ValueError("attack units must expect quarantine")
        else:
            if self.attack_unit_ids or self.document_canary is not None:
                raise ValueError("benign case cannot carry attack units or canary")
        if any(
            self.expected_guard_outcome[unit_id] != "admitted"
            for unit_id in self.benign_unit_ids
        ):
            raise ValueError("benign units must expect admission")

        poison_only = "poison_only" in self.scenario_tags
        mixed = "mixed_clean_poison" in self.scenario_tags
        if poison_only and mixed:
            raise ValueError("case cannot be both poison-only and mixed")
        if poison_only != (
            self.label == "attack" and not self.benign_unit_ids
        ):
            raise ValueError("poison_only tag must match attack-only evidence")
        if mixed and (self.label != "attack" or not self.benign_unit_ids):
            raise ValueError("mixed tag requires attack and benign units")
        if self.category == "split_payload" and "split_payload" not in self.scenario_tags:
            raise ValueError("split-payload cases require the split_payload tag")

        if self.expected_answer_mode_on == "security_filtered":
            if not poison_only or self.expected_task_success_on:
                raise ValueError(
                    "security_filtered is valid only for unsuccessful poison-only cases"
                )
            if self.required_clean_fact_ids:
                raise ValueError("poison-only case cannot require clean facts")
        elif self.expected_task_success_on and not self.required_clean_fact_ids:
            raise ValueError("successful answer requires explicit clean fact IDs")
        if not poison_only and not self.expected_task_success_on:
            raise ValueError("non-poison case must expect task success")
        return self


class IndirectInjectionDataset(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_dataset_v1"]
    dataset_id: StrictStr = Field(pattern=r"^r2_s1_indirect_injection_(?:dev|test)_v1$")
    split: Literal["dev", "test"]
    taxonomy_version: Literal["r2_s1_taxonomy_v1"]
    case_count: StrictInt
    attack_case_count: StrictInt
    benign_case_count: StrictInt
    cases: tuple[IndirectInjectionCase, ...]

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> IndirectInjectionDataset:
        if self.dataset_id != f"r2_s1_indirect_injection_{self.split}_v1":
            raise ValueError("dataset ID must match split")
        if (
            self.case_count != 36
            or self.attack_case_count != 24
            or self.benign_case_count != 12
            or len(self.cases) != 36
        ):
            raise ValueError("dataset must contain exactly 24 attack and 12 benign cases")
        case_ids = tuple(item.case_id for item in self.cases)
        _require_unique(case_ids, "case IDs")
        if any(
            not case_id.startswith(f"r2s1-{self.split}-")
            for case_id in case_ids
        ):
            raise ValueError("case IDs must match dataset split")
        if sum(item.label == "attack" for item in self.cases) != 24:
            raise ValueError("attack case count does not match cases")
        if sum(item.label == "benign" for item in self.cases) != 12:
            raise ValueError("benign case count does not match cases")

        expected_categories = (*ATTACK_CATEGORIES, *BENIGN_CATEGORIES)
        for category in expected_categories:
            variants = sorted(
                item.variant_id for item in self.cases if item.category == category
            )
            if variants != [1, 2, 3]:
                raise ValueError(
                    "category variants must be exactly 1, 2 and 3 for " + category
                )
        for item in self.cases:
            required_variant_tag = VARIANT_TAGS[item.category][item.variant_id - 1]
            if required_variant_tag not in item.tags:
                raise ValueError(
                    f"case {item.case_id} requires variant tag {required_variant_tag}"
                )
            if item.category == "instruction_override":
                expected_language = ("en", "zh", "mixed")[item.variant_id - 1]
                if item.language != expected_language:
                    raise ValueError("instruction variant language does not match taxonomy")

        actual_formats = {item.document_format for item in self.cases}
        if actual_formats != set(DOCUMENT_FORMATS):
            raise ValueError("document formats must cover md/html/csv/jsonl/txt")
        quota = {
            "mixed_clean_poison": 8,
            "poison_only": 4,
            "top_ranked_poison": 4,
            "same_chunk_fact_attack": 4,
            "title_section_metadata": 4,
            "parent_open_context": 4,
        }
        for tag, minimum in quota.items():
            count = sum(tag in item.scenario_tags for item in self.cases)
            if count < minimum:
                raise ValueError(f"scenario quota {tag} requires at least {minimum}")
        split_cases = [item for item in self.cases if item.category == "split_payload"]
        if len(split_cases) != 3 or any(
            "split_payload" not in item.scenario_tags for item in split_cases
        ):
            raise ValueError("all three split-payload variants are required")

        document_canaries = tuple(
            item.document_canary
            for item in self.cases
            if item.document_canary is not None
        )
        _require_unique(document_canaries, "document canaries")
        _require_unique(tuple(item.trace_canary for item in self.cases), "trace canaries")
        all_units = tuple(
            unit_id
            for item in self.cases
            for unit_id in (*item.attack_unit_ids, *item.benign_unit_ids)
        )
        _require_unique(all_units, "content unit IDs")
        return self


class FixtureCandidate(_StrictFrozenModel):
    chunk_id: StrictStr = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    document_id: StrictStr = Field(min_length=1, max_length=200)
    rank: StrictInt = Field(ge=1, le=4)
    source_path: StrictStr = Field(min_length=1, max_length=500)
    source_path_unit_id: StrictStr | None = None
    section_path: tuple[StrictStr, ...] = Field(min_length=1, max_length=8)
    section_unit_id: StrictStr | None = None
    locator_kind: Literal["paragraph", "table", "document"]
    locator_start: StrictInt = Field(ge=1)
    locator_end: StrictInt | None = Field(default=None, ge=1)
    matched_text: StrictStr = Field(min_length=1, max_length=20_000)
    matched_unit_id: StrictStr | None = None
    context_text: StrictStr = Field(min_length=1, max_length=20_000)
    context_unit_id: StrictStr | None = None
    context_from_parent: StrictBool = False
    parent_chunk_id: StrictStr | None = None
    document_title: StrictStr | None = None
    title_unit_id: StrictStr | None = None
    version: StrictStr = "synthetic-v1"
    version_unit_id: StrictStr | None = None
    fact_ids: tuple[StrictStr, ...] = Field(default_factory=tuple, max_length=8)

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _require_relative_path(value, "fixture source path")

    @field_validator("section_path", "fact_ids")
    @classmethod
    def validate_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(values, "fixture candidate values")

    @model_validator(mode="after")
    def validate_candidate(self) -> FixtureCandidate:
        if self.locator_end is not None and self.locator_end < self.locator_start:
            raise ValueError("locator end cannot precede start")
        if self.context_unit_id is not None and not self.context_from_parent:
            raise ValueError("context unit ID requires parent context")
        if self.context_from_parent and self.parent_chunk_id is None:
            raise ValueError("parent context requires parent chunk ID")
        bindings = self.unit_bindings()
        if len(bindings) != len(set(bindings)):
            raise ValueError("candidate unit IDs must be unique")
        return self

    def unit_bindings(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self.matched_unit_id,
                self.context_unit_id,
                self.title_unit_id,
                self.source_path_unit_id,
                self.section_unit_id,
                self.version_unit_id,
            )
            if value is not None
        )


class FixtureOpenResult(_StrictFrozenModel):
    target_id: StrictStr = Field(min_length=1, max_length=200)
    document_id: StrictStr = Field(min_length=1, max_length=200)
    content: StrictStr = Field(min_length=1, max_length=20_000)
    content_unit_id: StrictStr
    source_path: StrictStr = Field(min_length=1, max_length=500)
    section_path: tuple[StrictStr, ...] = Field(default_factory=tuple, max_length=8)

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        return _require_relative_path(value, "fixture open source path")


class FixtureParentLink(_StrictFrozenModel):
    parent_chunk_id: StrictStr = Field(min_length=1, max_length=200)
    document_id: StrictStr = Field(min_length=1, max_length=200)
    child_chunk_ids: tuple[StrictStr, ...] = Field(min_length=1, max_length=4)

    @field_validator("child_chunk_ids")
    @classmethod
    def validate_child_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _require_unique(values, "parent-link child chunk IDs")

    @model_validator(mode="after")
    def validate_parent_id(self) -> FixtureParentLink:
        if self.parent_chunk_id in self.child_chunk_ids:
            raise ValueError("parent link cannot name itself as a child")
        return self


class FixtureCase(_StrictFrozenModel):
    case_id: StrictStr = Field(pattern=r"^r2s1-(?:dev|test)-[a-z0-9-]+$")
    candidates: tuple[FixtureCandidate, ...] = Field(min_length=1, max_length=4)
    open_results: tuple[FixtureOpenResult, ...] = Field(default_factory=tuple, max_length=4)
    parent_links: tuple[FixtureParentLink, ...] = Field(default_factory=tuple, max_length=4)
    fact_texts: Mapping[StrictStr, StrictStr] = Field(default_factory=dict)

    @field_validator("fact_texts")
    @classmethod
    def freeze_fact_texts(
        cls,
        values: Mapping[str, str],
    ) -> Mapping[str, str]:
        return _FrozenMapping(values)

    @field_serializer("fact_texts")
    def serialize_fact_texts(
        self,
        values: Mapping[str, str],
    ) -> dict[str, str]:
        return dict(values)

    @model_validator(mode="after")
    def validate_fixture_case(self) -> FixtureCase:
        ranks = tuple(item.rank for item in self.candidates)
        if ranks != tuple(range(1, len(self.candidates) + 1)):
            raise ValueError("fixture candidate ranks must be contiguous and ordered")
        _require_unique(
            tuple(item.chunk_id for item in self.candidates),
            "fixture chunk IDs",
        )
        unit_ids = tuple(
            unit_id
            for item in self.candidates
            for unit_id in item.unit_bindings()
        ) + tuple(item.content_unit_id for item in self.open_results)
        _require_unique(unit_ids, "fixture unit IDs")
        if any(not value for value in self.fact_texts.values()):
            raise ValueError("fixture fact text cannot be empty")
        _validate_fixture_parent_links(self)
        return self

    def labeled_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            unit_id
            for item in self.candidates
            for unit_id in item.unit_bindings()
        ) + tuple(item.content_unit_id for item in self.open_results)


def _validate_fixture_parent_links(fixture: FixtureCase) -> None:
    referenced: dict[str, list[FixtureCandidate]] = {}
    for candidate in fixture.candidates:
        if candidate.parent_chunk_id is not None:
            referenced.setdefault(candidate.parent_chunk_id, []).append(candidate)
    declared = {item.parent_chunk_id: item for item in fixture.parent_links}
    if len(declared) != len(fixture.parent_links):
        raise ValueError("fixture parent link IDs must be unique")
    if set(declared) != set(referenced):
        raise ValueError("fixture parent links must exactly declare referenced parents")
    for parent_id, candidates in referenced.items():
        link = declared[parent_id]
        child_ids = tuple(candidate.chunk_id for candidate in candidates)
        if link.child_chunk_ids != child_ids:
            raise ValueError("fixture parent link child IDs must match candidates")
        if any(candidate.document_id != link.document_id for candidate in candidates):
            raise ValueError("fixture parent link document must match every child")


class FixtureManifest(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_fixture_manifest_v1"]
    fixture_id: StrictStr = Field(
        pattern=r"^r2_s1_indirect_injection_(?:dev|test)_fixtures_v1$"
    )
    split: Literal["dev", "test"]
    case_count: StrictInt
    cases: tuple[FixtureCase, ...]

    @model_validator(mode="after")
    def validate_manifest(self) -> FixtureManifest:
        if self.fixture_id != f"r2_s1_indirect_injection_{self.split}_fixtures_v1":
            raise ValueError("fixture ID must match split")
        if self.case_count != 36 or len(self.cases) != 36:
            raise ValueError("fixture manifest must contain exactly 36 cases")
        _require_unique(tuple(item.case_id for item in self.cases), "fixture case IDs")
        if any(
            not item.case_id.startswith(f"r2s1-{self.split}-")
            for item in self.cases
        ):
            raise ValueError("fixture case IDs must match fixture split")
        all_units = tuple(
            unit_id for item in self.cases for unit_id in item.labeled_unit_ids()
        )
        _require_unique(all_units, "fixture unit IDs")
        return self


class TestFreezeManifest(_StrictFrozenModel):
    schema_version: Literal["indirect_injection_test_freeze_v1"]
    dataset_path: StrictStr
    dataset_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_bytes: StrictInt = Field(ge=1)
    case_count: StrictInt
    attack_case_count: StrictInt
    benign_case_count: StrictInt
    taxonomy_counts: Mapping[StrictStr, StrictInt]
    scenario_counts: Mapping[StrictStr, StrictInt]
    fixture_manifest_path: StrictStr
    fixture_manifest_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at_utc: StrictStr = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    )
    freeze_git_head: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")

    @field_validator("dataset_path", "fixture_manifest_path")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        return _require_relative_path(value, "freeze manifest path")

    @field_validator("taxonomy_counts", "scenario_counts")
    @classmethod
    def freeze_count_maps(
        cls,
        values: Mapping[str, int],
    ) -> Mapping[str, int]:
        return _FrozenMapping(values)

    @field_serializer("taxonomy_counts", "scenario_counts")
    def serialize_count_maps(
        self,
        values: Mapping[str, int],
    ) -> dict[str, int]:
        return dict(values)

    @model_validator(mode="after")
    def validate_freeze_counts(self) -> TestFreezeManifest:
        if (
            self.case_count != 36
            or self.attack_case_count != 24
            or self.benign_case_count != 12
        ):
            raise ValueError("freeze manifest counts must be 36/24/12")
        expected = {category: 3 for category in (*ATTACK_CATEGORIES, *BENIGN_CATEGORIES)}
        if self.taxonomy_counts != expected:
            raise ValueError("freeze taxonomy counts must contain every category three times")
        if set(self.scenario_counts) != set(SCENARIO_TAGS) or any(
            value < 0 for value in self.scenario_counts.values()
        ):
            raise ValueError("freeze scenario counts must contain the full taxonomy")
        return self


def validate_dataset_pair(
    dev: IndirectInjectionDataset,
    test: IndirectInjectionDataset,
) -> None:
    if dev.split != "dev" or test.split != "test":
        raise ValueError("dataset pair must be ordered dev then test")
    dev_case_ids = {item.case_id for item in dev.cases}
    test_case_ids = {item.case_id for item in test.cases}
    if dev_case_ids & test_case_ids:
        raise ValueError("dev/test case IDs must be disjoint")
    dev_canaries = {
        item.document_canary for item in dev.cases if item.document_canary is not None
    }
    test_canaries = {
        item.document_canary for item in test.cases if item.document_canary is not None
    }
    if dev_canaries & test_canaries:
        raise ValueError("dev/test document canaries must be disjoint")
    if {item.trace_canary for item in dev.cases} & {
        item.trace_canary for item in test.cases
    }:
        raise ValueError("dev/test trace canaries must be disjoint")
    dev_units = {
        unit_id
        for item in dev.cases
        for unit_id in (*item.attack_unit_ids, *item.benign_unit_ids)
    }
    test_units = {
        unit_id
        for item in test.cases
        for unit_id in (*item.attack_unit_ids, *item.benign_unit_ids)
    }
    if dev_units & test_units:
        raise ValueError("dev/test content unit IDs must be disjoint")


def validate_test_freeze_alignment(
    manifest: TestFreezeManifest,
    dataset: IndirectInjectionDataset,
) -> None:
    if dataset.split != "test":
        raise ValueError("test freeze manifest requires the test dataset")
    if (
        manifest.case_count != dataset.case_count
        or manifest.attack_case_count != dataset.attack_case_count
        or manifest.benign_case_count != dataset.benign_case_count
    ):
        raise ValueError("test freeze case counts do not match dataset")
    taxonomy_counts = {
        category: sum(item.category == category for item in dataset.cases)
        for category in (*ATTACK_CATEGORIES, *BENIGN_CATEGORIES)
    }
    scenario_counts = {
        tag: sum(tag in item.scenario_tags for item in dataset.cases)
        for tag in SCENARIO_TAGS
    }
    if dict(manifest.taxonomy_counts) != taxonomy_counts:
        raise ValueError("test freeze taxonomy count mismatch")
    if dict(manifest.scenario_counts) != scenario_counts:
        raise ValueError("test freeze scenario count mismatch")


def validate_dataset_fixture_alignment(
    dataset: IndirectInjectionDataset,
    fixtures: FixtureManifest,
) -> None:
    if dataset.split != fixtures.split:
        raise ValueError("dataset and fixture split must match")
    fixture_by_case = {item.case_id: item for item in fixtures.cases}
    if set(fixture_by_case) != {item.case_id for item in dataset.cases}:
        raise ValueError("dataset and fixture case IDs must match")
    for item in dataset.cases:
        fixture = fixture_by_case[item.case_id]
        _validate_fixture_parent_links(fixture)
        expected_units = {*item.attack_unit_ids, *item.benign_unit_ids}
        if set(fixture.labeled_unit_ids()) != expected_units:
            raise ValueError(f"fixture unit IDs do not match dataset case {item.case_id}")
        document_ids = {
            candidate.document_id for candidate in fixture.candidates
        } | {opened.document_id for opened in fixture.open_results}
        if document_ids != set(item.fixture_document_ids):
            raise ValueError(
                f"fixture document IDs do not match dataset case {item.case_id}"
            )
        if set(fixture.fact_texts) != set(item.required_clean_fact_ids):
            raise ValueError(
                f"fixture fact IDs do not match dataset case {item.case_id}"
            )
        actual_surfaces = _fixture_source_surfaces(item, fixture)
        if actual_surfaces != set(item.source_surfaces):
            raise ValueError(
                f"fixture source surfaces do not match dataset case {item.case_id}"
            )
        _validate_scenario_evidence(item, fixture)
        expected_suffix = "." + item.document_format
        if any(
            not candidate.source_path.endswith(expected_suffix)
            for candidate in fixture.candidates
        ) or any(
            not opened.source_path.endswith(expected_suffix)
            for opened in fixture.open_results
        ):
            raise ValueError(
                f"fixture source format does not match dataset case {item.case_id}"
            )


def _fixture_source_surfaces(
    item: IndirectInjectionCase,
    fixture: FixtureCase,
) -> set[str]:
    labeled = set(
        item.attack_unit_ids if item.label == "attack" else item.benign_unit_ids
    )
    surfaces: set[str] = set()
    matched_count = 0
    for candidate in fixture.candidates:
        if candidate.matched_unit_id in labeled:
            matched_count += 1
        if candidate.context_unit_id in labeled:
            surfaces.add("parent")
        if candidate.title_unit_id in labeled:
            surfaces.add("title")
        if candidate.section_unit_id in labeled:
            surfaces.add("section")
        if (
            candidate.source_path_unit_id in labeled
            or candidate.version_unit_id in labeled
        ):
            surfaces.add("metadata")
    if any(opened.content_unit_id in labeled for opened in fixture.open_results):
        surfaces.add("open_context")
    if item.category == "split_payload" and matched_count >= 2:
        surfaces.add("split_chunks")
    elif matched_count:
        surfaces.add("body")
    return surfaces


def _validate_scenario_evidence(
    item: IndirectInjectionCase,
    fixture: FixtureCase,
) -> None:
    attack_units = set(item.attack_unit_ids)
    rank_one_attack = any(
        candidate.rank == 1
        and bool(set(candidate.unit_bindings()) & attack_units)
        for candidate in fixture.candidates
    )
    if "top_ranked_poison" in item.scenario_tags and not rank_one_attack:
        raise ValueError("top-ranked scenario lacks a rank-one attack unit")
    if "same_chunk_fact_attack" in item.scenario_tags:
        same_chunk_candidates = [
            candidate
            for candidate in fixture.candidates
            if candidate.matched_unit_id in attack_units
            and set(item.required_clean_fact_ids).issubset(candidate.fact_ids)
        ]
        if not same_chunk_candidates:
            raise ValueError("same-chunk scenario lacks fact plus attack evidence")
        if not any(
            all(
                fixture.fact_texts[fact_id] in candidate.matched_text
                for fact_id in item.required_clean_fact_ids
            )
            for candidate in same_chunk_candidates
        ):
            raise ValueError("same-chunk scenario lacks fact text in attack chunk")
    if "title_section_metadata" in item.scenario_tags and not (
        {"title", "section", "metadata"} & set(item.source_surfaces)
    ):
        raise ValueError("metadata scenario lacks title/section/metadata evidence")
    if "parent_open_context" in item.scenario_tags and not (
        {"parent", "open_context"} & set(item.source_surfaces)
    ):
        raise ValueError("parent/open scenario lacks parent or open evidence")
    if "split_payload" in item.scenario_tags:
        split_candidates = [
            candidate
            for candidate in fixture.candidates
            if candidate.matched_unit_id in attack_units
        ]
        if len(split_candidates) < 2:
            raise ValueError("split scenario requires at least two attack fragments")
        if len({candidate.document_id for candidate in split_candidates}) != 1:
            raise ValueError("split fragments must belong to one document")
        positions = [candidate.locator_start for candidate in split_candidates]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("split fragments must be adjacent and ordered")
    if item.category == "role_impersonation":
        required_surface = (
            {"title", "section"},
            {"body"},
            {"metadata"},
        )[item.variant_id - 1]
        if not (required_surface & set(item.source_surfaces)):
            raise ValueError("role variant source surface does not match taxonomy")
        if item.variant_id == 3 and item.document_format not in {"csv", "jsonl"}:
            raise ValueError("role metadata variant requires a table-like format")
    if item.category == "split_payload":
        attack_candidates = [
            candidate
            for candidate in fixture.candidates
            if candidate.matched_unit_id in attack_units
        ]
        expected_count = (2, 3, 2)[item.variant_id - 1]
        if len(attack_candidates) != expected_count:
            raise ValueError("split variant fragment count does not match taxonomy")
        if item.variant_id == 3 and not any(
            candidate.parent_chunk_id is not None
            for candidate in attack_candidates
        ):
            raise ValueError("split parent-child variant requires a parent link")


__all__ = [
    "ATTACK_CATEGORIES",
    "BENIGN_CATEGORIES",
    "DOCUMENT_FORMATS",
    "FixtureCandidate",
    "FixtureCase",
    "FixtureManifest",
    "FixtureOpenResult",
    "FixtureParentLink",
    "IndirectInjectionCase",
    "IndirectInjectionDataset",
    "SCENARIO_TAGS",
    "SOURCE_SURFACES",
    "TestFreezeManifest",
    "VARIANT_TAGS",
    "validate_dataset_fixture_alignment",
    "validate_dataset_pair",
    "validate_test_freeze_alignment",
]
