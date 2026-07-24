import json
from collections import Counter
from pathlib import Path

import pytest

from app.corpus.generator import generate_document_specs, load_facts, load_profile
from app.corpus.renderers import render_document
from app.corpus.schemas import CompanyFacts


ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
CONFIG_DIR = ROOT / "data" / "v2" / "config"


def serialize_documents(documents) -> str:
    return json.dumps(
        [document.model_dump(mode="json") for document in documents],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_demo_generation_is_deterministic_and_has_exact_distribution() -> None:
    facts = load_facts(FACTS_PATH)
    profile = load_profile(CONFIG_DIR / "demo.json")

    first = generate_document_specs(facts, profile, seed=20260716)
    second = generate_document_specs(facts, profile, seed=20260716)

    assert serialize_documents(first) == serialize_documents(second)
    assert len(first) == 72
    assert len({document.doc_id for document in first}) == 72
    assert Counter(document.metadata.variant for document in first) == Counter(
        {
            "authoritative": 16,
            "supporting": 33,
            "duplicate": 5,
            "near_duplicate": 7,
            "misfiled": 4,
            "stale": 7,
        }
    )
    assert {document.format for document in first} == {
        "md",
        "txt",
        "html",
        "csv",
        "jsonl",
    }
    assert {document.source_type for document in first} == {
        "policy",
        "wiki",
        "email",
        "ticket",
        "meeting",
        "table",
    }


def test_different_seed_changes_supporting_documents_not_authoritative_facts() -> None:
    facts = load_facts(FACTS_PATH)
    profile = load_profile(CONFIG_DIR / "demo.json")

    first = generate_document_specs(facts, profile, seed=20260716)
    second = generate_document_specs(facts, profile, seed=20260717)
    first_authoritative = [
        document.model_dump(mode="json")
        for document in first
        if document.metadata.variant == "authoritative"
    ]
    second_authoritative = [
        document.model_dump(mode="json")
        for document in second
        if document.metadata.variant == "authoritative"
    ]

    assert first_authoritative == second_authoritative
    assert serialize_documents(first) != serialize_documents(second)


def test_each_policy_version_has_one_authoritative_document() -> None:
    facts = load_facts(FACTS_PATH)
    profile = load_profile(CONFIG_DIR / "demo.json")
    documents = generate_document_specs(facts, profile)
    authoritative = [
        document
        for document in documents
        if document.metadata.variant == "authoritative"
    ]

    expected_versions = {
        version.version_id
        for policy in facts.policies
        for version in policy.versions
    }
    assert Counter(document.metadata.version_id for document in authoritative) == {
        version_id: 1 for version_id in expected_versions
    }
    assert all(document.source_type == "policy" for document in authoritative)
    assert all(document.format == "md" for document in authoritative)


def test_noise_variants_have_behavioral_metadata_and_content() -> None:
    facts = load_facts(FACTS_PATH)
    profile = load_profile(CONFIG_DIR / "demo.json")
    documents = generate_document_specs(facts, profile)
    by_id = {document.doc_id: document for document in documents}

    for document in documents:
        variant = document.metadata.variant
        if variant == "duplicate":
            original = by_id[document.metadata.duplicate_of]
            assert render_document(document) == render_document(original)
        elif variant == "near_duplicate":
            original = by_id[document.metadata.duplicate_of]
            assert render_document(document) != render_document(original)
            assert document.fact_ids == original.fact_ids
        elif variant == "misfiled":
            assert document.metadata.filed_department != document.metadata.actual_department
        elif variant == "stale":
            assert document.metadata.status == "retired"


def test_benchmark_profile_builds_600_logical_documents_without_io() -> None:
    facts = load_facts(FACTS_PATH)
    profile = load_profile(CONFIG_DIR / "benchmark.json")
    documents = generate_document_specs(facts, profile)

    assert len(documents) == 600
    assert len({document.doc_id for document in documents}) == 600


def test_generator_supports_versions_with_one_atomic_fact() -> None:
    facts = load_facts(
        ROOT / "data" / "v2" / "facts" / "company_facts_v2.json"
    )
    payload = facts.model_dump(mode="json")
    for policy in payload["policies"]:
        for version in policy["versions"]:
            version["facts"] = version["facts"][:1]
    one_fact_facts = CompanyFacts.model_validate(payload)
    profile = load_profile(CONFIG_DIR / "expanded.json")

    documents = generate_document_specs(one_fact_facts, profile)

    assert len(documents) == 240
    assert all(document.fact_ids for document in documents)


def test_expanded_profile_fails_when_support_coverage_cannot_fit() -> None:
    facts = load_facts(
        ROOT / "data" / "v2" / "facts" / "company_facts_v2.json"
    )
    profile = load_profile(CONFIG_DIR / "expanded.json").model_copy(
        update={"document_count": 80}
    )

    with pytest.raises(ValueError, match="too little room"):
        generate_document_specs(facts, profile)
