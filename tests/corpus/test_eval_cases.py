import hashlib
from collections import Counter
from pathlib import Path

from app.corpus.eval_cases import (
    build_test_manifest_line,
    build_eval_splits,
    serialize_eval_cases,
)
from app.corpus.generator import generate_document_specs, load_facts, load_profile


ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data" / "v2" / "facts" / "company_facts_v1.json"
PROFILE_PATH = ROOT / "data" / "v2" / "config" / "demo.json"


def build():
    facts = load_facts(FACTS_PATH)
    profile = load_profile(PROFILE_PATH)
    documents = generate_document_specs(facts, profile)
    dev, test = build_eval_splits(facts, documents, profile)
    return facts, documents, dev, test


def is_visible(document, user_context) -> bool:
    return (
        document.metadata.tenant == user_context.tenant
        and document.metadata.region == user_context.region
        and bool(set(document.metadata.acl_groups) & set(user_context.groups))
    )


def test_eval_splits_have_exact_counts_and_no_overlap() -> None:
    _, _, dev, test = build()

    assert len(dev) == 24
    assert len(test) == 28
    assert {case.case_id for case in dev}.isdisjoint(
        case.case_id for case in test
    )
    assert {case.question for case in dev}.isdisjoint(
        case.question for case in test
    )
    assert len({case.case_id for case in [*dev, *test]}) == 52
    assert len({case.question for case in [*dev, *test]}) == 52


def test_each_split_covers_all_enterprise_task_types() -> None:
    _, _, dev, test = build()
    expected = {
        "fact_lookup",
        "version_conflict",
        "completeness",
        "comparison",
        "permission",
        "no_answer",
    }

    assert {case.task_type for case in dev} == expected
    assert {case.task_type for case in test} == expected
    dev_counts = Counter(case.task_type for case in dev)
    test_counts = Counter(case.task_type for case in test)
    assert dev_counts["permission"] == 2
    assert test_counts["permission"] == 3
    assert dev_counts + test_counts == Counter(
        {
            "fact_lookup": 15,
            "version_conflict": 8,
            "completeness": 8,
            "comparison": 8,
            "permission": 5,
            "no_answer": 8,
        }
    )


def test_answered_cases_reference_accessible_documents_containing_gold_facts() -> None:
    _, documents, dev, test = build()
    by_id = {document.doc_id: document for document in documents}

    for case in [*dev, *test]:
        if case.answer_mode != "answered":
            continue
        assert case.required_fact_ids
        assert case.gold_doc_ids
        supported_fact_ids: set[str] = set()
        for doc_id in case.gold_doc_ids:
            document = by_id[doc_id]
            assert is_visible(document, case.user_context)
            supported_fact_ids.update(document.fact_ids)
        assert set(case.required_fact_ids).issubset(supported_fact_ids)


def test_permission_cases_only_reference_inaccessible_forbidden_documents() -> None:
    _, documents, dev, test = build()
    by_id = {document.doc_id: document for document in documents}
    permission_cases = [
        case for case in [*dev, *test] if case.answer_mode == "permission"
    ]

    assert permission_cases
    for case in permission_cases:
        assert case.gold_doc_ids == []
        assert case.forbidden_doc_ids
        assert all(
            not is_visible(by_id[doc_id], case.user_context)
            for doc_id in case.forbidden_doc_ids
        )


def test_version_conflict_cases_prefer_active_authoritative_documents() -> None:
    _, documents, dev, test = build()
    by_id = {document.doc_id: document for document in documents}

    for case in [*dev, *test]:
        if case.task_type != "version_conflict":
            continue
        assert case.expected_authority_doc_ids == case.gold_doc_ids
        assert all(by_id[doc_id].metadata.status == "active" for doc_id in case.gold_doc_ids)
        assert all(
            by_id[doc_id].metadata.status == "retired"
            for doc_id in case.distractor_doc_ids
        )


def test_eval_serialization_and_test_hash_are_byte_stable() -> None:
    facts = load_facts(FACTS_PATH)
    profile = load_profile(PROFILE_PATH)
    documents = generate_document_specs(facts, profile)
    first_dev, first_test = build_eval_splits(facts, documents, profile)
    second_dev, second_test = build_eval_splits(facts, documents, profile)

    assert serialize_eval_cases(first_dev) == serialize_eval_cases(second_dev)
    test_bytes = serialize_eval_cases(first_test)
    assert test_bytes == serialize_eval_cases(second_test)
    expected_hash = hashlib.sha256(test_bytes).hexdigest()
    assert build_test_manifest_line(test_bytes) == f"{expected_hash}  test.json\n"
