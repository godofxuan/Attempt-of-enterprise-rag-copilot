from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.corpus.artifacts import (
    load_manifest,
    validate_corpus_manifest_preset,
)
from app.corpus.eval_cases import TASK_ORDER, build_eval_splits
from app.corpus.generator import generate_document_specs
from app.corpus.schemas import CompanyFacts, CorpusProfile
from app.ingestion.normalize import ingest_corpus


class CorpusQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["enterprise_corpus_quality_v1"]
    profile_id: str
    facts_schema_version: str
    metrics: dict[str, str | int | float]
    checks: dict[str, bool]
    failures: list[str]
    release_pass: bool
    corpus_artifact_validated: bool = False
    corpus_manifest_sha256: str | None = None


def evaluate_corpus_quality(
    facts: CompanyFacts,
    profile: CorpusProfile,
) -> CorpusQualityReport:
    documents = generate_document_specs(facts, profile)
    dev_cases, test_cases = build_eval_splits(facts, documents, profile)
    eval_cases = [*dev_cases, *test_cases]
    versions = [
        version
        for policy in facts.policies
        for version in policy.versions
    ]
    atomic_facts = [
        fact
        for version in versions
        for fact in version.facts
    ]
    active_fact_ids = {
        fact.fact_id
        for policy in facts.policies
        for fact in policy.active_version.facts
    }
    supporting_fact_ids: set[str] = set()
    source_types_by_policy: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        if document.metadata.variant != "supporting":
            continue
        supporting_fact_ids.update(document.fact_ids)
        source_types_by_policy[document.metadata.policy_id].add(
            document.source_type
        )

    covered_active_fact_ids = active_fact_ids & supporting_fact_ids
    support_coverage = (
        len(covered_active_fact_ids) / len(active_fact_ids)
        if active_fact_ids
        else 0.0
    )
    eval_required_fact_ids = {
        fact_id
        for case in eval_cases
        for fact_id in case.required_fact_ids
    }
    evaluated_active_fact_ids = active_fact_ids & eval_required_fact_ids
    eval_coverage = (
        len(evaluated_active_fact_ids) / len(active_fact_ids)
        if active_fact_ids
        else 0.0
    )
    minimum_policy_source_type_count = min(
        (
            len(source_types_by_policy[policy.policy_id])
            for policy in facts.policies
        ),
        default=0,
    )
    eval_task_types = {case.task_type for case in eval_cases}
    eval_departments = {
        department
        for department in facts.departments
        if any(department in case.tags for case in eval_cases)
    }
    questions = [fact.question.casefold() for fact in atomic_facts]
    statements = [fact.statement.casefold() for fact in atomic_facts]
    case_ids = [case.case_id for case in eval_cases]
    dev_ids = {case.case_id for case in dev_cases}
    test_ids = {case.case_id for case in test_cases}
    policy_acl_groups = {
        acl_group
        for policy in facts.policies
        for acl_group in policy.active_version.acl_groups
    }
    operational_acl_groups = (
        set(facts.acl_groups) - {"external_contractors"}
    )
    unused_operational_acl_groups = (
        operational_acl_groups - policy_acl_groups
    )

    metrics: dict[str, str | int | float] = {
        "document_count": len(documents),
        "policy_count": len(facts.policies),
        "policy_version_count": len(versions),
        "atomic_fact_count": len(atomic_facts),
        "active_fact_count": len(active_fact_ids),
        "department_count": len(facts.departments),
        "acl_group_count": len(facts.acl_groups),
        "fixture_user_count": len(facts.users),
        "unused_operational_acl_group_count": len(
            unused_operational_acl_groups
        ),
        "authoritative_document_count": sum(
            document.metadata.variant == "authoritative"
            for document in documents
        ),
        "supporting_document_count": sum(
            document.metadata.variant == "supporting"
            for document in documents
        ),
        "active_fact_support_coverage": round(support_coverage, 6),
        "active_fact_eval_coverage": round(eval_coverage, 6),
        "minimum_policy_source_type_count": minimum_policy_source_type_count,
        "document_format_count": len(
            {document.format for document in documents}
        ),
        "document_source_type_count": len(
            {document.source_type for document in documents}
        ),
        "eval_dev_count": len(dev_cases),
        "eval_test_count": len(test_cases),
        "eval_case_count": len(eval_cases),
        "eval_task_type_count": len(eval_task_types),
        "eval_department_count": len(eval_departments),
    }
    checks = {
        "facts_schema_is_v2": (
            facts.schema_version == "enterprise_facts_v2"
        ),
        "document_count_matches_profile": (
            len(documents) == profile.document_count
        ),
        "policy_count_at_least_20": len(facts.policies) >= 20,
        "policy_version_count_at_least_40": len(versions) >= 40,
        "atomic_fact_count_at_least_100": len(atomic_facts) >= 100,
        "active_fact_count_at_least_50": len(active_fact_ids) >= 50,
        "department_count_at_least_12": len(facts.departments) >= 12,
        "all_operational_acl_groups_are_used": (
            not unused_operational_acl_groups
        ),
        "fact_questions_are_unique": len(questions) == len(set(questions)),
        "fact_statements_are_unique": len(statements) == len(set(statements)),
        "every_active_fact_has_supporting_content": (
            covered_active_fact_ids == active_fact_ids
        ),
        "every_active_fact_is_evaluated": (
            evaluated_active_fact_ids == active_fact_ids
        ),
        "every_policy_has_three_source_types": (
            minimum_policy_source_type_count >= 3
        ),
        "all_document_formats_are_present": (
            metrics["document_format_count"] == 5
        ),
        "all_document_source_types_are_present": (
            metrics["document_source_type_count"] == 6
        ),
        "eval_counts_match_profile": (
            len(dev_cases) == profile.eval_dev_count
            and len(test_cases) == profile.eval_test_count
        ),
        "eval_covers_all_task_types": eval_task_types == set(TASK_ORDER),
        "eval_covers_all_departments": (
            eval_departments == set(facts.departments)
        ),
        "eval_case_ids_are_unique": len(case_ids) == len(set(case_ids)),
        "eval_splits_are_disjoint": dev_ids.isdisjoint(test_ids),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return CorpusQualityReport(
        schema_version="enterprise_corpus_quality_v1",
        profile_id=profile.profile_id,
        facts_schema_version=facts.schema_version,
        metrics=metrics,
        checks=checks,
        failures=failures,
        release_pass=not failures,
    )


def evaluate_materialized_corpus_quality(
    facts: CompanyFacts,
    profile: CorpusProfile,
    corpus_dir: Path,
) -> CorpusQualityReport:
    corpus_dir = Path(corpus_dir).resolve()
    manifest_path = corpus_dir / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = load_manifest(manifest_path)
    validate_corpus_manifest_preset(manifest, facts, profile)
    records = ingest_corpus(corpus_dir)
    if len(records) != manifest.document_count:
        raise ValueError(
            "materialized corpus record count does not match its manifest"
        )
    report = evaluate_corpus_quality(facts, profile)
    return report.model_copy(
        update={
            "corpus_artifact_validated": True,
            "corpus_manifest_sha256": hashlib.sha256(
                manifest_bytes
            ).hexdigest(),
        }
    )
