from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DocumentFormat = Literal["md", "txt", "html", "csv", "jsonl", "pdf"]
SourceType = Literal[
    "policy",
    "wiki",
    "email",
    "ticket",
    "meeting",
    "table",
    "filing",
]
DocumentStatus = Literal["active", "retired"]
VariantType = Literal[
    "authoritative",
    "supporting",
    "duplicate",
    "near_duplicate",
    "misfiled",
    "stale",
]
TaskType = Literal[
    "fact_lookup",
    "version_conflict",
    "completeness",
    "comparison",
    "permission",
    "no_answer",
]
AnswerMode = Literal["answered", "permission", "not_found"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AtomicFact(StrictModel):
    fact_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    qualifiers: dict[str, str] = Field(default_factory=dict)


class PolicyVersion(StrictModel):
    version_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: DocumentStatus
    effective_from: date
    effective_to: date | None = None
    authority: int = Field(ge=1, le=100)
    supersedes: str | None = None
    acl_groups: list[str] = Field(min_length=1)
    facts: list[AtomicFact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_version(self) -> PolicyVersion:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        if self.status == "active" and self.effective_to is not None:
            raise ValueError("active version must not define effective_to")
        if self.status == "retired" and self.effective_to is None:
            raise ValueError("retired version must define effective_to")
        if len(self.acl_groups) != len(set(self.acl_groups)):
            raise ValueError("acl_groups must be unique within a version")
        fact_ids = [fact.fact_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact_id must be unique within a version")
        return self


class PolicyFamily(StrictModel):
    policy_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    department: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    region: str = Field(min_length=1)
    versions: list[PolicyVersion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_versions(self) -> PolicyFamily:
        version_ids = [version.version_id for version in self.versions]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("version_id must be unique within a policy")
        active_versions = [version for version in self.versions if version.status == "active"]
        if len(active_versions) != 1:
            raise ValueError("each policy must have exactly one active version")
        if not any(version.status == "retired" for version in self.versions):
            raise ValueError("each policy must have at least one retired version")

        known = set(version_ids)
        parent_by_version = {
            version.version_id: version.supersedes for version in self.versions
        }
        for version_id, parent in parent_by_version.items():
            if parent is not None and parent not in known:
                raise ValueError(
                    f"supersedes reference {parent!r} from {version_id!r} is unknown"
                )

        for start in version_ids:
            visited: set[str] = set()
            current: str | None = start
            while current is not None:
                if current in visited:
                    raise ValueError("supersedes chain contains a cycle")
                visited.add(current)
                current = parent_by_version[current]

        version_by_id = {version.version_id: version for version in self.versions}
        for version in self.versions:
            if version.supersedes is None:
                continue
            predecessor = version_by_id[version.supersedes]
            if (
                predecessor.effective_to is None
                or version.effective_from < predecessor.effective_to
            ):
                raise ValueError("successive version effective intervals overlap")
        return self

    @property
    def active_version(self) -> PolicyVersion:
        return next(version for version in self.versions if version.status == "active")


class UserFixture(StrictModel):
    user_id: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    region: str = Field(min_length=1)
    groups: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_groups(self) -> UserFixture:
        if len(self.groups) != len(set(self.groups)):
            raise ValueError("user groups must be unique")
        return self


class CompanyFacts(StrictModel):
    schema_version: Literal["enterprise_facts_v1", "enterprise_facts_v2"]
    company: str = Field(min_length=1)
    tenants: list[str] = Field(min_length=1)
    regions: list[str] = Field(min_length=1)
    departments: list[str] = Field(min_length=1)
    acl_groups: list[str] = Field(min_length=1)
    users: list[UserFixture] = Field(min_length=1)
    policies: list[PolicyFamily] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> CompanyFacts:
        for field_name in ("tenants", "regions", "departments", "acl_groups"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")

        user_ids = [user.user_id for user in self.users]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("user_id must be globally unique")

        known_tenants = set(self.tenants)
        known_regions = set(self.regions)
        known_departments = set(self.departments)
        known_groups = set(self.acl_groups)
        for user in self.users:
            if user.tenant not in known_tenants:
                raise ValueError(f"user {user.user_id!r} references an unknown tenant")
            if user.region not in known_regions:
                raise ValueError(f"user {user.user_id!r} references an unknown region")
            unknown_groups = set(user.groups) - known_groups
            if unknown_groups:
                raise ValueError(
                    f"user {user.user_id!r} references unknown ACL group(s): "
                    f"{sorted(unknown_groups)}"
                )

        policy_ids = [policy.policy_id for policy in self.policies]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("policy_id must be globally unique")

        version_ids: list[str] = []
        fact_ids: list[str] = []
        for policy in self.policies:
            if policy.tenant not in known_tenants:
                raise ValueError(f"policy {policy.policy_id!r} references an unknown tenant")
            if policy.region not in known_regions:
                raise ValueError(f"policy {policy.policy_id!r} references an unknown region")
            if policy.department not in known_departments:
                raise ValueError(
                    f"policy {policy.policy_id!r} references an unknown department"
                )
            for version in policy.versions:
                version_ids.append(version.version_id)
                fact_ids.extend(fact.fact_id for fact in version.facts)
                unknown_groups = set(version.acl_groups) - known_groups
                if unknown_groups:
                    raise ValueError(
                        f"version {version.version_id!r} references unknown ACL group(s): "
                        f"{sorted(unknown_groups)}"
                    )
                can_access = any(
                    user.tenant == policy.tenant
                    and user.region == policy.region
                    and bool(set(user.groups) & set(version.acl_groups))
                    for user in self.users
                )
                if not can_access:
                    raise ValueError(
                        f"version {version.version_id!r} has no authorized fixture user"
                    )

        if len(version_ids) != len(set(version_ids)):
            raise ValueError("version_id must be globally unique")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact_id must be globally unique")
        return self


class CorpusProfile(StrictModel):
    schema_version: Literal["enterprise_corpus_profile_v1"]
    profile_id: str = Field(min_length=1)
    document_count: int = Field(ge=1)
    seed: int
    format_weights: dict[DocumentFormat, int]
    source_type_weights: dict[SourceType, int]
    duplicate_ratio: float = Field(ge=0, lt=1)
    near_duplicate_ratio: float = Field(ge=0, lt=1)
    misfiled_ratio: float = Field(ge=0, lt=1)
    stale_ratio: float = Field(ge=0, lt=1)
    eval_dev_count: int = Field(ge=1)
    eval_test_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_profile(self) -> CorpusProfile:
        expected_formats = {"md", "txt", "html", "csv", "jsonl"}
        if set(self.format_weights) != expected_formats:
            raise ValueError("format_weights must define all supported formats")
        expected_sources = {"policy", "wiki", "email", "ticket", "meeting", "table"}
        if set(self.source_type_weights) != expected_sources:
            raise ValueError("source_type_weights must define all supported source types")
        if any(weight <= 0 for weight in self.format_weights.values()):
            raise ValueError("format weights must be positive")
        if any(weight <= 0 for weight in self.source_type_weights.values()):
            raise ValueError("source type weights must be positive")
        ratio_sum = (
            self.duplicate_ratio
            + self.near_duplicate_ratio
            + self.misfiled_ratio
            + self.stale_ratio
        )
        if ratio_sum > 0.6:
            raise ValueError("variant ratios must leave at least 40% base documents")
        return self


class DocumentSection(StrictModel):
    heading: str = Field(min_length=1)
    lines: list[str] = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)


class DocumentMetadata(StrictModel):
    policy_id: str
    version_id: str
    version: str
    status: DocumentStatus
    effective_from: date
    effective_to: date | None = None
    authority: int = Field(ge=1, le=100)
    supersedes: str | None = None
    actual_department: str
    filed_department: str
    tenant: str
    region: str
    acl_groups: list[str] = Field(min_length=1)
    variant: VariantType
    duplicate_of: str | None = None


class DocumentSpec(StrictModel):
    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_type: SourceType
    format: DocumentFormat
    metadata: DocumentMetadata
    sections: list[DocumentSection] = Field(min_length=1)
    fact_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fact_ids(self) -> DocumentSpec:
        section_fact_ids = {
            fact_id for section in self.sections for fact_id in section.fact_ids
        }
        if set(self.fact_ids) != section_fact_ids:
            raise ValueError("document fact_ids must match section fact_ids")
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError("document fact_ids must be unique")
        return self


class EvalUserContext(StrictModel):
    user_id: str
    tenant: str
    region: str
    groups: list[str] = Field(min_length=1)


class EvalCase(StrictModel):
    case_id: str
    question: str = Field(min_length=1)
    task_type: TaskType
    answer_mode: AnswerMode
    user_context: EvalUserContext
    required_fact_ids: list[str] = Field(default_factory=list)
    gold_doc_ids: list[str] = Field(default_factory=list)
    distractor_doc_ids: list[str] = Field(default_factory=list)
    forbidden_doc_ids: list[str] = Field(default_factory=list)
    expected_answer: str | None = None
    expected_filters: dict[str, str | list[str]] = Field(default_factory=dict)
    expected_authority_doc_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(min_length=1)


class ManifestDocument(StrictModel):
    doc_id: str
    path: str
    sha256: str
    byte_count: int = Field(ge=0)
    format: DocumentFormat
    source_type: SourceType
    variant: VariantType
    metadata: DocumentMetadata
    fact_ids: list[str]


class CorpusManifest(StrictModel):
    schema_version: Literal["enterprise_corpus_manifest_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    generator_version: str
    profile_id: str
    seed: int
    facts_sha256: str
    profile_sha256: str
    document_count: int
    counts_by_format: dict[str, int]
    counts_by_source_type: dict[str, int]
    counts_by_variant: dict[str, int]
    documents: list[ManifestDocument]


class SmokeFixtureManifest(StrictModel):
    schema_version: Literal["enterprise_smoke_fixture_v1"]
    producer: Literal["enterprise_agentic_rag_v2"]
    generator_version: str
    source_profile_id: str
    seed: int
    facts_sha256: str
    profile_sha256: str
    documents: list[ManifestDocument]
