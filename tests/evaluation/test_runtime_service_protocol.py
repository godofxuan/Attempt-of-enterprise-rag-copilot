from collections import Counter
from datetime import date
from types import SimpleNamespace

from app.ingestion.normalize import ingest_corpus
from scripts.eval_runtime_service import score_response
from scripts.prepare_runtime_service_eval import fixtures, write_fixture


def test_protocol_has_fixed_quota_and_unique_scenarios():
    _, cases = fixtures()
    assert len(cases) == 40
    assert len({case["case_id"] for case in cases}) == 40
    assert Counter(case["category"] for case in cases) == dict(
        fact=10, multi_table=6, procedure=6, acl=6, lifecycle=6, boundary=6
    )
    assert all(case["source"] == "synthetic_acceptance_not_blind" for case in cases)


def test_fixture_uses_real_parser_tables_and_effective_update(tmp_path):
    for version in ("base", "updated", "deleted"):
        root = tmp_path / version
        write_fixture(root, version)
        docs = ingest_corpus(root)
        assert sum(bool(doc.tables) for doc in docs) >= 3
        found = [doc for doc in docs if doc.doc_id == "lifecycle"]
        if version == "deleted":
            assert not found
        else:
            assert found[0].document_version.effective_from <= date(2026, 9, 7)
            assert ("60 元" if version == "updated" else "40 元") in found[0].text
        assert all(not doc.fact_ids for doc in docs)


def test_contract_does_not_reward_system_failure_or_unreviewed_accuracy():
    _, cases = fixtures()
    score = score_response(
        cases[0], 503, {"error": "unavailable"}, SimpleNamespace(documents_by_id={})
    )
    assert not score["contract_complete"]
    assert score["matched_facts"] == 0
    assert score["answer_semantics"] == "NOT_HUMAN_REVIEWED"


def test_scoring_detects_forbidden_value_even_in_source_preview():
    _, cases = fixtures()
    case = next(case for case in cases if case["case_id"] == "acl_deny_salary")
    response = {
        "mode": "not_found",
        "answer": "No evidence.",
        "sources": [{"doc_id": "salary", "preview": "4 月"}],
    }
    result = score_response(case, 200, response, SimpleNamespace(documents_by_id={}))
    assert result["known_security_failure"]
    assert not result["contract_complete"]
