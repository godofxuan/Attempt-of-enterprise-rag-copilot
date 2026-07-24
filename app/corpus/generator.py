from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Literal

from app.corpus.schemas import (
    CompanyFacts,
    CorpusProfile,
    DocumentFormat,
    DocumentMetadata,
    DocumentSection,
    DocumentSpec,
    PolicyFamily,
    PolicyVersion,
    SourceType,
    VariantType,
)


FORMAT_ORDER: tuple[DocumentFormat, ...] = ("md", "txt", "html", "csv", "jsonl")
SOURCE_TYPE_ORDER: tuple[SourceType, ...] = (
    "policy",
    "wiki",
    "email",
    "ticket",
    "meeting",
    "table",
)
SOURCE_AUTHORITY: dict[SourceType, int] = {
    "policy": 90,
    "wiki": 70,
    "email": 50,
    "ticket": 45,
    "meeting": 60,
    "table": 55,
}
SOURCE_LABELS: dict[SourceType, str] = {
    "policy": "制度摘录",
    "wiki": "知识库说明",
    "email": "通知邮件",
    "ticket": "服务工单",
    "meeting": "会议纪要",
    "table": "业务台账",
}


def load_facts(path: Path) -> CompanyFacts:
    return CompanyFacts.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_profile(path: Path) -> CorpusProfile:
    return CorpusProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _slug(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _metadata(
    policy: PolicyFamily,
    version: PolicyVersion,
    *,
    source_type: SourceType,
    variant: VariantType,
    filed_department: str | None = None,
    duplicate_of: str | None = None,
) -> DocumentMetadata:
    authority = (
        version.authority if variant == "authoritative" else SOURCE_AUTHORITY[source_type]
    )
    return DocumentMetadata(
        policy_id=policy.policy_id,
        version_id=version.version_id,
        version=version.version,
        status=version.status,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        authority=authority,
        supersedes=version.supersedes,
        actual_department=policy.department,
        filed_department=filed_department or policy.department,
        tenant=policy.tenant,
        region=policy.region,
        acl_groups=version.acl_groups,
        variant=variant,
        duplicate_of=duplicate_of,
    )


def _authoritative_document(
    policy: PolicyFamily,
    version: PolicyVersion,
) -> DocumentSpec:
    status_label = "当前生效" if version.status == "active" else "已废止"
    title = f"{policy.title} {version.version}（{status_label}）"
    fact_ids = [fact.fact_id for fact in version.facts]
    return DocumentSpec(
        doc_id=f"auth_{_slug(version.version_id)}",
        title=title,
        source_type="policy",
        format="md",
        metadata=_metadata(
            policy,
            version,
            source_type="policy",
            variant="authoritative",
        ),
        sections=[
            DocumentSection(
                heading="版本信息",
                lines=[
                    f"版本号：{version.version}。",
                    f"状态：{status_label}。",
                    f"生效日期：{version.effective_from.isoformat()}。",
                ],
            ),
            DocumentSection(
                heading="制度要求",
                lines=[fact.statement for fact in version.facts],
                fact_ids=fact_ids,
            ),
        ],
        fact_ids=fact_ids,
    )


def _weighted_choice(
    rng: random.Random,
    order: tuple[str, ...],
    weights: dict,
):
    return rng.choices(order, weights=[weights[item] for item in order], k=1)[0]


def _supporting_document(
    *,
    doc_id: str,
    policy: PolicyFamily,
    version: PolicyVersion,
    source_type: SourceType,
    document_format: DocumentFormat,
    fact_indexes: list[int],
    variant: VariantType,
    filed_department: str | None = None,
) -> DocumentSpec:
    selected_facts = [version.facts[index] for index in fact_indexes]
    fact_ids = [fact.fact_id for fact in selected_facts]
    source_label = SOURCE_LABELS[source_type]
    title = f"{policy.title} {version.version} {source_label}"
    context_line = {
        "policy": "以下内容来自制度执行摘要，正式解释以权威制度为准。",
        "wiki": "以下条目用于内部知识库检索，需结合版本状态判断。",
        "email": "以下为内部通知摘录，可能在后续制度发布后失效。",
        "ticket": "以下为服务工单中的处理依据，不替代正式制度。",
        "meeting": "以下为会议讨论记录，正式制度具有更高权威性。",
        "table": "以下为业务台账摘录，应与当前生效制度交叉核对。",
    }[source_type]
    return DocumentSpec(
        doc_id=doc_id,
        title=title,
        source_type=source_type,
        format=document_format,
        metadata=_metadata(
            policy,
            version,
            source_type=source_type,
            variant=variant,
            filed_department=filed_department,
        ),
        sections=[
            DocumentSection(heading="来源说明", lines=[context_line]),
            DocumentSection(
                heading="记录内容",
                lines=[fact.statement for fact in selected_facts],
                fact_ids=fact_ids,
            ),
        ],
        fact_ids=fact_ids,
    )


def _variant_counts(profile: CorpusProfile) -> dict[str, int]:
    return {
        "duplicate": int(profile.document_count * profile.duplicate_ratio),
        "near_duplicate": int(
            profile.document_count * profile.near_duplicate_ratio
        ),
        "misfiled": int(profile.document_count * profile.misfiled_ratio),
        "stale": int(profile.document_count * profile.stale_ratio),
    }


def _clone_document(
    original: DocumentSpec,
    *,
    doc_id: str,
    variant: Literal["duplicate", "near_duplicate"],
) -> DocumentSpec:
    metadata = original.metadata.model_copy(
        update={"variant": variant, "duplicate_of": original.doc_id},
        deep=True,
    )
    sections = [section.model_copy(deep=True) for section in original.sections]
    if variant == "near_duplicate":
        target = sections[-1]
        sections[-1] = target.model_copy(
            update={
                "lines": [
                    *target.lines,
                    "内容复核副本：核心要求不变，表述顺序可能与原记录不同。",
                ]
            },
            deep=True,
        )
    return original.model_copy(
        update={"doc_id": doc_id, "metadata": metadata, "sections": sections},
        deep=True,
    )


def _expanded_coverage_documents(
    facts: CompanyFacts,
) -> list[tuple[PolicyFamily, SourceType, DocumentFormat, list[int]]]:
    assignments: list[
        tuple[PolicyFamily, SourceType, DocumentFormat, list[int]]
    ] = []
    for policy_index, policy in enumerate(facts.policies):
        active = policy.active_version
        required_documents = max(3, len(active.facts))
        for local_index in range(required_documents):
            assignments.append(
                (
                    policy,
                    SOURCE_TYPE_ORDER[
                        (policy_index + local_index) % len(SOURCE_TYPE_ORDER)
                    ],
                    FORMAT_ORDER[
                        (policy_index * 3 + local_index) % len(FORMAT_ORDER)
                    ],
                    [local_index % len(active.facts)],
                )
            )
    return assignments


def generate_document_specs(
    facts: CompanyFacts,
    profile: CorpusProfile,
    seed: int | None = None,
) -> list[DocumentSpec]:
    effective_seed = profile.seed if seed is None else seed
    rng = random.Random(effective_seed)
    authoritative = [
        _authoritative_document(policy, version)
        for policy in facts.policies
        for version in policy.versions
    ]
    variants = _variant_counts(profile)
    base_count = profile.document_count - sum(variants.values())
    if base_count < len(authoritative):
        raise ValueError(
            "document_count and variant ratios leave too little room for "
            "one authoritative document per policy version"
        )

    supporting_count = base_count - len(authoritative)
    supporting: list[DocumentSpec] = []
    coverage = (
        _expanded_coverage_documents(facts)
        if facts.schema_version == "enterprise_facts_v2"
        else []
    )
    if len(coverage) > supporting_count:
        raise ValueError(
            "expanded corpus profile leaves too little room to cover every "
            "policy with three supporting source types"
        )
    for index in range(supporting_count):
        if index < len(coverage):
            policy, source_type, document_format, fact_indexes = coverage[index]
            version = policy.active_version
        else:
            policy = rng.choice(facts.policies)
            version = policy.active_version
            source_type = (
                SOURCE_TYPE_ORDER[index]
                if index < len(SOURCE_TYPE_ORDER)
                else _weighted_choice(
                    rng, SOURCE_TYPE_ORDER, profile.source_type_weights
                )
            )
            document_format = (
                FORMAT_ORDER[index]
                if index < len(FORMAT_ORDER)
                else _weighted_choice(
                    rng,
                    FORMAT_ORDER,
                    profile.format_weights,
                )
            )
            fact_indexes = [rng.randrange(len(version.facts))]
            if len(version.facts) > 1 and rng.random() < 0.4:
                fact_indexes = list(range(len(version.facts)))
        supporting.append(
            _supporting_document(
                doc_id=f"support_{index + 1:04d}",
                policy=policy,
                version=version,
                source_type=source_type,
                document_format=document_format,
                fact_indexes=fact_indexes,
                variant="supporting",
            )
        )

    base_documents = [*authoritative, *supporting]
    duplicates = [
        _clone_document(
            rng.choice(base_documents),
            doc_id=f"duplicate_{index + 1:04d}",
            variant="duplicate",
        )
        for index in range(variants["duplicate"])
    ]
    near_duplicates = [
        _clone_document(
            rng.choice(base_documents),
            doc_id=f"near_duplicate_{index + 1:04d}",
            variant="near_duplicate",
        )
        for index in range(variants["near_duplicate"])
    ]

    misfiled: list[DocumentSpec] = []
    for index in range(variants["misfiled"]):
        policy = rng.choice(facts.policies)
        other_departments = [
            department
            for department in facts.departments
            if department != policy.department
        ]
        misfiled.append(
            _supporting_document(
                doc_id=f"misfiled_{index + 1:04d}",
                policy=policy,
                version=policy.active_version,
                source_type=_weighted_choice(
                    rng, SOURCE_TYPE_ORDER, profile.source_type_weights
                ),
                document_format=_weighted_choice(
                    rng, FORMAT_ORDER, profile.format_weights
                ),
                fact_indexes=list(range(len(policy.active_version.facts))),
                variant="misfiled",
                filed_department=rng.choice(other_departments),
            )
        )

    stale: list[DocumentSpec] = []
    for index in range(variants["stale"]):
        policy = rng.choice(facts.policies)
        retired_versions = [
            version for version in policy.versions if version.status == "retired"
        ]
        retired_version = rng.choice(retired_versions)
        stale.append(
            _supporting_document(
                doc_id=f"stale_{index + 1:04d}",
                policy=policy,
                version=retired_version,
                source_type=_weighted_choice(
                    rng, SOURCE_TYPE_ORDER, profile.source_type_weights
                ),
                document_format=_weighted_choice(
                    rng, FORMAT_ORDER, profile.format_weights
                ),
                fact_indexes=list(
                    range(min(2, len(retired_version.facts)))
                ),
                variant="stale",
            )
        )

    documents = [
        *base_documents,
        *duplicates,
        *near_duplicates,
        *misfiled,
        *stale,
    ]
    if len(documents) != profile.document_count:
        raise AssertionError("generator did not produce the configured document count")
    return documents
